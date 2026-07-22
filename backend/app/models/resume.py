from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
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
    from app.models.job import Job, JobCriteriaVersion


class ScreeningBatch(Base):
    __tablename__ = "screening_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploading', 'ready', 'partial_failure', 'failed', "
            "'processing', 'completed')",
            name="ck_screening_batches_status",
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
    text_segments: Mapped[list[ResumeTextSegment]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ResumeTextSegment.sort_order",
    )

    @property
    def candidate_code(self) -> str:
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
