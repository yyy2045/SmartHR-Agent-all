import uuid
from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import exists, false, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import (
    InterviewReport,
    Job,
    JobApplication,
    Offer,
    OfferApproval,
    OfferManagerConfirmation,
    OfferVersion,
    User,
)
from app.schemas.offer import (
    OfferApprovalDecisionRequest,
    OfferCreateRequest,
    OfferManagerDecisionRequest,
    OfferResponse,
    OfferStatus,
    OfferSubmitRequest,
    OfferSummaryResponse,
    OfferVersionCreateRequest,
    OfferVersionResponse,
)
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_OFFER_LOAD_OPTIONS = (
    selectinload(Offer.application).selectinload(JobApplication.candidate),
    selectinload(Offer.application).selectinload(JobApplication.job),
    selectinload(Offer.versions).selectinload(OfferVersion.manager_confirmation),
    selectinload(Offer.versions).selectinload(OfferVersion.approval),
)
_CONTENT_FIELDS = (
    "monthly_salary",
    "annual_salary_months",
    "probation_months",
    "probation_monthly_salary",
    "bonus_description",
    "expected_start_date",
    "valid_until",
    "notes",
)


def _offer_scope_clause(user: User):
    if user.has_role("administrator"):
        return Offer.id.is_not(None)

    clauses = []
    if user.has_role("recruiter"):
        clauses.append(Job.owner_id == user.id)
    if user.has_role("hiring_manager"):
        clauses.append(Job.hiring_manager_id == user.id)
    if user.has_role("approver"):
        has_final_decision = exists(
            select(OfferApproval.id)
            .join(OfferVersion, OfferApproval.version_id == OfferVersion.id)
            .where(OfferVersion.offer_id == Offer.id)
        )
        clauses.append(or_(Offer.status == "pending_approval", has_final_decision))
    return or_(*clauses) if clauses else false()


def _offer_query(user: User):
    return (
        select(Offer)
        .join(JobApplication, Offer.application_id == JobApplication.id)
        .join(Job, JobApplication.job_id == Job.id)
        .where(_offer_scope_clause(user))
        .options(*_OFFER_LOAD_OPTIONS)
        .execution_options(populate_existing=True)
    )


def _get_offer(
    db: Session,
    offer_id: uuid.UUID,
    user: User,
    *,
    for_update: bool = False,
) -> Offer:
    query = _offer_query(user).where(Offer.id == offer_id)
    if for_update:
        query = query.with_for_update()
    offer = db.scalar(query)
    if offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer 不存在")
    return offer


def _reload_offer(db: Session, offer_id: uuid.UUID, user: User) -> Offer:
    db.expire_all()
    return _get_offer(db, offer_id, user)


def _get_writable_application(
    db: Session,
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    user: User,
) -> tuple[Job, JobApplication]:
    job = get_visible_job(db, job_id, user)
    ensure_job_writable(job, user)
    application = db.scalar(
        select(JobApplication)
        .where(
            JobApplication.id == application_id,
            JobApplication.job_id == job.id,
        )
        .options(
            selectinload(JobApplication.candidate),
            selectinload(JobApplication.interview_report).selectinload(
                InterviewReport.versions
            ),
            selectinload(JobApplication.offer).selectinload(Offer.versions),
        )
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="职位应聘记录不存在",
        )
    if job.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="归档职位不能修改 Offer")
    if application.status == "merged":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已合并应聘记录不能修改 Offer",
        )
    return job, application


def _ensure_offer_writable(offer: Offer, user: User) -> None:
    ensure_job_writable(offer.application.job, user)
    if offer.application.job.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="归档职位不能修改 Offer")
    if offer.application.status == "merged":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已合并应聘记录不能修改 Offer",
        )


def _confirmed_hire_report(application: JobApplication) -> InterviewReport:
    report = application.interview_report
    if (
        report is None
        or report.status != "confirmed"
        or report.current_version.conclusion != "hire"
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="只有已确认且结论为录用的面试报告可以创建 Offer",
        )
    return report


def _payload_content(payload: OfferCreateRequest | OfferVersionCreateRequest) -> dict[str, object]:
    return {field: getattr(payload, field) for field in _CONTENT_FIELDS}


def _version_content(version: OfferVersion) -> dict[str, object]:
    return {field: getattr(version, field) for field in _CONTENT_FIELDS}


def _new_version(
    payload: OfferCreateRequest | OfferVersionCreateRequest,
    user: User,
    *,
    version_number: int,
    source_version_id: uuid.UUID | None,
    report_version_id: uuid.UUID,
) -> OfferVersion:
    return OfferVersion(
        version_number=version_number,
        idempotency_key=payload.idempotency_key,
        source_version_id=source_version_id,
        source_interview_report_version_id=report_version_id,
        currency="CNY",
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
        **_payload_content(payload),
    )


def _find_version_by_key(offer: Offer, key: uuid.UUID) -> OfferVersion | None:
    return next((item for item in offer.versions if item.idempotency_key == key), None)


def _ensure_version_replay(
    version: OfferVersion,
    payload: OfferCreateRequest | OfferVersionCreateRequest,
    *,
    source_version_id: uuid.UUID | None,
    report_version_id: uuid.UUID,
) -> None:
    if (
        version.source_version_id != source_version_id
        or version.source_interview_report_version_id != report_version_id
        or _version_content(version) != _payload_content(payload)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="幂等键已用于不同的 Offer 版本或内容",
        )


def _validate_submission_dates(version: OfferVersion) -> None:
    today = datetime.now(_SHANGHAI).date()
    if version.valid_until <= today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Offer 有效期必须晚于提交当天",
        )
    if version.expected_start_date <= version.valid_until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="预计入职日必须晚于 Offer 有效期",
        )


def _version_response(version: OfferVersion) -> OfferVersionResponse:
    return OfferVersionResponse.model_validate(version)


def _offer_response(offer: Offer) -> OfferResponse:
    application = offer.application
    return OfferResponse(
        id=offer.id,
        application_id=application.id,
        application_status=application.status,
        job_id=application.job_id,
        job_title=application.job.title,
        candidate_id=application.candidate_id,
        candidate_code=application.candidate.candidate_code,
        candidate_name=application.candidate.full_name,
        status=offer.status,
        current_version_number=offer.current_version_number,
        current_version=_version_response(offer.current_version),
        versions=[_version_response(version) for version in offer.versions],
        created_by_id=offer.created_by_id,
        created_at=offer.created_at,
        updated_at=offer.updated_at,
    )


def _offer_summary(offer: Offer) -> OfferSummaryResponse:
    application = offer.application
    return OfferSummaryResponse(
        id=offer.id,
        application_id=application.id,
        job_id=application.job_id,
        job_title=application.job.title,
        candidate_id=application.candidate_id,
        candidate_code=application.candidate.candidate_code,
        candidate_name=application.candidate.full_name,
        status=offer.status,
        current_version_number=offer.current_version_number,
        current_version=_version_response(offer.current_version),
        updated_at=offer.updated_at,
    )


def _record_sensitive_read(db: Session, user: User, offer: Offer) -> None:
    record_audit(
        db,
        action="offer.sensitive_data_viewed",
        target_type="offer",
        target_id=offer.id,
        job_id=offer.application.job_id,
        result="success",
        actor=user,
        details={"application_id": str(offer.application_id)},
    )


@router.get("/offers", response_model=list[OfferSummaryResponse])
def list_offers(
    current_user: CurrentUser,
    db: DbSession,
    offer_status: Annotated[OfferStatus | None, Query(alias="status")] = None,
    job_id: uuid.UUID | None = None,
) -> list[OfferSummaryResponse]:
    query = _offer_query(current_user)
    if offer_status is not None:
        query = query.where(Offer.status == offer_status)
    if job_id is not None:
        query = query.where(Job.id == job_id)
    offers = list(db.scalars(query.order_by(Offer.updated_at.desc(), Offer.id)).unique())
    responses = [_offer_summary(offer) for offer in offers]
    for offer in offers:
        _record_sensitive_read(db, current_user, offer)
    db.commit()
    return responses


@router.get("/offers/{offer_id}", response_model=OfferResponse)
def get_offer(offer_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> OfferResponse:
    offer = _get_offer(db, offer_id, current_user)
    response = _offer_response(offer)
    _record_sensitive_read(db, current_user, offer)
    db.commit()
    return response


@router.post(
    "/jobs/{job_id}/applications/{application_id}/offer",
    response_model=OfferResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_offer(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    payload: OfferCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OfferResponse:
    job, application = _get_writable_application(
        db, job_id, application_id, current_user
    )
    report = _confirmed_hire_report(application)
    if application.offer is not None:
        replay = _find_version_by_key(application.offer, payload.idempotency_key)
        if replay is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该应聘记录已经存在 Offer",
            )
        _ensure_version_replay(
            replay,
            payload,
            source_version_id=None,
            report_version_id=report.current_version.id,
        )
        return _offer_response(application.offer)

    offer = Offer(application_id=application.id, created_by_id=current_user.id)
    offer.versions.append(
        _new_version(
            payload,
            current_user,
            version_number=1,
            source_version_id=None,
            report_version_id=report.current_version.id,
        )
    )
    db.add(offer)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(Offer)
            .where(Offer.application_id == application_id)
            .options(*_OFFER_LOAD_OPTIONS)
        )
        if concurrent is None:
            raise
        replay = _find_version_by_key(concurrent, payload.idempotency_key)
        if replay is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该应聘记录已经存在 Offer",
            ) from None
        _ensure_version_replay(
            replay,
            payload,
            source_version_id=None,
            report_version_id=report.current_version.id,
        )
        return _offer_response(concurrent)

    record_audit(
        db,
        action="offer.created",
        target_type="offer",
        target_id=offer.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={"application_id": str(application.id), "version_number": 1},
    )
    db.commit()
    return _offer_response(_reload_offer(db, offer.id, current_user))


@router.post("/offers/{offer_id}/versions", response_model=OfferResponse)
def create_offer_version(
    offer_id: uuid.UUID,
    payload: OfferVersionCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OfferResponse:
    offer = _get_offer(db, offer_id, current_user, for_update=True)
    _ensure_offer_writable(offer, current_user)
    report = _confirmed_hire_report(offer.application)
    replay = _find_version_by_key(offer, payload.idempotency_key)
    if replay is not None:
        _ensure_version_replay(
            replay,
            payload,
            source_version_id=payload.source_version_id,
            report_version_id=report.current_version.id,
        )
        return _offer_response(offer)
    if offer.status not in {"draft", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已提交或已批准的 Offer 不能修改",
        )
    if payload.source_version_id != offer.current_version.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只能基于 Offer 当前版本创建新版本",
        )
    if _version_content(offer.current_version) == _payload_content(payload):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Offer 内容未发生变化",
        )

    version = _new_version(
        payload,
        current_user,
        version_number=offer.current_version_number + 1,
        source_version_id=offer.current_version.id,
        report_version_id=report.current_version.id,
    )
    offer.versions.append(version)
    offer.current_version_number = version.version_number
    offer.status = "draft"
    record_audit(
        db,
        action="offer.version_created",
        target_type="offer",
        target_id=offer.id,
        job_id=offer.application.job_id,
        result="success",
        actor=current_user,
        details={
            "application_id": str(offer.application_id),
            "source_version_id": str(payload.source_version_id),
            "version_number": version.version_number,
        },
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        concurrent = _get_offer(db, offer_id, current_user)
        replay = _find_version_by_key(concurrent, payload.idempotency_key)
        if replay is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Offer 已被其他操作更新，请刷新后重试",
            ) from error
        _ensure_version_replay(
            replay,
            payload,
            source_version_id=payload.source_version_id,
            report_version_id=report.current_version.id,
        )
        return _offer_response(concurrent)
    return _offer_response(_reload_offer(db, offer.id, current_user))


@router.post("/offers/{offer_id}/submit", response_model=OfferResponse)
def submit_offer(
    offer_id: uuid.UUID,
    payload: OfferSubmitRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OfferResponse:
    offer = _get_offer(db, offer_id, current_user, for_update=True)
    _ensure_offer_writable(offer, current_user)
    version = offer.current_version
    if payload.version_id != version.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只能提交 Offer 当前版本",
        )
    if version.submission_idempotency_key is not None:
        if version.submission_idempotency_key == payload.idempotency_key:
            return _offer_response(offer)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Offer 当前版本已经提交",
        )
    if offer.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Offer 当前状态不能提交")
    _validate_submission_dates(version)
    version.submission_idempotency_key = payload.idempotency_key
    version.submitted_at = datetime.now(UTC)
    offer.status = "pending_manager_confirmation"
    record_audit(
        db,
        action="offer.submitted",
        target_type="offer",
        target_id=offer.id,
        job_id=offer.application.job_id,
        result="success",
        actor=current_user,
        details={"version_id": str(version.id), "version_number": version.version_number},
    )
    db.commit()
    return _offer_response(_reload_offer(db, offer.id, current_user))


@router.post("/offers/{offer_id}/manager-decision", response_model=OfferResponse)
def decide_offer_as_manager(
    offer_id: uuid.UUID,
    payload: OfferManagerDecisionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OfferResponse:
    offer = _get_offer(db, offer_id, current_user, for_update=True)
    job = offer.application.job
    if not current_user.has_role("administrator") and job.hiring_manager_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有该职位用人经理可以确认录用",
        )
    version = offer.current_version
    if payload.version_id != version.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只能处理 Offer 当前版本")
    existing = version.manager_confirmation
    if existing is not None:
        if (
            existing.idempotency_key == payload.idempotency_key
            and existing.confirmer_id == current_user.id
            and existing.decision == payload.decision
            and existing.comment == payload.comment
        ):
            return _offer_response(offer)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用人经理已经处理该版本")
    if offer.status != "pending_manager_confirmation":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Offer 当前不等待经理确认")

    version.manager_confirmation = OfferManagerConfirmation(
        idempotency_key=payload.idempotency_key,
        confirmer_id=current_user.id,
        confirmer_username=current_user.username,
        confirmer_display_name=current_user.display_name,
        decision=payload.decision,
        comment=payload.comment,
    )
    offer.status = "pending_approval" if payload.decision == "confirmed" else "rejected"
    record_audit(
        db,
        action=f"offer.manager_{payload.decision}",
        target_type="offer",
        target_id=offer.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={"version_id": str(version.id), "comment": payload.comment},
    )
    db.commit()
    return _offer_response(_reload_offer(db, offer.id, current_user))


@router.post("/offers/{offer_id}/approval-decision", response_model=OfferResponse)
def decide_offer_as_approver(
    offer_id: uuid.UUID,
    payload: OfferApprovalDecisionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> OfferResponse:
    offer = _get_offer(db, offer_id, current_user, for_update=True)
    if not current_user.has_role("administrator", "approver"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色不能审批 Offer",
        )
    version = offer.current_version
    if payload.version_id != version.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只能审批 Offer 当前版本")
    manager_confirmation = version.manager_confirmation
    if manager_confirmation is None or manager_confirmation.decision != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Offer 尚未通过用人经理确认",
        )
    if manager_confirmation.confirmer_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用人经理确认人与最终审批人必须是不同账号",
        )
    existing = version.approval
    if existing is not None:
        if (
            existing.idempotency_key == payload.idempotency_key
            and existing.approver_id == current_user.id
            and existing.decision == payload.decision
            and existing.comment == payload.comment
        ):
            return _offer_response(offer)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该版本已经完成最终审批")
    if offer.status != "pending_approval":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Offer 当前不等待最终审批")
    if payload.decision == "approved":
        _validate_submission_dates(version)

    version.approval = OfferApproval(
        idempotency_key=payload.idempotency_key,
        approver_id=current_user.id,
        approver_username=current_user.username,
        approver_display_name=current_user.display_name,
        decision=payload.decision,
        comment=payload.comment,
    )
    offer.status = "approved" if payload.decision == "approved" else "rejected"
    record_audit(
        db,
        action=f"offer.{payload.decision}",
        target_type="offer",
        target_id=offer.id,
        job_id=offer.application.job_id,
        result="success",
        actor=current_user,
        details={"version_id": str(version.id), "comment": payload.comment},
    )
    db.commit()
    return _offer_response(_reload_offer(db, offer.id, current_user))
