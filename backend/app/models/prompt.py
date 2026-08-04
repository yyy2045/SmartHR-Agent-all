from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.ai_observability import AiCallLog
    from app.models.user import User


PROMPT_TEMPLATE_SCENARIOS = (
    "jd_generation",
    "resume_analysis",
    "resume_analysis_repair",
    "interview_report",
    "offer_copy",
    "candidate_comparison",
    "candidate_qa",
)
PROMPT_TEMPLATE_STATUSES = ("active", "inactive")
PROMPT_VERSION_STATUSES = ("draft", "published", "retired")

PROMPT_TEMPLATE_SCENARIO_SQL = ", ".join(f"'{scenario}'" for scenario in PROMPT_TEMPLATE_SCENARIOS)
PROMPT_TEMPLATE_STATUS_SQL = ", ".join(f"'{status}'" for status in PROMPT_TEMPLATE_STATUSES)
PROMPT_VERSION_STATUS_SQL = ", ".join(f"'{status}'" for status in PROMPT_VERSION_STATUSES)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        CheckConstraint(
            f"scenario IN ({PROMPT_TEMPLATE_SCENARIO_SQL})",
            name="ck_prompt_templates_scenario",
        ),
        CheckConstraint(
            f"status IN ({PROMPT_TEMPLATE_STATUS_SQL})",
            name="ck_prompt_templates_status",
        ),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_prompt_templates_name"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 1000",
            name="ck_prompt_templates_description",
        ),
        CheckConstraint(
            "current_version_number IS NULL OR current_version_number >= 1",
            name="ck_prompt_templates_current_version",
        ),
        CheckConstraint(
            "resource_version >= 1",
            name="ck_prompt_templates_resource_version",
        ),
        UniqueConstraint("scenario", name="uq_prompt_templates_scenario"),
        Index("ix_prompt_templates_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    current_version_number: Mapped[int | None] = mapped_column(Integer)
    resource_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    versions: Mapped[list[PromptTemplateVersion]] = relationship(
        back_populates="template",
        order_by="PromptTemplateVersion.version_number",
        passive_deletes="all",
    )

    @property
    def current_version(self) -> PromptTemplateVersion | None:
        if self.current_version_number is None:
            return None
        for version in reversed(self.versions):
            if version.version_number == self.current_version_number:
                return version
        raise RuntimeError("Prompt 模板当前发布版本不存在")


class PromptTemplateVersion(Base):
    __tablename__ = "prompt_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_prompt_template_versions_number",
        ),
        UniqueConstraint(
            "template_id",
            "idempotency_key",
            name="uq_prompt_template_versions_idempotency",
        ),
        CheckConstraint("version_number >= 1", name="ck_prompt_template_versions_number"),
        CheckConstraint(
            f"status IN ({PROMPT_VERSION_STATUS_SQL})",
            name="ck_prompt_template_versions_status",
        ),
        CheckConstraint(
            "length(trim(change_note)) BETWEEN 1 AND 500",
            name="ck_prompt_template_versions_change_note",
        ),
        CheckConstraint(
            "length(trim(system_prompt)) BETWEEN 1 AND 20000",
            name="ck_prompt_template_versions_system_prompt",
        ),
        CheckConstraint(
            "length(trim(user_prompt_template)) BETWEEN 1 AND 20000",
            name="ck_prompt_template_versions_user_prompt",
        ),
        CheckConstraint(
            "published_at IS NULL OR status IN ('published', 'retired')",
            name="ck_prompt_template_versions_published_at",
        ),
        Index("ix_prompt_template_versions_template_status", "template_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", index=True
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_template_versions.id", ondelete="RESTRICT"), index=True
    )
    change_note: Mapped[str] = mapped_column(String(500), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    output_schema: Mapped[dict[str, object] | None] = mapped_column(JSON)
    model_parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    published_by_username: Mapped[str | None] = mapped_column(String(64))
    published_by_display_name: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    template: Mapped[PromptTemplate] = relationship(back_populates="versions")
    source_version: Mapped[PromptTemplateVersion | None] = relationship(
        remote_side=[id], foreign_keys=[source_version_id]
    )
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    published_by: Mapped[User | None] = relationship(foreign_keys=[published_by_id])
    ai_call_logs: Mapped[list[AiCallLog]] = relationship(back_populates="prompt_template_version")


@event.listens_for(PromptTemplateVersion, "before_update")
def _protect_prompt_template_version_update(
    _mapper: object,
    _connection: object,
    _target: PromptTemplateVersion,
) -> None:
    raise ValueError("Prompt 模板历史版本不可修改")


@event.listens_for(PromptTemplateVersion, "before_delete")
def _protect_prompt_template_version_delete(
    _mapper: object,
    _connection: object,
    _target: PromptTemplateVersion,
) -> None:
    raise ValueError("Prompt 模板历史版本不可删除")
