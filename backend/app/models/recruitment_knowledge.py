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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.prompt import PromptTemplateVersion
    from app.models.user import User


RECRUITMENT_KNOWLEDGE_BASE_STATUSES = ("active", "inactive")
RECRUITMENT_KNOWLEDGE_CATEGORIES = (
    "policy",
    "job_standard",
    "interview",
    "offer",
    "compensation",
    "communication",
    "general",
)
RECRUITMENT_KNOWLEDGE_VISIBILITY_SCOPES = (
    "all_internal",
    "recruiter_manager",
    "recruiter_only",
    "admin_only",
)
RECRUITMENT_KNOWLEDGE_DOCUMENT_STATUSES = ("active", "archived")
RECRUITMENT_KNOWLEDGE_VERSION_STATUSES = ("draft", "published", "retired")
RECRUITMENT_KNOWLEDGE_CHUNK_STATUSES = ("pending", "processing", "completed", "failed")
RECRUITMENT_KNOWLEDGE_SOURCE_TYPES = ("manual", "upload")

BASE_STATUS_SQL = ", ".join(f"'{item}'" for item in RECRUITMENT_KNOWLEDGE_BASE_STATUSES)
CATEGORY_SQL = ", ".join(f"'{item}'" for item in RECRUITMENT_KNOWLEDGE_CATEGORIES)
VISIBILITY_SCOPE_SQL = ", ".join(f"'{item}'" for item in RECRUITMENT_KNOWLEDGE_VISIBILITY_SCOPES)
DOCUMENT_STATUS_SQL = ", ".join(f"'{item}'" for item in RECRUITMENT_KNOWLEDGE_DOCUMENT_STATUSES)
VERSION_STATUS_SQL = ", ".join(f"'{item}'" for item in RECRUITMENT_KNOWLEDGE_VERSION_STATUSES)
CHUNK_STATUS_SQL = ", ".join(f"'{item}'" for item in RECRUITMENT_KNOWLEDGE_CHUNK_STATUSES)
SOURCE_TYPE_SQL = ", ".join(f"'{item}'" for item in RECRUITMENT_KNOWLEDGE_SOURCE_TYPES)


class RecruitmentKnowledgeBase(Base):
    __tablename__ = "recruitment_knowledge_bases"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({BASE_STATUS_SQL})",
            name="ck_rkb_status",
        ),
        CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 120",
            name="ck_rkb_name",
        ),
        CheckConstraint(
            "description IS NULL OR length(description) <= 1000",
            name="ck_rkb_description",
        ),
        CheckConstraint(
            "resource_version >= 1",
            name="ck_rkb_resource_version",
        ),
        UniqueConstraint("name", name="uq_rkb_name"),
        Index("ix_rkb_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    resource_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    documents: Mapped[list[RecruitmentKnowledgeDocument]] = relationship(
        back_populates="knowledge_base",
        passive_deletes="all",
        order_by="RecruitmentKnowledgeDocument.updated_at.desc()",
    )


class RecruitmentKnowledgeDocument(Base):
    __tablename__ = "recruitment_knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({CATEGORY_SQL})",
            name="ck_rkd_category",
        ),
        CheckConstraint(
            f"visibility_scope IN ({VISIBILITY_SCOPE_SQL})",
            name="ck_rkd_visibility_scope",
        ),
        CheckConstraint(
            f"status IN ({DOCUMENT_STATUS_SQL})",
            name="ck_rkd_status",
        ),
        CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 200",
            name="ck_rkd_title",
        ),
        CheckConstraint(
            "summary IS NULL OR length(summary) <= 1000",
            name="ck_rkd_summary",
        ),
        CheckConstraint(
            "current_version_number IS NULL OR current_version_number >= 1",
            name="ck_rkd_current_version",
        ),
        CheckConstraint(
            "resource_version >= 1",
            name="ck_rkd_resource_version",
        ),
        UniqueConstraint(
            "knowledge_base_id",
            "title",
            name="uq_rkd_title",
        ),
        Index(
            "ix_rkd_base_category",
            "knowledge_base_id",
            "category",
        ),
        Index(
            "ix_rkd_scope_status",
            "visibility_scope",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_knowledge_bases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    visibility_scope: Mapped[str] = mapped_column(
        String(40), nullable=False, default="all_internal", server_default="all_internal"
    )
    related_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active", index=True
    )
    current_version_number: Mapped[int | None] = mapped_column(Integer)
    resource_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    knowledge_base: Mapped[RecruitmentKnowledgeBase] = relationship(back_populates="documents")
    related_job: Mapped[Job | None] = relationship(foreign_keys=[related_job_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    versions: Mapped[list[RecruitmentKnowledgeDocumentVersion]] = relationship(
        back_populates="document",
        order_by="RecruitmentKnowledgeDocumentVersion.version_number",
        passive_deletes="all",
    )
    chunks: Mapped[list[RecruitmentKnowledgeChunk]] = relationship(
        back_populates="document",
        passive_deletes="all",
        order_by="RecruitmentKnowledgeChunk.chunk_index",
    )

    @property
    def current_version(self) -> RecruitmentKnowledgeDocumentVersion | None:
        if self.current_version_number is None:
            return None
        for version in reversed(self.versions):
            if version.version_number == self.current_version_number:
                return version
        raise RuntimeError("招聘知识文档当前发布版本不存在")


class RecruitmentKnowledgeDocumentVersion(Base):
    __tablename__ = "recruitment_knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_rkdv_number",
        ),
        UniqueConstraint(
            "document_id",
            "idempotency_key",
            name="uq_rkdv_idempotency",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_rkdv_number",
        ),
        CheckConstraint(
            f"status IN ({VERSION_STATUS_SQL})",
            name="ck_rkdv_status",
        ),
        CheckConstraint(
            f"source_type IN ({SOURCE_TYPE_SQL})",
            name="ck_rkdv_source_type",
        ),
        CheckConstraint(
            "length(trim(change_note)) BETWEEN 1 AND 500",
            name="ck_rkdv_change_note",
        ),
        CheckConstraint(
            "length(trim(raw_text)) BETWEEN 1 AND 200000",
            name="ck_rkdv_raw_text",
        ),
        CheckConstraint(
            "parser_name IS NULL OR length(parser_name) <= 120",
            name="ck_rkdv_parser_name",
        ),
        CheckConstraint(
            "chunk_count >= 0",
            name="ck_rkdv_chunk_count",
        ),
        CheckConstraint(
            "published_at IS NULL OR status IN ('published', 'retired')",
            name="ck_rkdv_published_at",
        ),
        Index(
            "ix_rkdv_document_status",
            "document_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_knowledge_documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", index=True
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default="manual"
    )
    source_filename: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    mime_type: Mapped[str | None] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    change_note: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parser_name: Mapped[str | None] = mapped_column(String(120))
    parser_version: Mapped[str | None] = mapped_column(String(80))
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    published_by_username: Mapped[str | None] = mapped_column(String(64))
    published_by_display_name: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[RecruitmentKnowledgeDocument] = relationship(back_populates="versions")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    published_by: Mapped[User | None] = relationship(foreign_keys=[published_by_id])
    chunks: Mapped[list[RecruitmentKnowledgeChunk]] = relationship(
        back_populates="document_version",
        passive_deletes="all",
        order_by="RecruitmentKnowledgeChunk.chunk_index",
    )


class RecruitmentKnowledgeChunk(Base):
    __tablename__ = "recruitment_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            "embedding_model",
            "embedding_version",
            name="uq_rkc_version_index",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_rkc_index",
        ),
        CheckConstraint(
            "length(trim(chunk_text)) BETWEEN 1 AND 8000",
            name="ck_rkc_text",
        ),
        CheckConstraint(
            f"status IN ({CHUNK_STATUS_SQL})",
            name="ck_rkc_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_rkc_attempt_count",
        ),
        CheckConstraint(
            "embedding_dimension > 0",
            name="ck_rkc_dimension",
        ),
        CheckConstraint(
            "embedding IS NULL OR vector_dims(embedding) = embedding_dimension",
            name="ck_rkc_vector_dimension",
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_rkc_document_status",
            "document_id",
            "status",
        ),
        Index(
            "ix_rkc_model_status",
            "embedding_model",
            "embedding_version",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_knowledge_bases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_knowledge_documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recruitment_knowledge_document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_locator: Mapped[str | None] = mapped_column(String(200))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    task_id: Mapped[str | None] = mapped_column(String(120), index=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    document: Mapped[RecruitmentKnowledgeDocument] = relationship(back_populates="chunks")
    document_version: Mapped[RecruitmentKnowledgeDocumentVersion] = relationship(
        back_populates="chunks"
    )
    knowledge_base: Mapped[RecruitmentKnowledgeBase] = relationship()


class RecruitmentKnowledgeRetrievalLog(Base):
    __tablename__ = "recruitment_knowledge_retrieval_logs"
    __table_args__ = (
        CheckConstraint(
            "length(trim(scenario)) BETWEEN 1 AND 80",
            name="ck_rkrl_scenario",
        ),
        CheckConstraint(
            "query_summary IS NULL OR length(query_summary) <= 1000",
            name="ck_rkrl_query_summary",
        ),
        CheckConstraint(
            "limit_count >= 1 AND limit_count <= 20",
            name="ck_rkrl_limit",
        ),
        CheckConstraint(
            "returned_count >= 0 AND filtered_count >= 0",
            name="ck_rkrl_counts",
        ),
        Index(
            "ix_rkrl_scenario_created",
            "scenario",
            "created_at",
        ),
        Index(
            "ix_rkrl_resource",
            "resource_type",
            "resource_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_summary: Mapped[str | None] = mapped_column(Text)
    invoked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    prompt_template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_template_versions.id", ondelete="SET NULL"), index=True
    )
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)
    limit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    returned_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    filtered_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    invoked_by: Mapped[User | None] = relationship(foreign_keys=[invoked_by_id])
    prompt_template_version: Mapped[PromptTemplateVersion | None] = relationship(
        foreign_keys=[prompt_template_version_id]
    )


@event.listens_for(RecruitmentKnowledgeDocumentVersion, "before_update")
def _protect_recruitment_knowledge_version_update(
    _mapper: object,
    _connection: object,
    _target: RecruitmentKnowledgeDocumentVersion,
) -> None:
    allowed_lifecycle_fields = {
        "status",
        "published_by_id",
        "published_by_username",
        "published_by_display_name",
        "published_at",
    }
    state = inspect(_target)
    changed_fields = {
        attribute.key for attribute in state.attrs if attribute.history.has_changes()
    }
    forbidden_fields = changed_fields.difference(allowed_lifecycle_fields)
    if forbidden_fields:
        raise ValueError("招聘知识文档历史版本正文不可修改")


@event.listens_for(RecruitmentKnowledgeDocumentVersion, "before_delete")
def _protect_recruitment_knowledge_version_delete(
    _mapper: object,
    _connection: object,
    _target: RecruitmentKnowledgeDocumentVersion,
) -> None:
    raise ValueError("招聘知识文档历史版本不可删除")

