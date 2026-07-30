from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.candidate_process import CandidateProcess
    from app.models.interview import CandidateInterviewSchedule
    from app.models.interview_report import InterviewReport
    from app.models.job import Job
    from app.models.offer import Offer
    from app.models.onboarding import Onboarding
    from app.models.resume import ResumeDocument, ScreeningResult
    from app.models.talent_pool import TalentPoolMembership
    from app.models.user import User


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'merged')",
            name="ck_candidates_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(320))
    full_name_normalized: Mapped[str | None] = mapped_column(String(200), index=True)
    phone_normalized: Mapped[str | None] = mapped_column(String(30), index=True)
    email_normalized: Mapped[str | None] = mapped_column(String(320), index=True)
    experience_fingerprint: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active", index=True
    )
    merged_into_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"),
        index=True,
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    merged_into: Mapped[Candidate | None] = relationship(
        remote_side=[id],
        foreign_keys=[merged_into_candidate_id],
    )
    applications: Mapped[list[JobApplication]] = relationship(
        back_populates="candidate",
        foreign_keys="JobApplication.candidate_id",
    )
    documents: Mapped[list[ResumeDocument]] = relationship(back_populates="candidate")
    talent_pool_memberships: Mapped[list[TalentPoolMembership]] = relationship(
        back_populates="candidate",
        order_by="TalentPoolMembership.created_at",
    )
    duplicate_reviews_as_a: Mapped[list[CandidateDuplicateReview]] = relationship(
        back_populates="candidate_a",
        foreign_keys="CandidateDuplicateReview.candidate_a_id",
        cascade="all, delete-orphan",
    )
    duplicate_reviews_as_b: Mapped[list[CandidateDuplicateReview]] = relationship(
        back_populates="candidate_b",
        foreign_keys="CandidateDuplicateReview.candidate_b_id",
        cascade="all, delete-orphan",
    )

    @property
    def candidate_code(self) -> str:
        return f"CAND-{self.id.hex[:12].upper()}"


class JobApplication(Base):
    __tablename__ = "job_applications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'merged')",
            name="ck_job_applications_status",
        ),
        CheckConstraint(
            "source_type IN ('resume_upload', 'talent_recommendation')",
            name="ck_job_applications_source_type",
        ),
        CheckConstraint(
            "(source_type = 'resume_upload' "
            "AND talent_recommendation_run_id IS NULL "
            "AND talent_recommendation_result_id IS NULL) OR "
            "(source_type = 'talent_recommendation' "
            "AND talent_recommendation_run_id IS NOT NULL "
            "AND talent_recommendation_result_id IS NOT NULL)",
            name="ck_job_applications_recommendation_source",
        ),
        Index(
            "uq_job_applications_active_candidate_job",
            "candidate_id",
            "job_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        ForeignKeyConstraint(
            ["id", "primary_document_id"],
            [
                "application_resume_documents.application_id",
                "application_resume_documents.document_id",
            ],
            name="fk_job_applications_primary_document_link",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["talent_recommendation_result_id", "talent_recommendation_run_id"],
            [
                "talent_recommendation_results.id",
                "talent_recommendation_results.run_id",
            ],
            name="fk_job_applications_recommendation_result",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint(
            "talent_recommendation_result_id",
            name="uq_job_applications_recommendation_result",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active", index=True
    )
    source_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="resume_upload",
        server_default="resume_upload",
        index=True,
    )
    talent_recommendation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        index=True,
    )
    talent_recommendation_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        index=True,
    )
    merged_into_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_applications.id", ondelete="SET NULL"),
        index=True,
    )
    primary_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "resume_documents.id",
            name="fk_job_applications_primary_document_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        index=True,
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    candidate: Mapped[Candidate] = relationship(
        back_populates="applications",
        foreign_keys=[candidate_id],
    )
    job: Mapped[Job] = relationship(back_populates="applications")
    merged_into: Mapped[JobApplication | None] = relationship(
        remote_side=[id],
        foreign_keys=[merged_into_application_id],
    )
    documents: Mapped[list[ResumeDocument]] = relationship(
        back_populates="application",
        foreign_keys="ResumeDocument.application_id",
        order_by="ResumeDocument.created_at",
    )
    document_links: Mapped[list[ApplicationResumeDocument]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        foreign_keys="ApplicationResumeDocument.application_id",
        order_by="ApplicationResumeDocument.created_at",
    )
    shared_documents: Mapped[list[ResumeDocument]] = relationship(
        secondary="application_resume_documents",
        primaryjoin="JobApplication.id == ApplicationResumeDocument.application_id",
        secondaryjoin="ApplicationResumeDocument.document_id == ResumeDocument.id",
        viewonly=True,
        order_by="ResumeDocument.created_at",
    )
    primary_document: Mapped[ResumeDocument | None] = relationship(
        foreign_keys=[primary_document_id],
        post_update=True,
    )
    process: Mapped[CandidateProcess | None] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        uselist=False,
    )
    interview_schedule: Mapped[CandidateInterviewSchedule | None] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        uselist=False,
    )
    interview_report: Mapped[InterviewReport | None] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        uselist=False,
    )
    offer: Mapped[Offer | None] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        uselist=False,
    )
    onboarding: Mapped[Onboarding | None] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        uselist=False,
        foreign_keys="Onboarding.application_id",
        overlaps="offer,onboarding",
    )
    screening_results: Mapped[list[ScreeningResult]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        foreign_keys="ScreeningResult.application_id",
        order_by="ScreeningResult.created_at",
        passive_deletes=True,
    )


class ApplicationResumeDocument(Base):
    __tablename__ = "application_resume_documents"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_documents.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    application: Mapped[JobApplication] = relationship(
        back_populates="document_links",
        foreign_keys=[application_id],
    )
    document: Mapped[ResumeDocument] = relationship(back_populates="application_links")


class CandidateDuplicateReview(Base):
    __tablename__ = "candidate_duplicate_reviews"
    __table_args__ = (
        CheckConstraint(
            "candidate_a_id <> candidate_b_id",
            name="ck_candidate_duplicate_reviews_distinct_candidates",
        ),
        CheckConstraint(
            "confidence IN ('strong', 'weak')",
            name="ck_candidate_duplicate_reviews_confidence",
        ),
        CheckConstraint(
            "status IN ('pending', 'not_duplicate', 'merged')",
            name="ck_candidate_duplicate_reviews_status",
        ),
        Index(
            "uq_candidate_duplicate_reviews_pair",
            "candidate_a_id",
            "candidate_b_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resume_documents.id", ondelete="SET NULL"), index=True
    )
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    signals: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending", index=True
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    candidate_a: Mapped[Candidate] = relationship(
        back_populates="duplicate_reviews_as_a", foreign_keys=[candidate_a_id]
    )
    candidate_b: Mapped[Candidate] = relationship(
        back_populates="duplicate_reviews_as_b", foreign_keys=[candidate_b_id]
    )
    source_document: Mapped[ResumeDocument | None] = relationship()
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])
