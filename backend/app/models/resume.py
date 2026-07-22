from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
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
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="uploaded", index=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(50))
    failure_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
