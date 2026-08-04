import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import User
from app.schemas.prompt import (
    PromptTemplateCreateRequest,
    PromptTemplateListResponse,
    PromptTemplatePublishRequest,
    PromptTemplateResponse,
    PromptTemplateVersionCreateRequest,
)
from app.services.prompt_templates import (
    create_template,
    create_version,
    get_template_or_404,
    list_templates,
    publish_version,
    template_response,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _ensure_prompt_admin(user: User) -> None:
    if not user.has_role("administrator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要企业管理员权限",
        )


@router.get("", response_model=PromptTemplateListResponse)
def list_prompt_templates(
    current_user: CurrentUser,
    db: DbSession,
) -> PromptTemplateListResponse:
    _ensure_prompt_admin(current_user)
    return PromptTemplateListResponse(
        items=[template_response(template) for template in list_templates(db)]
    )


@router.get("/{template_id}", response_model=PromptTemplateResponse)
def get_prompt_template(
    template_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> PromptTemplateResponse:
    _ensure_prompt_admin(current_user)
    return template_response(get_template_or_404(db, template_id))


@router.post("", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_prompt_template(
    payload: PromptTemplateCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> PromptTemplateResponse:
    _ensure_prompt_admin(current_user)
    return template_response(create_template(db, payload, actor=current_user))


@router.post("/{template_id}/versions", response_model=PromptTemplateResponse)
def create_prompt_template_version(
    template_id: uuid.UUID,
    payload: PromptTemplateVersionCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> PromptTemplateResponse:
    _ensure_prompt_admin(current_user)
    return template_response(create_version(db, template_id, payload, actor=current_user))


@router.post("/{template_id}/publish", response_model=PromptTemplateResponse)
def publish_prompt_template_version(
    template_id: uuid.UUID,
    payload: PromptTemplatePublishRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> PromptTemplateResponse:
    _ensure_prompt_admin(current_user)
    return template_response(publish_version(db, template_id, payload, actor=current_user))
