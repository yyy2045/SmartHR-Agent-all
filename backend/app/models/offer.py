from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
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
    from app.models.interview_report import InterviewReportVersion
    from app.models.user import User


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_offers_application"),
        CheckConstraint(
            "status IN ('draft', 'pending_manager_confirmation', "
            "'pending_approval', 'approved', 'rejected')",
            name="ck_offers_status",
        ),
        CheckConstraint(
            "current_version_number >= 1",
            name="ck_offers_current_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="draft", server_default="draft", index=True
    )
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    application: Mapped[JobApplication] = relationship(back_populates="offer")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    versions: Mapped[list[OfferVersion]] = relationship(
        back_populates="offer",
        cascade="all, delete-orphan",
        order_by="OfferVersion.version_number",
    )

    @property
    def current_version(self) -> OfferVersion:
        for version in reversed(self.versions):
            if version.version_number == self.current_version_number:
                return version
        raise RuntimeError("Offer 当前版本不存在")


class OfferVersion(Base):
    __tablename__ = "offer_versions"
    __table_args__ = (
        UniqueConstraint(
            "offer_id",
            "version_number",
            name="uq_offer_version_number",
        ),
        UniqueConstraint(
            "offer_id",
            "idempotency_key",
            name="uq_offer_version_idempotency",
        ),
        CheckConstraint("version_number >= 1", name="ck_offer_versions_number"),
        CheckConstraint("currency = 'CNY'", name="ck_offer_versions_currency"),
        CheckConstraint("monthly_salary > 0", name="ck_offer_versions_monthly_salary"),
        CheckConstraint(
            "annual_salary_months >= 1 AND annual_salary_months <= 36",
            name="ck_offer_versions_annual_salary_months",
        ),
        CheckConstraint(
            "probation_months >= 0 AND probation_months <= 12",
            name="ck_offer_versions_probation_months",
        ),
        CheckConstraint(
            "(probation_months = 0 AND probation_monthly_salary IS NULL) OR "
            "(probation_months > 0 AND probation_monthly_salary > 0)",
            name="ck_offer_versions_probation_salary",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("offer_versions.id", ondelete="SET NULL"), index=True
    )
    source_interview_report_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_report_versions.id", ondelete="SET NULL"), index=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="CNY", server_default="CNY"
    )
    monthly_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    annual_salary_months: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    probation_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    probation_monthly_salary: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    bonus_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    offer: Mapped[Offer] = relationship(back_populates="versions")
    source_version: Mapped[OfferVersion | None] = relationship(
        remote_side=[id], foreign_keys=[source_version_id]
    )
    source_interview_report_version: Mapped[InterviewReportVersion | None] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    manager_confirmation: Mapped[OfferManagerConfirmation | None] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        uselist=False,
    )
    approval: Mapped[OfferApproval | None] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        uselist=False,
    )


class OfferManagerConfirmation(Base):
    __tablename__ = "offer_manager_confirmations"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_offer_manager_confirmation_version"),
        CheckConstraint(
            "decision IN ('confirmed', 'rejected')",
            name="ck_offer_manager_confirmations_decision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offer_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confirmer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    confirmer_username: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmer_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    version: Mapped[OfferVersion] = relationship(back_populates="manager_confirmation")
    confirmer: Mapped[User | None] = relationship(foreign_keys=[confirmer_id])


class OfferApproval(Base):
    __tablename__ = "offer_approvals"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_offer_approval_version"),
        CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_offer_approvals_decision",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("offer_versions.id", ondelete="CASCADE"), nullable=False, index=True
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

    version: Mapped[OfferVersion] = relationship(back_populates="approval")
    approver: Mapped[User | None] = relationship(foreign_keys=[approver_id])
