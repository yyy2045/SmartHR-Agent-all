from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
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
    from app.models.job import Job
    from app.models.user import User


class RecruitmentRequest(Base):
    __tablename__ = "recruitment_requests"
    __table_args__ = (
        UniqueConstraint(
            "created_by_id",
            "idempotency_key",
            name="uq_recruitment_requests_creator_idempotency",
        ),
        CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'rejected', 'converted')",
            name="ck_recruitment_requests_status",
        ),
        CheckConstraint(
            "current_version_number >= 1",
            name="ck_recruitment_requests_current_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    recruiter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    recruiter: Mapped[User] = relationship(foreign_keys=[recruiter_id])
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    versions: Mapped[list[RecruitmentRequestVersion]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="RecruitmentRequestVersion.version_number",
    )
    approvals: Mapped[list[RecruitmentRequestApproval]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="RecruitmentRequestApproval.decided_at",
    )
    job: Mapped[Job | None] = relationship(
        back_populates="recruitment_request",
        uselist=False,
    )

    @property
    def current_version(self) -> RecruitmentRequestVersion:
        for version in reversed(self.versions):
            if version.version_number == self.current_version_number:
                return version
        raise RuntimeError("招聘需求当前版本不存在")

    @property
    def linked_job_id(self) -> uuid.UUID | None:
        return self.job.id if self.job is not None else None


class RecruitmentRequestVersion(Base):
    __tablename__ = "recruitment_request_versions"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "version_number",
            name="uq_recruitment_request_version_number",
        ),
        CheckConstraint("version_number >= 1", name="ck_recruitment_request_version_number"),
        CheckConstraint("headcount >= 1", name="ck_recruitment_request_headcount"),
        CheckConstraint(
            "priority IN ('urgent', 'high', 'normal', 'low')",
            name="ck_recruitment_request_priority",
        ),
        CheckConstraint(
            "salary_min >= 0 AND salary_max >= salary_min",
            name="ck_recruitment_request_salary_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recruitment_request_versions.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    target_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    salary_min: Mapped[int] = mapped_column(Integer, nullable=False)
    salary_max: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    request: Mapped[RecruitmentRequest] = relationship(back_populates="versions")


class RecruitmentRequestApproval(Base):
    __tablename__ = "recruitment_request_approvals"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_recruitment_request_approval_version"),
        CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_recruitment_request_approval_decision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_request_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    approver_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approver_username: Mapped[str] = mapped_column(String(64), nullable=False)
    approver_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    request: Mapped[RecruitmentRequest] = relationship(back_populates="approvals")
    version: Mapped[RecruitmentRequestVersion] = relationship()
