from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.prompt import PromptTemplateVersion
    from app.models.user import User


AI_TASK_STATUSES = ("queued", "running", "succeeded", "failed", "retrying", "cancelled")
AI_CALL_STATUSES = ("succeeded", "failed")
AI_TASK_EVENT_TYPES = ("queued", "started", "retry_scheduled", "succeeded", "failed", "cancelled")

AI_TASK_STATUS_SQL = ", ".join(f"'{status}'" for status in AI_TASK_STATUSES)
AI_CALL_STATUS_SQL = ", ".join(f"'{status}'" for status in AI_CALL_STATUSES)
AI_TASK_EVENT_TYPE_SQL = ", ".join(f"'{event_type}'" for event_type in AI_TASK_EVENT_TYPES)


class AiTask(Base):
    __tablename__ = "ai_tasks"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({AI_TASK_STATUS_SQL})",
            name="ck_ai_tasks_status",
        ),
        CheckConstraint("length(trim(task_name)) BETWEEN 1 AND 120", name="ck_ai_tasks_name"),
        CheckConstraint("length(trim(scenario)) BETWEEN 1 AND 80", name="ck_ai_tasks_scenario"),
        CheckConstraint(
            "resource_type IS NULL OR length(trim(resource_type)) BETWEEN 1 AND 80",
            name="ck_ai_tasks_resource_type",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_ai_tasks_attempt_count"),
        CheckConstraint("max_retries >= 0", name="ck_ai_tasks_max_retries"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_tasks_duration_ms",
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="ck_ai_tasks_completed_at",
        ),
        Index("ix_ai_tasks_status_created", "status", "created_at"),
        Index("ix_ai_tasks_resource", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    celery_task_id: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued", index=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    candidate_profile_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    events: Mapped[list[AiTaskEvent]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="AiTaskEvent.created_at",
    )
    calls: Mapped[list[AiCallLog]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="AiCallLog.created_at",
    )


class AiTaskEvent(Base):
    __tablename__ = "ai_task_events"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({AI_TASK_EVENT_TYPE_SQL})",
            name="ck_ai_task_events_type",
        ),
        CheckConstraint(
            f"status_after IN ({AI_TASK_STATUS_SQL})",
            name="ck_ai_task_events_status_after",
        ),
        CheckConstraint("length(message) <= 500", name="ck_ai_task_events_message_length"),
        Index("ix_ai_task_events_task_created", "task_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status_after: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    task: Mapped[AiTask] = relationship(back_populates="events")


class AiCallLog(Base):
    __tablename__ = "ai_call_logs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({AI_CALL_STATUS_SQL})",
            name="ck_ai_call_logs_status",
        ),
        CheckConstraint("length(trim(scenario)) BETWEEN 1 AND 80", name="ck_ai_call_logs_scenario"),
        CheckConstraint(
            "resource_type IS NULL OR length(trim(resource_type)) BETWEEN 1 AND 80",
            name="ck_ai_call_logs_resource_type",
        ),
        CheckConstraint("retry_count >= 0", name="ck_ai_call_logs_retry_count"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_call_logs_duration_ms",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_call_logs_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_call_logs_output_tokens",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_ai_call_logs_total_tokens",
        ),
        Index("ix_ai_call_logs_scenario_created", "scenario", "created_at"),
        Index("ix_ai_call_logs_status_created", "status", "created_at"),
        Index("ix_ai_call_logs_resource", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_tasks.id", ondelete="SET NULL"), index=True
    )
    scenario: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(120))
    prompt_template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_template_versions.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(
        String(60), nullable=False, default="openai_compatible", server_default="openai_compatible"
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    invoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    candidate_profile_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    task: Mapped[AiTask | None] = relationship(back_populates="calls")
    prompt_template_version: Mapped[PromptTemplateVersion | None] = relationship(
        back_populates="ai_call_logs"
    )
    invoked_by: Mapped[User | None] = relationship(foreign_keys=[invoked_by_id])
