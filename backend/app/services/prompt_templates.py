from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models import PromptTemplate, PromptTemplateVersion, User
from app.schemas.prompt import (
    PromptTemplateCreateRequest,
    PromptTemplatePublishRequest,
    PromptTemplateResponse,
    PromptTemplateVersionCreateRequest,
    PromptTemplateVersionResponse,
)


@dataclass(frozen=True)
class PublishedPromptSnapshot:
    version_id: uuid.UUID
    scenario: str
    version_number: int
    system_prompt: str
    user_prompt_template: str
    model_parameters: dict[str, object]

    @property
    def prompt_version(self) -> str:
        return f"{self.scenario}-v{self.version_number}"


def _actor_snapshot(user: User) -> dict[str, object]:
    return {
        "created_by_id": user.id,
        "created_by_username": user.username,
        "created_by_display_name": user.display_name,
    }


def _version_response(version: PromptTemplateVersion) -> PromptTemplateVersionResponse:
    return PromptTemplateVersionResponse(
        id=version.id,
        template_id=version.template_id,
        version_number=version.version_number,
        status=version.status,
        source_version_id=version.source_version_id,
        change_note=version.change_note,
        system_prompt=version.system_prompt,
        user_prompt_template=version.user_prompt_template,
        variables=version.variables,
        output_schema=version.output_schema,
        model_parameters=version.model_parameters,
        created_by_id=version.created_by_id,
        created_by_username=version.created_by_username,
        created_by_display_name=version.created_by_display_name,
        published_by_id=version.published_by_id,
        published_by_username=version.published_by_username,
        published_by_display_name=version.published_by_display_name,
        published_at=version.published_at,
        created_at=version.created_at,
    )


def template_response(template: PromptTemplate) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        id=template.id,
        scenario=template.scenario,
        name=template.name,
        description=template.description,
        status=template.status,
        current_version_number=template.current_version_number,
        resource_version=template.resource_version,
        created_by_id=template.created_by_id,
        created_by_username=template.created_by_username,
        created_by_display_name=template.created_by_display_name,
        created_at=template.created_at,
        updated_at=template.updated_at,
        versions=[_version_response(version) for version in template.versions],
    )


def get_template_or_404(
    db: Session,
    template_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> PromptTemplate:
    query = (
        select(PromptTemplate)
        .where(PromptTemplate.id == template_id)
        .options(selectinload(PromptTemplate.versions))
    )
    if for_update:
        query = query.with_for_update()
    template = db.scalar(query)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prompt 模板不存在",
        )
    return template


def list_templates(db: Session) -> list[PromptTemplate]:
    return list(
        db.scalars(
            select(PromptTemplate)
            .options(selectinload(PromptTemplate.versions))
            .order_by(PromptTemplate.scenario)
        )
    )


def get_published_prompt_snapshot(
    db: Session,
    scenario: str,
) -> PublishedPromptSnapshot | None:
    version = db.scalar(
        select(PromptTemplateVersion)
        .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.template_id)
        .where(
            PromptTemplate.scenario == scenario,
            PromptTemplate.status == "active",
            PromptTemplate.current_version_number == PromptTemplateVersion.version_number,
            PromptTemplateVersion.status == "published",
        )
    )
    if version is None:
        return None
    return PublishedPromptSnapshot(
        version_id=version.id,
        scenario=scenario,
        version_number=version.version_number,
        system_prompt=version.system_prompt,
        user_prompt_template=version.user_prompt_template,
        model_parameters=version.model_parameters or {},
    )


def create_template(
    db: Session,
    payload: PromptTemplateCreateRequest,
    *,
    actor: User,
) -> PromptTemplate:
    template = PromptTemplate(
        scenario=payload.scenario,
        name=payload.name,
        description=payload.description,
        current_version_number=None,
        created_by_id=actor.id,
        created_by_username=actor.username,
        created_by_display_name=actor.display_name,
    )
    version = PromptTemplateVersion(
        template=template,
        version_number=1,
        status="draft",
        idempotency_key=payload.idempotency_key,
        change_note=payload.change_note,
        system_prompt=payload.system_prompt,
        user_prompt_template=payload.user_prompt_template,
        variables=payload.variables,
        output_schema=payload.output_schema,
        model_parameters=payload.model_parameters,
        **_actor_snapshot(actor),
    )
    db.add_all([template, version])
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prompt 模板场景或幂等键已存在",
        ) from error
    db.refresh(template)
    return get_template_or_404(db, template.id)


def create_version(
    db: Session,
    template_id: uuid.UUID,
    payload: PromptTemplateVersionCreateRequest,
    *,
    actor: User,
) -> PromptTemplate:
    template = get_template_or_404(db, template_id, for_update=True)
    if payload.source_version_id is not None and all(
        version.id != payload.source_version_id for version in template.versions
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="来源 Prompt 版本不属于当前模板",
        )
    next_version = max((version.version_number for version in template.versions), default=0) + 1
    version = PromptTemplateVersion(
        template=template,
        version_number=next_version,
        status="draft",
        idempotency_key=payload.idempotency_key,
        source_version_id=payload.source_version_id,
        change_note=payload.change_note,
        system_prompt=payload.system_prompt,
        user_prompt_template=payload.user_prompt_template,
        variables=payload.variables,
        output_schema=payload.output_schema,
        model_parameters=payload.model_parameters,
        **_actor_snapshot(actor),
    )
    template.resource_version += 1
    db.add(version)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        existing = db.scalar(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.template_id == template_id,
                PromptTemplateVersion.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            return get_template_or_404(db, template_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prompt 版本创建冲突",
        ) from error
    return get_template_or_404(db, template_id)


def publish_version(
    db: Session,
    template_id: uuid.UUID,
    payload: PromptTemplatePublishRequest,
    *,
    actor: User,
) -> PromptTemplate:
    template = get_template_or_404(db, template_id, for_update=True)
    if template.resource_version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Prompt 模板版本已变化，请刷新后重试",
        )
    target = next(
        (version for version in template.versions if version.id == payload.version_id),
        None,
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="待发布 Prompt 版本不属于当前模板",
        )
    if target.status == "published" and template.current_version_number == target.version_number:
        db.rollback()
        return template

    now = datetime.now(UTC)
    for version in template.versions:
        if version.status == "published" and version.id != target.id:
            version.status = "retired"
    target.status = "published"
    target.published_by_id = actor.id
    target.published_by_username = actor.username
    target.published_by_display_name = actor.display_name
    target.published_at = now
    template.current_version_number = target.version_number
    template.resource_version += 1
    db.commit()
    return get_template_or_404(db, template_id)
