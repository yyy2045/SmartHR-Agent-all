import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import JobApplication, Offer, OfferPortalLink
from app.redis_client import get_offer_portal_store
from app.schemas.offer_portal import (
    CandidateOfferResponse,
    CandidateOfferView,
    OfferPortalDetailRequest,
    OfferPortalStatusResponse,
    OfferPortalTokenRequest,
    OfferPortalVerifiedResponse,
    OfferPortalVerifyRequest,
)
from app.services.audit import record_audit
from app.services.offer_portal import (
    OfferPortalVerificationStore,
    hash_portal_token,
    phone_last_four,
    portal_link_is_expired,
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


def _candidate_offer_view(link: OfferPortalLink) -> CandidateOfferView:
    offer = link.offer
    version = link.version
    response = link.response
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

    expected = phone_last_four(link.offer.application.candidate.phone)
    verified = expected is not None and hmac.compare_digest(
        expected, payload.phone_last_four
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
