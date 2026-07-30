import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import MessageTemplate, MessageTemplateVersion, User
from app.schemas.message import (
    MessageTemplateAction,
    MessageTemplateCreateRequest,
    MessageTemplateListResponse,
    MessageTemplateResponse,
    MessageTemplateStatusRequest,
    MessageTemplateSummaryResponse,
    MessageTemplateType,
    MessageTemplateVersionCreateRequest,
    MessageTemplateVersionResponse,
)
from app.services.message_templates import (
    MessageTemplateServiceError,
    create_template,
    create_template_version,
    get_template,
    set_template_status,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _ensure_read_access(user: User) -> None:
    if not user.has_role("administrator", "recruiter", "hiring_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有沟通模板访问权限",
        )


def _ensure_write_access(user: User) -> None:
    if not user.has_role("administrator", "recruiter"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有沟通模板维护权限",
        )


def _raise_service_error(error: MessageTemplateServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _allowed_actions(template: MessageTemplate, user: User) -> list[MessageTemplateAction]:
    if not user.has_role("administrator", "recruiter"):
        return []
    actions: list[MessageTemplateAction] = ["create_version"]
    actions.append("deactivate" if template.status == "active" else "activate")
    return actions


def _version_response(version: MessageTemplateVersion) -> MessageTemplateVersionResponse:
    return MessageTemplateVersionResponse(
        id=version.id,
        version_number=version.version_number,
        source_version_id=version.source_version_id,
        subject=version.subject,
        body=version.body,
        variables=version.variables,
        created_by_id=version.created_by_id,
        created_by_username=version.created_by_username,
        created_by_display_name=version.created_by_display_name,
        created_at=version.created_at,
    )


def _summary_response(
    template: MessageTemplate,
    user: User,
) -> MessageTemplateSummaryResponse:
    return MessageTemplateSummaryResponse(
        id=template.id,
        system_key=template.system_key,
        template_type=template.template_type,  # type: ignore[arg-type]
        name=template.name,
        status=template.status,  # type: ignore[arg-type]
        current_version_number=template.current_version_number,
        resource_version=template.resource_version,
        current_subject=template.current_version.subject,
        updated_at=template.updated_at,
        allowed_actions=_allowed_actions(template, user),
    )


def _detail_response(template: MessageTemplate, user: User) -> MessageTemplateResponse:
    versions = (
        template.versions
        if user.has_role("administrator", "recruiter")
        else [template.current_version]
    )
    return MessageTemplateResponse(
        **_summary_response(template, user).model_dump(),
        created_by_id=template.created_by_id,
        created_by_username=template.created_by_username,
        created_by_display_name=template.created_by_display_name,
        created_at=template.created_at,
        current_version=_version_response(template.current_version),
        versions=[_version_response(version) for version in versions],
    )


def _reload_template(
    db: Session,
    template_id: uuid.UUID,
    user: User,
) -> MessageTemplateResponse:
    db.expire_all()
    return _detail_response(get_template(db, template_id), user)


@router.get("", response_model=MessageTemplateListResponse)
def list_message_templates(
    current_user: CurrentUser,
    db: DbSession,
    template_status: Annotated[
        Literal["active", "inactive", "all"], Query(alias="status")
    ] = "active",
    template_type: MessageTemplateType | None = None,
    query: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MessageTemplateListResponse:
    _ensure_read_access(current_user)
    manager_only = current_user.has_role("hiring_manager") and not current_user.has_role(
        "administrator", "recruiter"
    )
    if manager_only and template_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用人经理只能使用已启用的沟通模板",
        )

    filters = []
    if template_status != "all":
        filters.append(MessageTemplate.status == template_status)
    if template_type is not None:
        filters.append(MessageTemplate.template_type == template_type)
    normalized_query = query.strip() if query else ""
    if normalized_query:
        filters.append(MessageTemplate.name.ilike(f"%{normalized_query}%"))

    total = db.scalar(select(func.count(MessageTemplate.id)).where(*filters)) or 0
    templates = db.scalars(
        select(MessageTemplate)
        .where(*filters)
        .options(selectinload(MessageTemplate.versions))
        .order_by(MessageTemplate.updated_at.desc(), MessageTemplate.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return MessageTemplateListResponse(
        items=[_summary_response(template, current_user) for template in templates],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=MessageTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_message_template(
    payload: MessageTemplateCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageTemplateResponse:
    _ensure_write_access(current_user)
    try:
        template = create_template(
            db,
            template_type=payload.template_type,
            name=payload.name,
            subject=payload.subject,
            body=payload.body,
            variables=payload.variables,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except MessageTemplateServiceError as error:
        db.rollback()
        _raise_service_error(error)
    except IntegrityError as error:
        db.rollback()
        try:
            template = create_template(
                db,
                template_type=payload.template_type,
                name=payload.name,
                subject=payload.subject,
                body=payload.body,
                variables=payload.variables,
                idempotency_key=payload.idempotency_key,
                actor=current_user,
            )
            db.commit()
        except (MessageTemplateServiceError, IntegrityError):
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="启用的沟通模板名称已存在",
            ) from error
    return _reload_template(db, template.id, current_user)


@router.get("/{template_id:uuid}", response_model=MessageTemplateResponse)
def get_message_template(
    template_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageTemplateResponse:
    _ensure_read_access(current_user)
    try:
        template = get_template(db, template_id)
    except MessageTemplateServiceError as error:
        _raise_service_error(error)
    manager_only = current_user.has_role("hiring_manager") and not current_user.has_role(
        "administrator", "recruiter"
    )
    if manager_only and template.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="沟通模板不存在")
    return _detail_response(template, current_user)


@router.post("/{template_id:uuid}/versions", response_model=MessageTemplateResponse)
def create_message_template_version(
    template_id: uuid.UUID,
    payload: MessageTemplateVersionCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageTemplateResponse:
    _ensure_write_access(current_user)
    try:
        template = create_template_version(
            db,
            template_id=template_id,
            subject=payload.subject,
            body=payload.body,
            variables=payload.variables,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except MessageTemplateServiceError as error:
        db.rollback()
        _raise_service_error(error)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="沟通模板已被并发修改，请刷新后重试",
        ) from error
    return _reload_template(db, template.id, current_user)


def _change_status(
    template_id: uuid.UUID,
    payload: MessageTemplateStatusRequest,
    current_user: User,
    db: Session,
    *,
    target_status: Literal["active", "inactive"],
) -> MessageTemplateResponse:
    _ensure_write_access(current_user)
    try:
        template = set_template_status(
            db,
            template_id=template_id,
            target_status=target_status,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except MessageTemplateServiceError as error:
        db.rollback()
        _raise_service_error(error)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="启用的沟通模板名称已存在",
        ) from error
    return _reload_template(db, template.id, current_user)


@router.post("/{template_id:uuid}/activate", response_model=MessageTemplateResponse)
def activate_message_template(
    template_id: uuid.UUID,
    payload: MessageTemplateStatusRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageTemplateResponse:
    return _change_status(
        template_id,
        payload,
        current_user,
        db,
        target_status="active",
    )


@router.post("/{template_id:uuid}/deactivate", response_model=MessageTemplateResponse)
def deactivate_message_template(
    template_id: uuid.UUID,
    payload: MessageTemplateStatusRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageTemplateResponse:
    return _change_status(
        template_id,
        payload,
        current_user,
        db,
        target_status="inactive",
    )
