from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
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
    from app.models.candidate import JobApplication
    from app.models.resume import ScreeningResult
    from app.models.user import User


class InterviewReport(Base):
    __tablename__ = "interview_reports"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_interview_reports_application"),
        CheckConstraint(
            "status IN ('draft', 'confirmed')",
            name="ck_interview_reports_status",
        ),
        CheckConstraint(
            "current_version_number >= 1",
            name="ck_interview_reports_current_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", index=True
    )
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    application: Mapped[JobApplication] = relationship(back_populates="interview_report")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    confirmed_by: Mapped[User | None] = relationship(foreign_keys=[confirmed_by_id])
    versions: Mapped[list[InterviewReportVersion]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="InterviewReportVersion.version_number",
    )

    @property
    def current_version(self) -> InterviewReportVersion:
        for version in reversed(self.versions):
            if version.version_number == self.current_version_number:
                return version
        raise RuntimeError("面试报告当前版本不存在")


class InterviewReportVersion(Base):
    __tablename__ = "interview_report_versions"
    __table_args__ = (
        UniqueConstraint(
            "report_id",
            "version_number",
            name="uq_interview_report_version_number",
        ),
        UniqueConstraint(
            "report_id",
            "idempotency_key",
            name="uq_interview_report_version_idempotency",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_interview_report_versions_number",
        ),
        CheckConstraint(
            "generation_mode IN ('ai', 'manual')",
            name="ck_interview_report_versions_generation_mode",
        ),
        CheckConstraint(
            "conclusion IS NULL OR conclusion IN ('hire', 'next_round', 'reserve', 'reject')",
            name="ck_interview_report_versions_conclusion",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_report_versions.id", ondelete="SET NULL"), index=True
    )
    generation_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    conclusion: Mapped[str | None] = mapped_column(String(20))
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    concerns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    follow_up_actions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    screening_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("screening_results.id", ondelete="SET NULL"), index=True
    )
    evaluation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    missing_rounds: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    ai_failure_code: Mapped[str | None] = mapped_column(String(50))
    ai_failure_message: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    report: Mapped[InterviewReport] = relationship(back_populates="versions")
    source_version: Mapped[InterviewReportVersion | None] = relationship(
        remote_side=[id], foreign_keys=[source_version_id]
    )
    screening_result: Mapped[ScreeningResult | None] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
