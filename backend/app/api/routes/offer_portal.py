import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import get_db
from app.models import (
    CandidateProcess,
    JobApplication,
    Offer,
    OfferPortalLink,
    OfferResponse,
    Onboarding,
)
from app.redis_client import get_offer_portal_store
from app.schemas.offer_portal import (
    CandidateOfferResponse,
    CandidateOfferView,
    OfferPortalDetailRequest,
    OfferPortalRespondRequest,
    OfferPortalStatusResponse,
    OfferPortalTokenRequest,
    OfferPortalVerifiedResponse,
    OfferPortalVerifyRequest,
)
from app.schemas.onboarding import (
    CandidateOnboardingView,
    PortalOnboardingAbandonRequest,
    PortalOnboardingConfirmDateRequest,
    PortalOnboardingProposeDateRequest,
)
from app.services.audit import record_audit
from app.services.candidate_process import change_candidate_process_stage
from app.services.offer_portal import (
    OfferPortalVerificationStore,
    hash_portal_token,
    phone_verification_digest,
    portal_link_is_expired,
)
from app.services.onboarding import (
    OnboardingConflictError,
    OnboardingValidationError,
    abandon_onboarding,
    candidate_confirm_date,
    candidate_propose_date,
    create_onboarding_for_acceptance,
    find_event_by_key,
    onboarding_action_owner,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
PortalStore = Annotated[OfferPortalVerificationStore, Depends(get_offer_portal_store)]


def _get_portal_link(db: Session, token: str) -> OfferPortalLink:
    link = db.scalar(
        select(OfferPortalLink)
        .where(OfferPortalLink.token_hash == hash_portal_token(token))
        .options(
            selectinload(OfferPortalLink.offer)
            .selectinload(Offer.application)
            .selectinload(JobApplication.candidate),
            selectinload(OfferPortalLink.offer)
            .selectinload(Offer.application)
            .selectinload(JobApplication.job),
            selectinload(OfferPortalLink.offer).selectinload(Offer.versions),
            selectinload(OfferPortalLink.offer).selectinload(Offer.candidate_response),
            selectinload(OfferPortalLink.offer)
            .selectinload(Offer.onboarding)
            .selectinload(Onboarding.events),
            selectinload(OfferPortalLink.version),
            selectinload(OfferPortalLink.response),
        )
    )
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="候选人链接不存在或已失效",
        )
    return link


def _ensure_link_usable(link: OfferPortalLink) -> None:
    if link.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="候选人链接已撤回",
        )
    if portal_link_is_expired(link.expires_at):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="候选人链接已过期",
        )


def _get_locked_offer(db: Session, offer_id: uuid.UUID) -> Offer:
    offer = db.scalar(
        select(Offer)
        .where(Offer.id == offer_id)
        .with_for_update()
        .options(
            selectinload(Offer.application)
            .selectinload(JobApplication.process)
            .selectinload(CandidateProcess.events),
            selectinload(Offer.application).selectinload(JobApplication.candidate),
            selectinload(Offer.application).selectinload(JobApplication.job),
            selectinload(Offer.versions),
            selectinload(Offer.portal_links).selectinload(OfferPortalLink.response),
            selectinload(Offer.candidate_response),
            selectinload(Offer.onboarding).selectinload(Onboarding.events),
        )
        .execution_options(populate_existing=True)
    )
    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="候选人链接不存在或已失效",
        )
    return offer


def _response_matches(response: OfferResponse, payload: OfferPortalRespondRequest) -> bool:
    return (
        response.idempotency_key == payload.idempotency_key
        and response.decision == payload.decision
        and response.rejection_reason_code == payload.rejection_reason_code
        and response.rejection_note == payload.rejection_note
    )


def _response_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="候选人已经完成 Offer 回应，不能再次修改",
    )


def _candidate_onboarding_view(onboarding: Onboarding) -> CandidateOnboardingView:
    return CandidateOnboardingView(
        status=onboarding.status,
        version=onboarding.version,
        action_owner=onboarding_action_owner(onboarding),
        expected_start_date=onboarding.offer.current_version.expected_start_date,
        candidate_proposed_date=onboarding.candidate_proposed_date,
        recruiter_proposed_date=onboarding.recruiter_proposed_date,
        confirmed_start_date=onboarding.confirmed_start_date,
        actual_start_date=onboarding.actual_start_date,
        abandonment_source=onboarding.abandonment_source,
        abandonment_reason_code=onboarding.abandonment_reason_code,
    )


def _candidate_offer_view(link: OfferPortalLink) -> CandidateOfferView:
    offer = link.offer
    version = link.version
    response = offer.candidate_response
    progress = {
        "accepted": "accepted",
        "declined": "declined",
    }.get(offer.status, "offer_pending_response")
    return CandidateOfferView(
        candidate_name=offer.application.candidate.full_name,
        job_title=offer.application.job.title,
        progress=progress,
        currency="CNY",
        monthly_salary=version.monthly_salary,
        annual_salary_months=version.annual_salary_months,
        probation_months=version.probation_months,
        probation_monthly_salary=version.probation_monthly_salary,
        bonus_description=version.bonus_description,
        expected_start_date=version.expected_start_date,
        valid_until=version.valid_until,
        notes=version.notes,
        response=(
            CandidateOfferResponse(
                decision=response.decision,
                rejection_reason_code=response.rejection_reason_code,
                rejection_note=response.rejection_note,
                responded_at=response.responded_at,
            )
            if response is not None
            else None
        ),
        onboarding=(
            _candidate_onboarding_view(offer.onboarding)
            if offer.onboarding is not None
            else None
        ),
    )


def _verification_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="候选人验证服务暂时不可用，请稍后重试",
    )


@router.post("/status", response_model=OfferPortalStatusResponse)
def get_offer_portal_status(
    payload: OfferPortalTokenRequest,
    db: DbSession,
) -> OfferPortalStatusResponse:
    link = _get_portal_link(db, payload.token)
    _ensure_link_usable(link)
    return OfferPortalStatusResponse(status="verification_required")


@router.post("/verify", response_model=OfferPortalVerifiedResponse)
def verify_offer_portal(
    payload: OfferPortalVerifyRequest,
    db: DbSession,
    portal_store: PortalStore,
) -> OfferPortalVerifiedResponse:
    link = _get_portal_link(db, payload.token)
    _ensure_link_usable(link)
    try:
        retry_after = portal_store.lock_remaining_seconds(link.id)
    except Exception as error:
        raise _verification_unavailable() from error
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="验证失败次数过多，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )

    submitted_digest = phone_verification_digest(
        payload.phone_last_four,
        link_id=link.id,
        secret_key=settings.app_secret_key,
    )
    verified = hmac.compare_digest(
        link.verification_phone_digest,
        submitted_digest,
    )
    if not verified:
        try:
            failure = portal_store.record_failure(link.id)
        except Exception as error:
            raise _verification_unavailable() from error
        record_audit(
            db,
            action="offer_portal.verification_failed",
            target_type="offer_portal_link",
            target_id=link.id,
            job_id=link.offer.application.job_id,
            result="failure",
            actor_username="candidate_portal",
            details={"locked": failure.locked},
        )
        db.commit()
        if failure.locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="验证失败次数过多，请稍后重试",
                headers={"Retry-After": str(failure.retry_after_seconds)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="验证信息不正确",
        )

    try:
        portal_store.clear_failures(link.id)
        verification_token, verification_expires_at = (
            portal_store.create_verification(link.id)
        )
    except Exception as error:
        raise _verification_unavailable() from error
    record_audit(
        db,
        action="offer_portal.verified",
        target_type="offer_portal_link",
        target_id=link.id,
        job_id=link.offer.application.job_id,
        result="success",
        actor_username="candidate_portal",
    )
    try:
        db.commit()
    except Exception:
        portal_store.delete_verification(verification_token)
        raise
    view = _candidate_offer_view(link)
    return OfferPortalVerifiedResponse(
        **view.model_dump(),
        verification_token=verification_token,
        verification_expires_at=verification_expires_at,
    )


@router.post("/detail", response_model=CandidateOfferView)
def get_verified_offer_portal_detail(
    payload: OfferPortalDetailRequest,
    db: DbSession,
    portal_store: PortalStore,
) -> CandidateOfferView:
    link = _get_portal_link(db, payload.token)
    _ensure_link_usable(link)
    try:
        identity = portal_store.get_verification(payload.verification_token)
    except Exception as error:
        raise _verification_unavailable() from error
    if identity is None or identity.link_id != link.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="候选人验证已失效，请重新验证",
        )
    return _candidate_offer_view(link)


@router.post("/respond", response_model=CandidateOfferView)
def respond_to_offer(
    payload: OfferPortalRespondRequest,
    db: DbSession,
    portal_store: PortalStore,
) -> CandidateOfferView:
    initial_link = _get_portal_link(db, payload.token)
    _ensure_link_usable(initial_link)
    try:
        identity = portal_store.get_verification(payload.verification_token)
    except Exception as error:
        raise _verification_unavailable() from error
    if identity is None or identity.link_id != initial_link.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="候选人验证已失效，请重新验证",
        )

    offer = _get_locked_offer(db, initial_link.offer_id)
    link = next((item for item in offer.portal_links if item.id == initial_link.id), None)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="候选人链接不存在或已失效",
        )
    _ensure_link_usable(link)

    existing = offer.candidate_response
    if existing is not None:
        if _response_matches(existing, payload) and existing.portal_link_id == link.id:
            return _candidate_offer_view(link)
        raise _response_conflict()
    if offer.status != "pending_response" or offer.current_version.id != link.version_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前 Offer 状态不允许候选人回应",
        )

    response = OfferResponse(
        offer_id=offer.id,
        version_id=link.version_id,
        portal_link_id=link.id,
        idempotency_key=payload.idempotency_key,
        decision=payload.decision,
        rejection_reason_code=payload.rejection_reason_code,
        rejection_note=payload.rejection_note,
        verification_completed_at=identity.verified_at,
    )
    db.add(response)
    if payload.decision == "accepted":
        offer.status = "accepted"
        target_stage = "onboarding_pending_confirmation"
        process_reason = "候选人已接受 Offer"
        db.flush()
        create_onboarding_for_acceptance(
            db,
            offer=offer,
            response=response,
            portal_link=link,
        )
    else:
        offer.status = "declined"
        target_stage = "offer_rejected"
        process_reason = "候选人已拒绝 Offer"
    change_candidate_process_stage(
        db,
        offer.application,
        target_stage=target_stage,
        reason=process_reason,
        operator=None,
    )
    try:
        db.flush()
        record_audit(
            db,
            action="offer_portal.responded",
            target_type="offer_response",
            target_id=response.id,
            job_id=offer.application.job_id,
            result="success",
            actor_username="candidate_portal",
            details={
                "offer_id": str(offer.id),
                "portal_link_id": str(link.id),
                "decision": payload.decision,
                "rejection_reason_code": payload.rejection_reason_code,
            },
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        concurrent_link = _get_portal_link(db, payload.token)
        concurrent = concurrent_link.offer.candidate_response
        if (
            concurrent is not None
            and concurrent.portal_link_id == concurrent_link.id
            and _response_matches(concurrent, payload)
        ):
            return _candidate_offer_view(concurrent_link)
        raise _response_conflict() from error

    db.expire_all()
    return _candidate_offer_view(_get_portal_link(db, payload.token))


def _get_verified_onboarding(
    db: Session,
    portal_store: OfferPortalVerificationStore,
    *,
    token: str,
    verification_token: str,
) -> tuple[OfferPortalLink, Onboarding]:
    initial_link = _get_portal_link(db, token)
    _ensure_link_usable(initial_link)
    try:
        identity = portal_store.get_verification(verification_token)
    except Exception as error:
        raise _verification_unavailable() from error
    if identity is None or identity.link_id != initial_link.id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="候选人验证已失效，请重新验证",
        )

    link = db.scalar(
        select(OfferPortalLink)
        .where(OfferPortalLink.id == initial_link.id)
        .with_for_update()
    )
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="候选人链接不存在或已失效",
        )
    _ensure_link_usable(link)
    onboarding = db.scalar(
        select(Onboarding)
        .where(Onboarding.offer_id == initial_link.offer_id)
        .with_for_update()
        .options(
            selectinload(Onboarding.application).selectinload(JobApplication.candidate),
            selectinload(Onboarding.application).selectinload(JobApplication.job),
            selectinload(Onboarding.offer).selectinload(Offer.versions),
            selectinload(Onboarding.offer)
            .selectinload(Offer.portal_links)
            .selectinload(OfferPortalLink.response),
            selectinload(Onboarding.offer).selectinload(Offer.candidate_response),
            selectinload(Onboarding.events),
        )
        .execution_options(populate_existing=True)
    )
    if onboarding is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="入职记录尚未建立，请联系招聘专员",
        )
    return link, onboarding


def _onboarding_service_error(error: Exception) -> HTTPException:
    if isinstance(error, OnboardingValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.post("/onboarding/confirm-date", response_model=CandidateOfferView)
def confirm_onboarding_date(
    payload: PortalOnboardingConfirmDateRequest,
    db: DbSession,
    portal_store: PortalStore,
) -> CandidateOfferView:
    _link, onboarding = _get_verified_onboarding(
        db,
        portal_store,
        token=payload.token,
        verification_token=payload.verification_token,
    )
    replay = find_event_by_key(onboarding, payload.idempotency_key)
    try:
        candidate_confirm_date(
            db,
            onboarding,
            idempotency_key=payload.idempotency_key,
            version=payload.version,
            start_date=payload.start_date,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        raise _onboarding_service_error(error) from error
    if replay is not None:
        return _candidate_offer_view(_get_portal_link(db, payload.token))
    record_audit(
        db,
        action="onboarding.candidate_confirmed_date",
        target_type="onboarding",
        target_id=onboarding.id,
        job_id=onboarding.application.job_id,
        result="success",
        actor_username="candidate_portal",
        details={"status": onboarding.status, "version": onboarding.version},
    )
    db.commit()
    db.expire_all()
    return _candidate_offer_view(_get_portal_link(db, payload.token))


@router.post("/onboarding/propose-date", response_model=CandidateOfferView)
def propose_onboarding_date(
    payload: PortalOnboardingProposeDateRequest,
    db: DbSession,
    portal_store: PortalStore,
) -> CandidateOfferView:
    _link, onboarding = _get_verified_onboarding(
        db,
        portal_store,
        token=payload.token,
        verification_token=payload.verification_token,
    )
    replay = find_event_by_key(onboarding, payload.idempotency_key)
    try:
        candidate_propose_date(
            db,
            onboarding,
            idempotency_key=payload.idempotency_key,
            version=payload.version,
            proposed_date=payload.start_date,
            note=payload.note,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        raise _onboarding_service_error(error) from error
    if replay is not None:
        return _candidate_offer_view(_get_portal_link(db, payload.token))
    record_audit(
        db,
        action="onboarding.candidate_proposed_date",
        target_type="onboarding",
        target_id=onboarding.id,
        job_id=onboarding.application.job_id,
        result="success",
        actor_username="candidate_portal",
        details={"status": onboarding.status, "version": onboarding.version},
    )
    db.commit()
    db.expire_all()
    return _candidate_offer_view(_get_portal_link(db, payload.token))


@router.post("/onboarding/abandon", response_model=CandidateOfferView)
def abandon_portal_onboarding(
    payload: PortalOnboardingAbandonRequest,
    db: DbSession,
    portal_store: PortalStore,
) -> CandidateOfferView:
    _link, onboarding = _get_verified_onboarding(
        db,
        portal_store,
        token=payload.token,
        verification_token=payload.verification_token,
    )
    replay = find_event_by_key(onboarding, payload.idempotency_key)
    try:
        abandon_onboarding(
            db,
            onboarding,
            idempotency_key=payload.idempotency_key,
            version=payload.version,
            source="candidate_withdrew",
            reason_code=payload.reason_code,
            note=payload.note,
            actor_type="candidate",
            actor=None,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        raise _onboarding_service_error(error) from error
    if replay is not None:
        return _candidate_offer_view(_get_portal_link(db, payload.token))
    record_audit(
        db,
        action="onboarding.candidate_abandoned",
        target_type="onboarding",
        target_id=onboarding.id,
        job_id=onboarding.application.job_id,
        result="success",
        actor_username="candidate_portal",
        details={"status": onboarding.status, "version": onboarding.version},
    )
    db.commit()
    db.expire_all()
    return _candidate_offer_view(_get_portal_link(db, payload.token))
