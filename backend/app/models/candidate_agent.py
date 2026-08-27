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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.ai_observability import AiCallLog
    from app.models.candidate import JobApplication
    from app.models.job import Job
    from app.models.prompt import PromptTemplateVersion
    from app.models.user import User


CANDIDATE_AGENT_SESSION_STATUSES = ("active", "archived")
CANDIDATE_AGENT_EXCHANGE_STATUSES = ("pending", "succeeded", "failed", "manual_fallback")

SESSION_STATUS_SQL = ", ".join(f"'{item}'" for item in CANDIDATE_AGENT_SESSION_STATUSES)
EXCHANGE_STATUS_SQL = ", ".join(f"'{item}'" for item in CANDIDATE_AGENT_EXCHANGE_STATUSES)


class CandidateAgentSession(Base):
    __tablename__ = "candidate_agent_sessions"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({SESSION_STATUS_SQL})",
            name="ck_candidate_agent_sessions_status",
        ),
        CheckConstraint(
            "title IS NULL OR length(trim(title)) BETWEEN 1 AND 120",
            name="ck_candidate_agent_sessions_title",
        ),
        Index(
            "ix_candidate_agent_sessions_application_status",
            "application_id",
            "status",
        ),
        Index(
            "ix_candidate_agent_sessions_job_created",
            "job_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active", index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    job: Mapped[Job] = relationship(foreign_keys=[job_id])
    application: Mapped[JobApplication] = relationship(foreign_keys=[application_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    exchanges: Mapped[list[CandidateAgentExchange]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CandidateAgentExchange.sequence_number",
    )


class CandidateAgentExchange(Base):
    __tablename__ = "candidate_agent_exchanges"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "sequence_number",
            name="uq_candidate_agent_exchanges_sequence",
        ),
        UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_candidate_agent_exchanges_idempotency",
        ),
        CheckConstraint(
            f"status IN ({EXCHANGE_STATUS_SQL})",
            name="ck_candidate_agent_exchanges_status",
        ),
        CheckConstraint(
            "sequence_number >= 1",
            name="ck_candidate_agent_exchanges_sequence",
        ),
        CheckConstraint(
            "length(trim(question)) BETWEEN 1 AND 2000",
            name="ck_candidate_agent_exchanges_question",
        ),
        CheckConstraint(
            "answer IS NULL OR length(answer) <= 8000",
            name="ck_candidate_agent_exchanges_answer",
        ),
        CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) BETWEEN 1 AND 80",
            name="ck_candidate_agent_exchanges_failure_code",
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'manual_fallback') AND answer IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'manual_fallback'))",
            name="ck_candidate_agent_exchanges_completed_answer",
        ),
        Index(
            "ix_candidate_agent_exchanges_session_created",
            "session_id",
            "created_at",
        ),
        Index(
            "ix_candidate_agent_exchanges_status_created",
            "status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    evidence_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    evidence_references: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    knowledge_citations: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    tool_trajectory: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    ai_call_log_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    ai_call_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_call_logs.id", ondelete="SET NULL"), index=True
    )
    prompt_template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_template_versions.id", ondelete="SET NULL"), index=True
    )
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(120))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    session: Mapped[CandidateAgentSession] = relationship(back_populates="exchanges")
    ai_call_log: Mapped[AiCallLog | None] = relationship(foreign_keys=[ai_call_log_id])
    prompt_template_version: Mapped[PromptTemplateVersion | None] = relationship(
        foreign_keys=[prompt_template_version_id]
    )
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
