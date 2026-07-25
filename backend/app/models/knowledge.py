from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
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
    from app.models.resume import CandidateProfile, ResumeDocument


class ResumeEmbeddingChunk(Base):
    __tablename__ = "resume_embedding_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_resume_embedding_chunks_index"),
        CheckConstraint(
            "embedding_dimension > 0",
            name="ck_resume_embedding_chunks_dimension",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_resume_embedding_chunks_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_resume_embedding_chunks_attempt_count",
        ),
        CheckConstraint(
            "embedding IS NULL OR vector_dims(embedding) = embedding_dimension",
            name="ck_resume_embedding_chunks_vector_dimension",
        ).ddl_if(dialect="postgresql"),
        UniqueConstraint(
            "candidate_profile_id",
            "chunk_type",
            "chunk_index",
            "embedding_model",
            "embedding_version",
            name="uq_resume_embedding_chunk_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(40), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_segment_keys: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(String(100), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(50))
    failure_message: Mapped[str | None] = mapped_column(Text)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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

    document: Mapped[ResumeDocument] = relationship(back_populates="embedding_chunks")
    candidate_profile: Mapped[CandidateProfile] = relationship(
        back_populates="embedding_chunks"
    )
