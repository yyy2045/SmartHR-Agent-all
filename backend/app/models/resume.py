from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
    from app.models.candidate import Candidate, JobApplication
    from app.models.candidate_process import CandidateProcess
    from app.models.interview import CandidateInterviewSchedule
    from app.models.job import Job, JobCriteriaVersion
    from app.models.knowledge import ResumeEmbeddingChunk
    from app.models.user import User


class ScreeningBatch(Base):
    __tablename__ = "screening_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploading', 'ready', 'partial_failure', 'failed', "
            "'processing', 'completed')",
            name="ck_screening_batches_status",
        ),
        CheckConstraint(
            "ai_input_mode IN ('raw', 'redacted')",
            name="ck_screening_batches_ai_input_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criteria_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_criteria_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    ai_input_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="raw", server_default="raw"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="uploading", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    job: Mapped[Job] = relationship(back_populates="screening_batches")
    criteria_version: Mapped[JobCriteriaVersion] = relationship(
        back_populates="screening_batches"
    )
    documents: Mapped[list[ResumeDocument]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ResumeDocument.created_at",
    )


class ResumeDocument(Base):
    __tablename__ = "resume_documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded', 'queued', 'processing', 'completed', 'failed')",
            name="ck_resume_documents_status",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_resume_documents_size"),
        CheckConstraint("attempt_count >= 1", name="ck_resume_documents_attempt_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screening_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"),
        index=True,
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_applications.id", ondelete="RESTRICT"),
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    detected_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_key: Mapped[str | None] = mapped_column(String(500))
    extraction_method: Mapped[str | None] = mapped_column(String(30))
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    redaction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="uploaded", index=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(50))
    failure_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    processing_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_id: Mapped[str | None] = mapped_column(String(100), index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    batch: Mapped[ScreeningBatch] = relationship(back_populates="documents")
    candidate: Mapped[Candidate | None] = relationship(back_populates="documents")
    application: Mapped[JobApplication | None] = relationship(back_populates="documents")
    text_segments: Mapped[list[ResumeTextSegment]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ResumeTextSegment.sort_order",
    )
    candidate_profiles: Mapped[list[CandidateProfile]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="CandidateProfile.version_number",
    )
    screening_results: Mapped[list[ScreeningResult]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ScreeningResult.analysis_version",
    )
    embedding_chunks: Mapped[list[ResumeEmbeddingChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    candidate_process: Mapped[CandidateProcess | None] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,
    )
    interview_schedule: Mapped[CandidateInterviewSchedule | None] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def candidate_code(self) -> str:
        if self.candidate is not None:
            return self.candidate.candidate_code
        return f"CAND-{self.id.hex[:12].upper()}"


class ResumeTextSegment(Base):
    __tablename__ = "resume_text_segments"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('pdf_page', 'docx_paragraph', 'image_ocr')",
            name="ck_resume_text_segments_source_type",
        ),
        CheckConstraint("sort_order >= 0", name="ck_resume_text_segments_sort_order"),
        CheckConstraint(
            "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)",
            name="ck_resume_text_segments_ocr_confidence",
        ),
        UniqueConstraint("document_id", "segment_key", name="uq_resume_segment_key"),
        UniqueConstraint("document_id", "sort_order", name="uq_resume_segment_sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_key: Mapped[str] = mapped_column(String(20), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    redacted_text: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document: Mapped[ResumeDocument] = relationship(back_populates="text_segments")
    redactions: Mapped[list[ResumeRedaction]] = relationship(
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="ResumeRedaction.start_offset",
    )
    evidence_citations: Mapped[list[EvidenceCitation]] = relationship(
        back_populates="segment",
    )


class ResumeRedaction(Base):
    __tablename__ = "resume_redactions"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('name', 'phone', 'email', 'id_number', 'address', "
            "'social_account')",
            name="ck_resume_redactions_entity_type",
        ),
        CheckConstraint("start_offset >= 0", name="ck_resume_redactions_start_offset"),
        CheckConstraint("end_offset > start_offset", name="ck_resume_redactions_end_offset"),
        UniqueConstraint(
            "segment_id",
            "start_offset",
            "end_offset",
            "entity_type",
            name="uq_resume_redaction_span",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_text_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    replacement_text: Mapped[str] = mapped_column(String(100), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    segment: Mapped[ResumeTextSegment] = relationship(back_populates="redactions")


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="ck_candidate_profiles_version"),
        CheckConstraint("source IN ('ai', 'manual')", name="ck_candidate_profiles_source"),
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_candidate_profile_document_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")
    source_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="SET NULL")
    )
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    education: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    work_experiences: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    projects: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    skills: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    certifications: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    languages: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document: Mapped[ResumeDocument] = relationship(back_populates="candidate_profiles")
    screening_results: Mapped[list[ScreeningResult]] = relationship(
        back_populates="candidate_profile"
    )
    embedding_chunks: Mapped[list[ResumeEmbeddingChunk]] = relationship(
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
    )


class ScreeningResult(Base):
    __tablename__ = "screening_results"
    __table_args__ = (
        CheckConstraint("analysis_version >= 1", name="ck_screening_results_version"),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_screening_results_status",
        ),
        CheckConstraint(
            "ai_group IS NULL OR ai_group IN ('passed', 'low_match', 'auto_rejected')",
            name="ck_screening_results_ai_group",
        ),
        CheckConstraint(
            "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
            name="ck_screening_results_total_score",
        ),
        CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 100",
            name="ck_screening_results_pass_threshold",
        ),
        UniqueConstraint(
            "document_id",
            "criteria_version_id",
            "analysis_version",
            name="uq_screening_result_analysis_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        index=True,
    )
    criteria_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_criteria_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="processing", index=True
    )
    ai_group: Mapped[str | None] = mapped_column(String(30), index=True)
    total_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    pass_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    hard_requirement_results: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    missing_items: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    interview_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(50))
    failure_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document: Mapped[ResumeDocument] = relationship(back_populates="screening_results")
    candidate_profile: Mapped[CandidateProfile | None] = relationship(
        back_populates="screening_results"
    )
    criteria_version: Mapped[JobCriteriaVersion] = relationship(
        back_populates="screening_results"
    )
    dimension_scores: Mapped[list[DimensionScore]] = relationship(
        back_populates="screening_result",
        cascade="all, delete-orphan",
        order_by="DimensionScore.sort_order",
    )
    evidence_citations: Mapped[list[EvidenceCitation]] = relationship(
        back_populates="screening_result",
        cascade="all, delete-orphan",
        order_by="EvidenceCitation.sort_order",
    )
    recruiter_decisions: Mapped[list[RecruiterDecision]] = relationship(
        back_populates="screening_result",
        cascade="all, delete-orphan",
        order_by="RecruiterDecision.sequence_number",
    )


class DimensionScore(Base):
    __tablename__ = "dimension_scores"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_dimension_scores_score"),
        CheckConstraint(
            "weight_percent >= 0 AND weight_percent <= 100",
            name="ck_dimension_scores_weight",
        ),
        CheckConstraint(
            "weighted_score >= 0 AND weighted_score <= 100",
            name="ck_dimension_scores_weighted_score",
        ),
        CheckConstraint("sort_order >= 0", name="ck_dimension_scores_sort_order"),
        UniqueConstraint(
            "screening_result_id",
            "sort_order",
            name="uq_dimension_score_result_sort_order",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    screening_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screening_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scoring_dimension_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scoring_dimensions.id", ondelete="SET NULL"),
        index=True,
    )
    dimension_name: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    weighted_score: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    missing_items: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    screening_result: Mapped[ScreeningResult] = relationship(
        back_populates="dimension_scores"
    )
    evidence_citations: Mapped[list[EvidenceCitation]] = relationship(
        back_populates="dimension_score"
    )


class EvidenceCitation(Base):
    __tablename__ = "evidence_citations"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('profile', 'hard_requirement', 'dimension')",
            name="ck_evidence_citations_subject_type",
        ),
        CheckConstraint("sort_order >= 0", name="ck_evidence_citations_sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    screening_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screening_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dimension_score_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dimension_scores.id", ondelete="SET NULL"),
        index=True,
    )
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resume_text_segments.id", ondelete="SET NULL"),
        index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(100), nullable=False)
    segment_key: Mapped[str] = mapped_column(String(20), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    screening_result: Mapped[ScreeningResult] = relationship(
        back_populates="evidence_citations"
    )
    dimension_score: Mapped[DimensionScore | None] = relationship(
        back_populates="evidence_citations"
    )
    segment: Mapped[ResumeTextSegment | None] = relationship(
        back_populates="evidence_citations"
    )


class RecruiterDecision(Base):
    __tablename__ = "recruiter_decisions"
    __table_args__ = (
        CheckConstraint(
            "previous_decision IN ('unprocessed', 'shortlisted', 'pending', 'rejected')",
            name="ck_recruiter_decisions_previous",
        ),
        CheckConstraint(
            "decision IN ('shortlisted', 'pending', 'rejected')",
            name="ck_recruiter_decisions_decision",
        ),
        CheckConstraint("sequence_number >= 1", name="ck_recruiter_decisions_sequence"),
        UniqueConstraint(
            "screening_result_id",
            "sequence_number",
            name="uq_recruiter_decision_result_sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    screening_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screening_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    is_auto_rejection_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    screening_result: Mapped[ScreeningResult] = relationship(
        back_populates="recruiter_decisions"
    )
    operator: Mapped[User] = relationship()
