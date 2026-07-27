import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import false, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import (
    RecruitmentRequest,
    RecruitmentRequestApproval,
    RecruitmentRequestVersion,
    Role,
    User,
    UserRole,
)
from app.schemas.recruitment_request import (
    RecruitmentRequestContent,
    RecruitmentRequestCreate,
    RecruitmentRequestDecision,
    RecruitmentRequestResponse,
    RecruitmentRequestStatus,
    RecruitmentRequestSubmit,
    RecruitmentRequestVersionCreate,
)
from app.services.audit import record_audit

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

_LOAD_OPTIONS = (
    selectinload(RecruitmentRequest.requester),
    selectinload(RecruitmentRequest.recruiter),
    selectinload(RecruitmentRequest.created_by),
    selectinload(RecruitmentRequest.versions),
    selectinload(RecruitmentRequest.approvals),
)
_CONTENT_FIELDS = (
    "job_title",
    "headcount",
    "reason",
    "priority",
    "target_start_date",
    "salary_min",
    "salary_max",
    "notes",
)


def _request_scope_clause(user: User):
    if user.has_role("administrator"):
        return RecruitmentRequest.id.is_not(None)

    clauses = []
    if user.has_role("hiring_manager"):
        clauses.append(RecruitmentRequest.requester_id == user.id)
    if user.has_role("recruiter"):
        clauses.append(RecruitmentRequest.recruiter_id == user.id)
    if user.has_role("approver"):
        clauses.append(
            RecruitmentRequest.status.in_(("pending_approval", "approved", "rejected", "converted"))
        )
    return or_(*clauses) if clauses else false()


def _get_request(
    db: Session,
    request_id: uuid.UUID,
    user: User,
    *,
    for_update: bool = False,
) -> RecruitmentRequest:
    query = (
        select(RecruitmentRequest)
        .where(
            RecruitmentRequest.id == request_id,
            _request_scope_clause(user),
        )
        .options(*_LOAD_OPTIONS)
    )
    if for_update:
        query = query.with_for_update()
    request = db.scalar(query)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="招聘需求不存在")
    return request


def _reload_request(db: Session, request_id: uuid.UUID, user: User) -> RecruitmentRequest:
    db.expire_all()
    return _get_request(db, request_id, user)


def _get_active_user_with_role(
    db: Session,
    user_id: uuid.UUID,
    role_key: str,
    *,
    detail: str,
) -> User:
    user = db.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.id == user_id, User.is_active.is_(True), Role.key == role_key)
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
    return user


def _resolve_requester(
    db: Session,
    current_user: User,
    requester_id: uuid.UUID | None,
) -> User:
    selected_id = requester_id
    if selected_id is None and current_user.has_role("hiring_manager"):
        selected_id = current_user.id
    if selected_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="管理员创建招聘需求时必须指定用人经理",
        )
    if not current_user.has_role("administrator"):
        if not current_user.has_role("hiring_manager"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="当前角色不能创建招聘需求",
            )
        if selected_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用人经理只能为本人创建招聘需求",
            )
    return _get_active_user_with_role(
        db,
        selected_id,
        "hiring_manager",
        detail="用人经理不存在、已停用或角色不匹配",
    )


def _ensure_request_writable(request: RecruitmentRequest, user: User) -> None:
    if user.has_role("administrator"):
        return
    if user.has_role("hiring_manager") and request.requester_id == user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="当前角色只能查看该招聘需求",
    )


def _ensure_can_approve(user: User) -> None:
    if user.has_role("administrator", "approver"):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="当前角色不能审批招聘需求",
    )


def _version_content(version: RecruitmentRequestVersion) -> dict[str, object]:
    return {field: getattr(version, field) for field in _CONTENT_FIELDS}


def _payload_content(payload: RecruitmentRequestContent) -> dict[str, object]:
    values = payload.model_dump()
    return {field: values[field] for field in _CONTENT_FIELDS}


def _new_version(
    payload: RecruitmentRequestContent,
    user: User,
    *,
    version_number: int,
    source_version_id: uuid.UUID | None,
) -> RecruitmentRequestVersion:
    return RecruitmentRequestVersion(
        version_number=version_number,
        source_version_id=source_version_id,
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
        **_payload_content(payload),
    )


def _find_idempotent_request(
    db: Session,
    user: User,
    idempotency_key: uuid.UUID,
) -> RecruitmentRequest | None:
    return db.scalar(
        select(RecruitmentRequest)
        .where(
            RecruitmentRequest.created_by_id == user.id,
            RecruitmentRequest.idempotency_key == idempotency_key,
        )
        .options(*_LOAD_OPTIONS)
    )


def _ensure_same_create_payload(
    request: RecruitmentRequest,
    payload: RecruitmentRequestCreate,
    requester_id: uuid.UUID,
) -> None:
    if (
        request.requester_id != requester_id
        or request.recruiter_id != payload.recruiter_id
        or _version_content(request.current_version) != _payload_content(payload)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="幂等键已用于不同的招聘需求内容",
        )


@router.get("", response_model=list[RecruitmentRequestResponse])
def list_recruitment_requests(
    current_user: CurrentUser,
    db: DbSession,
    request_status: Annotated[RecruitmentRequestStatus | None, Query(alias="status")] = None,
) -> list[RecruitmentRequest]:
    query = (
        select(RecruitmentRequest)
        .where(_request_scope_clause(current_user))
        .options(*_LOAD_OPTIONS)
    )
    if request_status is not None:
        query = query.where(RecruitmentRequest.status == request_status)
    return list(
        db.scalars(
            query.order_by(
                RecruitmentRequest.updated_at.desc(),
                RecruitmentRequest.created_at.desc(),
            )
        )
    )


@router.post(
    "",
    response_model=RecruitmentRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_recruitment_request(
    payload: RecruitmentRequestCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentRequest:
    if not current_user.has_role("administrator", "hiring_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色不能创建招聘需求",
        )
    requester = _resolve_requester(db, current_user, payload.requester_id)
    _get_active_user_with_role(
        db,
        payload.recruiter_id,
        "recruiter",
        detail="招聘专员不存在、已停用或角色不匹配",
    )

    existing = _find_idempotent_request(db, current_user, payload.idempotency_key)
    if existing is not None:
        _ensure_same_create_payload(existing, payload, requester.id)
        return existing

    request = RecruitmentRequest(
        idempotency_key=payload.idempotency_key,
        requester_id=requester.id,
        recruiter_id=payload.recruiter_id,
        created_by_id=current_user.id,
    )
    request.versions.append(
        _new_version(
            payload,
            current_user,
            version_number=1,
            source_version_id=None,
        )
    )
    db.add(request)
    db.flush()
    record_audit(
        db,
        action="recruitment_request.created",
        target_type="recruitment_request",
        target_id=request.id,
        result="success",
        actor=current_user,
        details={
            "requester_id": str(request.requester_id),
            "recruiter_id": str(request.recruiter_id),
            "version_number": 1,
        },
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_idempotent_request(db, current_user, payload.idempotency_key)
        if existing is None:
            raise
        _ensure_same_create_payload(existing, payload, requester.id)
        return existing
    return _reload_request(db, request.id, current_user)


@router.get("/{request_id}", response_model=RecruitmentRequestResponse)
def get_recruitment_request(
    request_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentRequest:
    return _get_request(db, request_id, current_user)


@router.post(
    "/{request_id}/versions",
    response_model=RecruitmentRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_recruitment_request_version(
    request_id: uuid.UUID,
    payload: RecruitmentRequestVersionCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentRequest:
    request = _get_request(db, request_id, current_user, for_update=True)
    _ensure_request_writable(request, current_user)
    if request.status not in {"draft", "rejected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前状态不能修改招聘需求",
        )
    source = request.current_version
    if payload.source_version_id != source.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="招聘需求已产生新版本，请刷新后重试",
        )
    if _version_content(source) == _payload_content(payload):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="招聘需求内容未发生变化",
        )

    version_number = request.current_version_number + 1
    request.versions.append(
        _new_version(
            payload,
            current_user,
            version_number=version_number,
            source_version_id=source.id,
        )
    )
    request.current_version_number = version_number
    request.status = "draft"
    record_audit(
        db,
        action="recruitment_request.version_created",
        target_type="recruitment_request",
        target_id=request.id,
        result="success",
        actor=current_user,
        details={
            "source_version_id": str(source.id),
            "version_number": version_number,
        },
    )
    db.commit()
    return _reload_request(db, request.id, current_user)


@router.post("/{request_id}/submit", response_model=RecruitmentRequestResponse)
def submit_recruitment_request(
    request_id: uuid.UUID,
    payload: RecruitmentRequestSubmit,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentRequest:
    request = _get_request(db, request_id, current_user, for_update=True)
    _ensure_request_writable(request, current_user)
    current_version = request.current_version
    if request.status == "pending_approval":
        if payload.version_id == current_version.id:
            return request
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="招聘需求已提交其他版本",
        )
    if request.status == "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="被驳回的需求必须修改生成新版本后再提交",
        )
    if request.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前状态不能提交审批",
        )
    if payload.version_id != current_version.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="招聘需求已产生新版本，请刷新后重试",
        )

    request.status = "pending_approval"
    record_audit(
        db,
        action="recruitment_request.submitted",
        target_type="recruitment_request",
        target_id=request.id,
        result="success",
        actor=current_user,
        details={
            "version_id": str(current_version.id),
            "version_number": current_version.version_number,
        },
    )
    db.commit()
    return _reload_request(db, request.id, current_user)


@router.post("/{request_id}/decision", response_model=RecruitmentRequestResponse)
def decide_recruitment_request(
    request_id: uuid.UUID,
    payload: RecruitmentRequestDecision,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentRequest:
    request = _get_request(db, request_id, current_user, for_update=True)
    _ensure_can_approve(current_user)
    current_version = request.current_version
    existing = next(
        (approval for approval in request.approvals if approval.version_id == payload.version_id),
        None,
    )
    if existing is not None:
        if existing.decision == payload.decision:
            return request
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该版本已经完成审批，不能修改审批结论",
        )
    if request.status != "pending_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前状态不在审批中",
        )
    if payload.version_id != current_version.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只能审批当前提交版本",
        )

    approval = RecruitmentRequestApproval(
        request_id=request.id,
        version_id=current_version.id,
        approver_id=current_user.id,
        approver_username=current_user.username,
        approver_display_name=current_user.display_name,
        decision=payload.decision,
        comment=payload.comment,
    )
    request.approvals.append(approval)
    request.status = payload.decision
    record_audit(
        db,
        action=f"recruitment_request.{payload.decision}",
        target_type="recruitment_request",
        target_id=request.id,
        result="success",
        actor=current_user,
        details={
            "version_id": str(current_version.id),
            "version_number": current_version.version_number,
            "comment": payload.comment,
        },
    )
    db.commit()
    return _reload_request(db, request.id, current_user)
