from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CANDIDATE_AGENT_REPORT_STATUSES = ("pending", "succeeded", "manual_fallback")
REPORT_STATUS_SQL = ", ".join(f"'{item}'" for item in CANDIDATE_AGENT_REPORT_STATUSES)


class CandidateAgentReport(Base):
    __tablename__ = "candidate_agent_reports"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "idempotency_key",
            name="uq_candidate_agent_reports_idempotency",
        ),
        CheckConstraint(
            f"status IN ({REPORT_STATUS_SQL})",
            name="ck_candidate_agent_reports_status",
        ),
        CheckConstraint(
            "overall_recommendation IS NULL OR overall_recommendation IN "
            "('hire', 'next_round', 'reserve', 'reject')",
            name="ck_candidate_agent_reports_overall_recommendation",
        ),
        CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) BETWEEN 1 AND 80",
            name="ck_candidate_agent_reports_failure_code",
        ),
        Index(
            "ix_candidate_agent_reports_application_created",
            "application_id",
            "created_at",
        ),
        Index(
            "ix_candidate_agent_reports_job_created",
            "job_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    match_assessment: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    contradictions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_gaps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    next_step_suggestions: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    open_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    overall_recommendation: Mapped[str | None] = mapped_column(String(20))
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
