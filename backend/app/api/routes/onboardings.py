import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.config import settings
from app.database import get_db
from app.models import (
    Job,
    JobApplication,
    Offer,
    OfferPortalLink,
    Onboarding,
    OnboardingEvent,
    User,
)
from app.schemas.offer_portal import (
    OfferPortalLinkCreateRequest,
    OfferPortalLinkIssuedResponse,
    OfferPortalLinkRegenerateRequest,
)
from app.schemas.onboarding import (
    OnboardingAbandonRequest,
    OnboardingCorrectionRequest,
    OnboardingDateDecisionRequest,
    OnboardingDetailResponse,
    OnboardingEventResponse,
    OnboardingListResponse,
    OnboardingOnboardRequest,
    OnboardingStatus,
    OnboardingSummaryResponse,
)
from app.services.audit import record_audit
from app.services.offer_portal import (
    create_portal_token,
    hash_portal_token,
    phone_last_four,
    phone_verification_digest,
    portal_link_is_expired,
    revoke_portal_link,
)
from app.services.onboarding import (
    OnboardingConflictError,
    OnboardingValidationError,
    abandon_onboarding,
    correct_onboarded_status,
    find_event_by_key,
    mark_onboarded,
    onboarding_action_owner,
    onboarding_portal_expiry,
    onboarding_reference_date,
    recruiter_date_decision,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

_LOAD_OPTIONS = (
    selectinload(Onboarding.application).selectinload(JobApplication.candidate),
    selectinload(Onboarding.application).selectinload(JobApplication.job),
    selectinload(Onboarding.offer).selectinload(Offer.versions),
    selectinload(Onboarding.offer)
    .selectinload(Offer.portal_links)
    .selectinload(OfferPortalLink.response),
    selectinload(Onboarding.offer).selectinload(Offer.candidate_response),
    selectinload(Onboarding.events),
)


def _scope_clause(user: User):
    if user.has_role("administrator"):
        return Onboarding.id.is_not(None)
    clauses = []
    if user.has_role("recruiter"):
        clauses.append(Job.owner_id == user.id)
    if user.has_role("hiring_manager"):
        clauses.append(Job.hiring_manager_id == user.id)
    return or_(*clauses) if clauses else false()


def _query(user: User):
    return (
        select(Onboarding)
        .join(JobApplication, Onboarding.application_id == JobApplication.id)
        .join(Job, JobApplication.job_id == Job.id)
        .where(_scope_clause(user))
        .options(*_LOAD_OPTIONS)
        .execution_options(populate_existing=True)
    )


def _get_onboarding(
    db: Session,
    onboarding_id: uuid.UUID,
    user: User,
    *,
    for_update: bool = False,
) -> Onboarding:
    query = _query(user).where(Onboarding.id == onboarding_id)
    if for_update:
        query = query.with_for_update()
    onboarding = db.scalar(query)
    if onboarding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="入职记录不存在")
    return onboarding


def _ensure_writable(onboarding: Onboarding, user: User) -> None:
    if user.has_role("administrator") or (
        user.has_role("recruiter") and onboarding.application.job.owner_id == user.id
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="当前角色只能查看该入职记录",
    )


def _event_response(event: OnboardingEvent) -> OnboardingEventResponse:
    return OnboardingEventResponse.model_validate(event, from_attributes=True)


def _summary_response(onboarding: Onboarding, user: User) -> OnboardingSummaryResponse:
    application = onboarding.application
    show_phone = user.has_role("administrator") or (
        user.has_role("recruiter") and application.job.owner_id == user.id
    )
    return OnboardingSummaryResponse(
        id=onboarding.id,
        application_id=application.id,
        offer_id=onboarding.offer_id,
        job_id=application.job_id,
        job_title=application.job.title,
        candidate_id=application.candidate_id,
        candidate_code=application.candidate.candidate_code,
        candidate_name=application.candidate.full_name,
        candidate_phone=application.candidate.phone if show_phone else None,
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
        updated_at=onboarding.updated_at,
    )


def _detail_response(onboarding: Onboarding, user: User) -> OnboardingDetailResponse:
    summary = _summary_response(onboarding, user)
    return OnboardingDetailResponse(
        **summary.model_dump(),
        abandonment_note=onboarding.abandonment_note,
        events=[_event_response(event) for event in onboarding.events],
    )


def _translate_service_error(error: Exception) -> HTTPException:
    if isinstance(error, OnboardingValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def _commit_action(
    db: Session,
    onboarding: Onboarding,
    user: User,
    *,
    action: str,
) -> OnboardingDetailResponse:
    record_audit(
        db,
        action=action,
        target_type="onboarding",
        target_id=onboarding.id,
        job_id=onboarding.application.job_id,
        result="success",
        actor=user,
        details={"status": onboarding.status, "version": onboarding.version},
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="入职状态已被其他操作更新，请刷新后重试",
        ) from error
    return _detail_response(_get_onboarding(db, onboarding.id, user), user)


@router.get("/onboardings", response_model=OnboardingListResponse)
def list_onboardings(
    current_user: CurrentUser,
    db: DbSession,
    onboarding_status: Annotated[OnboardingStatus | None, Query(alias="status")] = None,
    job_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OnboardingListResponse:
    filters = []
    if onboarding_status is not None:
        filters.append(Onboarding.status == onboarding_status)
    if job_id is not None:
        filters.append(JobApplication.job_id == job_id)
    base = _query(current_user).where(*filters)
    total = db.scalar(
        select(func.count())
        .select_from(Onboarding)
        .join(JobApplication, Onboarding.application_id == JobApplication.id)
        .join(Job, JobApplication.job_id == Job.id)
        .where(_scope_clause(current_user), *filters)
    )
    items = list(
        db.scalars(
            base.order_by(Onboarding.updated_at.desc(), Onboarding.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return OnboardingListResponse(
        items=[_summary_response(item, current_user) for item in items],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/onboardings/{onboarding_id}", response_model=OnboardingDetailResponse)
def get_onboarding_detail(
    onboarding_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> OnboardingDetailResponse:
    return _detail_response(_get_onboarding(db, onboarding_id, current_user), current_user)


@router.post(
    "/onboardings/{onboarding_id}/date-decision",
    response_model=OnboardingDetailResponse,
)
def decide_onboarding_date(
    onboarding_id: uuid.UUID,
    payload: OnboardingDateDecisionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OnboardingDetailResponse:
    onboarding = _get_onboarding(db, onboarding_id, current_user, for_update=True)
    _ensure_writable(onboarding, current_user)
    replay = find_event_by_key(onboarding, payload.idempotency_key)
    try:
        recruiter_date_decision(
            db,
            onboarding,
            idempotency_key=payload.idempotency_key,
            version=payload.version,
            decision=payload.decision,
            proposed_date=payload.proposed_date,
            note=payload.note,
            actor=current_user,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        raise _translate_service_error(error) from error
    if replay is not None:
        return _detail_response(onboarding, current_user)
    return _commit_action(
        db,
        onboarding,
        current_user,
        action=f"onboarding.date_{payload.decision}",
    )


@router.post("/onboardings/{onboarding_id}/onboard", response_model=OnboardingDetailResponse)
def onboard_candidate(
    onboarding_id: uuid.UUID,
    payload: OnboardingOnboardRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OnboardingDetailResponse:
    onboarding = _get_onboarding(db, onboarding_id, current_user, for_update=True)
    _ensure_writable(onboarding, current_user)
    replay = find_event_by_key(onboarding, payload.idempotency_key)
    try:
        mark_onboarded(
            db,
            onboarding,
            idempotency_key=payload.idempotency_key,
            version=payload.version,
            actual_start_date=payload.actual_start_date,
            note=payload.note,
            actor=current_user,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        raise _translate_service_error(error) from error
    if replay is not None:
        return _detail_response(onboarding, current_user)
    return _commit_action(
        db,
        onboarding,
        current_user,
        action="onboarding.onboarded",
    )


@router.post("/onboardings/{onboarding_id}/abandon", response_model=OnboardingDetailResponse)
def abandon_candidate_onboarding(
    onboarding_id: uuid.UUID,
    payload: OnboardingAbandonRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OnboardingDetailResponse:
    onboarding = _get_onboarding(db, onboarding_id, current_user, for_update=True)
    _ensure_writable(onboarding, current_user)
    replay = find_event_by_key(onboarding, payload.idempotency_key)
    try:
        abandon_onboarding(
            db,
            onboarding,
            idempotency_key=payload.idempotency_key,
            version=payload.version,
            source=payload.source,
            reason_code=payload.reason_code,
            note=payload.note,
            actor_type=(
                "admin" if current_user.has_role("administrator") else "recruiter"
            ),
            actor=current_user,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        raise _translate_service_error(error) from error
    if replay is not None:
        return _detail_response(onboarding, current_user)
    return _commit_action(
        db,
        onboarding,
        current_user,
        action="onboarding.abandoned",
    )


@router.post(
    "/onboardings/{onboarding_id}/corrections",
    response_model=OnboardingDetailResponse,
)
def correct_onboarding(
    onboarding_id: uuid.UUID,
    payload: OnboardingCorrectionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OnboardingDetailResponse:
    onboarding = _get_onboarding(db, onboarding_id, current_user, for_update=True)
    if not current_user.has_role("administrator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有企业管理员可以更正已入职状态",
        )
    replay = find_event_by_key(onboarding, payload.idempotency_key)
    try:
        correct_onboarded_status(
            db,
            onboarding,
            idempotency_key=payload.idempotency_key,
            version=payload.version,
            reason=payload.reason,
            actor=current_user,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        raise _translate_service_error(error) from error
    if replay is not None:
        return _detail_response(onboarding, current_user)
    return _commit_action(
        db,
        onboarding,
        current_user,
        action="onboarding.onboarded_corrected",
    )


def _verification_digest(onboarding: Onboarding, link_id: uuid.UUID) -> str:
    last_four = phone_last_four(onboarding.application.candidate.phone)
    if last_four is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="候选人缺少可用于验证的手机号",
        )
    return phone_verification_digest(
        last_four,
        link_id=link_id,
        secret_key=settings.app_secret_key,
    )


def _active_link(onboarding: Onboarding) -> OfferPortalLink | None:
    return next(
        (
            link
            for link in reversed(onboarding.offer.portal_links)
            if link.revoked_at is None
        ),
        None,
    )


def _issued_link(
    link: OfferPortalLink,
    *,
    portal_token: str | None,
) -> OfferPortalLinkIssuedResponse:
    if link.revoked_at is not None:
        state = "revoked"
    elif portal_link_is_expired(link.expires_at):
        state = "expired"
    elif link.offer.candidate_response is not None:
        state = "responded"
    else:
        state = "active"
    return OfferPortalLinkIssuedResponse(
        id=link.id,
        version_id=link.version_id,
        state=state,
        expires_at=link.expires_at,
        created_by_username=link.created_by_username,
        created_by_display_name=link.created_by_display_name,
        created_at=link.created_at,
        revoked_at=link.revoked_at,
        revoked_by_username=link.revoked_by_username,
        revoked_by_display_name=link.revoked_by_display_name,
        revocation_reason=link.revocation_reason,
        portal_token=portal_token,
    )


def _create_access_link(
    db: Session,
    onboarding: Onboarding,
    user: User,
    *,
    idempotency_key: uuid.UUID,
) -> tuple[OfferPortalLink, str]:
    token = create_portal_token()
    link_id = uuid.uuid4()
    link = OfferPortalLink(
        id=link_id,
        offer_id=onboarding.offer_id,
        version_id=onboarding.offer.current_version.id,
        idempotency_key=idempotency_key,
        token_hash=hash_portal_token(token),
        verification_phone_digest=_verification_digest(onboarding, link_id),
        expires_at=onboarding_portal_expiry(onboarding_reference_date(onboarding)),
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
    )
    db.add(link)
    return link, token


@router.post(
    "/onboardings/{onboarding_id}/portal-links",
    response_model=OfferPortalLinkIssuedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_onboarding_access_link(
    onboarding_id: uuid.UUID,
    payload: OfferPortalLinkCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OfferPortalLinkIssuedResponse:
    onboarding = _get_onboarding(db, onboarding_id, current_user, for_update=True)
    _ensure_writable(onboarding, current_user)
    replay = next(
        (
            link
            for link in onboarding.offer.portal_links
            if link.idempotency_key == payload.idempotency_key
        ),
        None,
    )
    if replay is not None:
        return _issued_link(replay, portal_token=None)
    if _active_link(onboarding) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前已有有效候选人访问链接",
        )
    link, token = _create_access_link(
        db,
        onboarding,
        current_user,
        idempotency_key=payload.idempotency_key,
    )
    record_audit(
        db,
        action="onboarding.portal_link_created",
        target_type="offer_portal_link",
        target_id=link.id,
        job_id=onboarding.application.job_id,
        result="success",
        actor=current_user,
        details={"onboarding_id": str(onboarding.id)},
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="候选人访问链接已被其他操作更新",
        ) from error
    return _issued_link(link, portal_token=token)


@router.post(
    "/onboardings/{onboarding_id}/portal-links/regenerate",
    response_model=OfferPortalLinkIssuedResponse,
    status_code=status.HTTP_201_CREATED,
)
def regenerate_onboarding_access_link(
    onboarding_id: uuid.UUID,
    payload: OfferPortalLinkRegenerateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OfferPortalLinkIssuedResponse:
    onboarding = _get_onboarding(db, onboarding_id, current_user, for_update=True)
    _ensure_writable(onboarding, current_user)
    replay = next(
        (
            link
            for link in onboarding.offer.portal_links
            if link.idempotency_key == payload.idempotency_key
        ),
        None,
    )
    if replay is not None:
        revoked = next(
            (
                link
                for link in onboarding.offer.portal_links
                if link.revocation_idempotency_key
                == payload.revocation_idempotency_key
            ),
            None,
        )
        if revoked is None or revoked.revocation_reason != payload.reason:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="幂等键已用于不同的链接重新生成操作",
            )
        return _issued_link(replay, portal_token=None)
    active = _active_link(onboarding)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前没有可重新生成的候选人访问链接",
        )
    if any(
        link.revocation_idempotency_key == payload.revocation_idempotency_key
        for link in onboarding.offer.portal_links
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="撤回幂等键已用于其他链接",
        )
    revoke_portal_link(
        active,
        idempotency_key=payload.revocation_idempotency_key,
        reason=payload.reason,
        user=current_user,
    )
    link, token = _create_access_link(
        db,
        onboarding,
        current_user,
        idempotency_key=payload.idempotency_key,
    )
    record_audit(
        db,
        action="onboarding.portal_link_regenerated",
        target_type="offer_portal_link",
        target_id=link.id,
        job_id=onboarding.application.job_id,
        result="success",
        actor=current_user,
        details={
            "onboarding_id": str(onboarding.id),
            "revoked_link_id": str(active.id) if active is not None else None,
        },
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="候选人访问链接已被其他操作更新",
        ) from error
    return _issued_link(link, portal_token=token)
