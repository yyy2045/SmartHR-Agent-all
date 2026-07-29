import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import Candidate, TalentPoolGroup, TalentPoolMembership, User
from app.schemas.talent_pool import (
    TalentPoolGroupArchiveRequest,
    TalentPoolGroupCreateRequest,
    TalentPoolGroupListResponse,
    TalentPoolGroupResponse,
    TalentPoolGroupUpdateRequest,
    TalentPoolMembershipAddRequest,
    TalentPoolMembershipListResponse,
    TalentPoolMembershipOperationItemResponse,
    TalentPoolMembershipOperationResponse,
    TalentPoolMembershipRemoveRequest,
    TalentPoolMembershipResponse,
)
from app.services.talent_pool import (
    MembershipOperationOutcome,
    TalentPoolServiceError,
    add_memberships,
    archive_group,
    create_group,
    remove_memberships,
    update_group,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _ensure_read_access(user: User) -> None:
    if not user.has_role("administrator", "recruiter", "hiring_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有人才库访问权限",
        )


def _ensure_write_access(user: User) -> None:
    if not user.has_role("administrator", "recruiter"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有人才库维护权限",
        )


def _raise_service_error(error: TalentPoolServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _active_member_count(db: Session, group_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count(TalentPoolMembership.id))
            .join(Candidate, Candidate.id == TalentPoolMembership.candidate_id)
            .where(
                TalentPoolMembership.group_id == group_id,
                TalentPoolMembership.status == "active",
                Candidate.status == "active",
            )
        )
        or 0
    )


def _group_response(
    db: Session,
    group: TalentPoolGroup,
    *,
    member_count: int | None = None,
) -> TalentPoolGroupResponse:
    created_by = db.get(User, group.created_by_id) if group.created_by_id else None
    archived_by = db.get(User, group.archived_by_id) if group.archived_by_id else None
    return TalentPoolGroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        version=group.version,
        is_archived=group.is_archived,
        member_count=(
            member_count if member_count is not None else _active_member_count(db, group.id)
        ),
        created_by_id=group.created_by_id,
        created_by_display_name=created_by.display_name if created_by else None,
        archived_at=group.archived_at,
        archived_by_id=group.archived_by_id,
        archived_by_display_name=archived_by.display_name if archived_by else None,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _operation_response(
    outcome: MembershipOperationOutcome,
) -> TalentPoolMembershipOperationResponse:
    return TalentPoolMembershipOperationResponse(
        group_id=outcome.group.id,
        group_version=outcome.group_version,
        items=[
            TalentPoolMembershipOperationItemResponse(
                requested_candidate_id=item.requested_candidate_id,
                candidate_id=item.candidate_id,
                membership_id=item.membership_id,
                status=item.status,  # type: ignore[arg-type]
            )
            for item in outcome.items
        ],
    )


@router.get("/groups", response_model=TalentPoolGroupListResponse)
def list_talent_pool_groups(
    current_user: CurrentUser,
    db: DbSession,
    group_status: Annotated[
        Literal["active", "archived", "all"],
        Query(alias="status"),
    ] = "active",
    query: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TalentPoolGroupListResponse:
    _ensure_read_access(current_user)
    filters = []
    if group_status == "active":
        filters.append(TalentPoolGroup.archived_at.is_(None))
    elif group_status == "archived":
        filters.append(TalentPoolGroup.archived_at.is_not(None))
    normalized_query = query.strip() if query else ""
    if normalized_query:
        filters.append(TalentPoolGroup.name.ilike(f"%{normalized_query}%"))

    active_member_count = (
        select(func.count(TalentPoolMembership.id))
        .join(Candidate, Candidate.id == TalentPoolMembership.candidate_id)
        .where(
            TalentPoolMembership.group_id == TalentPoolGroup.id,
            TalentPoolMembership.status == "active",
            Candidate.status == "active",
        )
        .correlate(TalentPoolGroup)
        .scalar_subquery()
    )
    total = db.scalar(select(func.count(TalentPoolGroup.id)).where(*filters)) or 0
    rows = db.execute(
        select(TalentPoolGroup, active_member_count.label("member_count"))
        .where(*filters)
        .order_by(
            TalentPoolGroup.archived_at.is_not(None),
            func.lower(TalentPoolGroup.name),
            TalentPoolGroup.id,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return TalentPoolGroupListResponse(
        items=[
            _group_response(db, group, member_count=member_count)
            for group, member_count in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/groups",
    response_model=TalentPoolGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_talent_pool_group(
    payload: TalentPoolGroupCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentPoolGroupResponse:
    _ensure_write_access(current_user)
    try:
        group = create_group(
            db,
            name=payload.name,
            description=payload.description,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except TalentPoolServiceError as error:
        db.rollback()
        _raise_service_error(error)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="活跃人才分组名称已存在",
        ) from error
    return _group_response(db, group)


@router.patch("/groups/{group_id:uuid}", response_model=TalentPoolGroupResponse)
def update_talent_pool_group(
    group_id: uuid.UUID,
    payload: TalentPoolGroupUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentPoolGroupResponse:
    _ensure_write_access(current_user)
    try:
        group = update_group(
            db,
            group_id=group_id,
            name_is_set="name" in payload.model_fields_set,
            name=payload.name,
            description_is_set="description" in payload.model_fields_set,
            description=payload.description,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except TalentPoolServiceError as error:
        db.rollback()
        _raise_service_error(error)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="活跃人才分组名称已存在",
        ) from error
    return _group_response(db, group)


@router.post(
    "/groups/{group_id:uuid}/archive",
    response_model=TalentPoolGroupResponse,
)
def archive_talent_pool_group(
    group_id: uuid.UUID,
    payload: TalentPoolGroupArchiveRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentPoolGroupResponse:
    _ensure_write_access(current_user)
    try:
        group = archive_group(
            db,
            group_id=group_id,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            reason=payload.reason,
            actor=current_user,
        )
        db.commit()
    except TalentPoolServiceError as error:
        db.rollback()
        _raise_service_error(error)
    return _group_response(db, group)


@router.get("/memberships", response_model=TalentPoolMembershipListResponse)
def list_talent_pool_memberships(
    current_user: CurrentUser,
    db: DbSession,
    membership_status: Annotated[
        Literal["active", "removed", "all"],
        Query(alias="status"),
    ] = "active",
    group_status: Literal["active", "archived", "all"] = "active",
    group_id: uuid.UUID | None = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TalentPoolMembershipListResponse:
    _ensure_read_access(current_user)
    if group_id is not None and db.get(TalentPoolGroup, group_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="人才分组不存在")

    filters = []
    if membership_status != "all":
        filters.append(TalentPoolMembership.status == membership_status)
    if membership_status == "active":
        filters.append(Candidate.status == "active")
    if group_status == "active":
        filters.append(TalentPoolGroup.archived_at.is_(None))
    elif group_status == "archived":
        filters.append(TalentPoolGroup.archived_at.is_not(None))
    if group_id is not None:
        filters.append(TalentPoolMembership.group_id == group_id)
    normalized_query = query.strip() if query else ""
    if normalized_query:
        search_clauses = [Candidate.full_name.ilike(f"%{normalized_query}%")]
        candidate_code = normalized_query.upper().removeprefix("CAND-").replace("-", "")
        if candidate_code and len(candidate_code) <= 32 and all(
            character in "0123456789ABCDEF" for character in candidate_code
        ):
            search_clauses.append(
                func.replace(cast(Candidate.id, String), "-", "").ilike(
                    f"{candidate_code.lower()}%"
                )
            )
        if current_user.has_role("administrator", "recruiter"):
            search_clauses.extend(
                [
                    Candidate.phone.ilike(f"%{normalized_query}%"),
                    Candidate.email.ilike(f"%{normalized_query}%"),
                ]
            )
        filters.append(or_(*search_clauses))

    statement = (
        select(TalentPoolMembership)
        .join(Candidate, Candidate.id == TalentPoolMembership.candidate_id)
        .join(TalentPoolGroup, TalentPoolGroup.id == TalentPoolMembership.group_id)
        .where(*filters)
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    memberships = db.scalars(
        statement.options(
            selectinload(TalentPoolMembership.candidate),
            selectinload(TalentPoolMembership.group),
        )
        .order_by(TalentPoolMembership.updated_at.desc(), TalentPoolMembership.id)
        .offset(offset)
        .limit(limit)
    ).all()
    can_view_contacts = current_user.has_role("administrator", "recruiter")
    return TalentPoolMembershipListResponse(
        items=[
            TalentPoolMembershipResponse(
                id=membership.id,
                group_id=membership.group_id,
                group_name=membership.group.name,
                group_archived=membership.group.is_archived,
                candidate_id=membership.candidate_id,
                candidate_code=membership.candidate.candidate_code,
                candidate_name=membership.candidate.full_name,
                phone=membership.candidate.phone if can_view_contacts else None,
                email=membership.candidate.email if can_view_contacts else None,
                status=membership.status,  # type: ignore[arg-type]
                reason=membership.reason,
                source_application_id=membership.source_application_id,
                version=membership.version,
                joined_at=membership.joined_at,
                removed_at=membership.removed_at,
                updated_at=membership.updated_at,
            )
            for membership in memberships
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/groups/{group_id:uuid}/memberships",
    response_model=TalentPoolMembershipOperationResponse,
)
def add_talent_pool_memberships(
    group_id: uuid.UUID,
    payload: TalentPoolMembershipAddRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentPoolMembershipOperationResponse:
    _ensure_write_access(current_user)
    try:
        outcome = add_memberships(
            db,
            group_id=group_id,
            members=payload.members,
            reason=payload.reason,
            expected_group_version=payload.expected_group_version,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except TalentPoolServiceError as error:
        db.rollback()
        _raise_service_error(error)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="人才组成员关系已被并发修改，请刷新后重试",
        ) from error
    return _operation_response(outcome)


@router.post(
    "/groups/{group_id:uuid}/memberships/remove",
    response_model=TalentPoolMembershipOperationResponse,
)
def remove_talent_pool_memberships(
    group_id: uuid.UUID,
    payload: TalentPoolMembershipRemoveRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentPoolMembershipOperationResponse:
    _ensure_write_access(current_user)
    try:
        outcome = remove_memberships(
            db,
            group_id=group_id,
            candidate_ids=payload.candidate_ids,
            reason=payload.reason,
            expected_group_version=payload.expected_group_version,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except TalentPoolServiceError as error:
        db.rollback()
        _raise_service_error(error)
    return _operation_response(outcome)
