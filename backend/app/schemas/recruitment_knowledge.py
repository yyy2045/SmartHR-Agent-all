import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RecruitmentKnowledgeCategory = Literal[
    "policy",
    "job_standard",
    "interview",
    "offer",
    "compensation",
    "communication",
    "general",
]
RecruitmentKnowledgeVisibilityScope = Literal[
    "all_internal",
    "recruiter_manager",
    "recruiter_only",
    "admin_only",
]
RecruitmentKnowledgeDocumentStatus = Literal["active", "archived"]
RecruitmentKnowledgeVersionStatus = Literal["draft", "published", "retired"]
RecruitmentKnowledgeChunkStatus = Literal["pending", "processing", "completed", "failed"]


class RecruitmentKnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    summary: str | None
    category: RecruitmentKnowledgeCategory
    tags: list[str]
    visibility_scope: RecruitmentKnowledgeVisibilityScope
    related_job_id: uuid.UUID | None
    status: RecruitmentKnowledgeDocumentStatus
    current_version_number: int | None
    resource_version: int
    created_at: datetime
    updated_at: datetime


class RecruitmentKnowledgeVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    status: RecruitmentKnowledgeVersionStatus
    source_type: Literal["manual", "upload"]
    source_filename: str | None
    mime_type: str | None
    content_hash: str
    change_note: str
    parser_name: str | None
    parser_version: str | None
    chunk_count: int
    published_at: datetime | None
    created_at: datetime


class RecruitmentKnowledgeChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_index: int
    chunk_text: str
    heading_path: list[str]
    source_locator: str | None
    status: RecruitmentKnowledgeChunkStatus
    embedding_model: str
    embedding_dimension: int
    embedding_version: str
    attempt_count: int
    failure_code: str | None
    failure_message: str | None
    embedded_at: datetime | None
    updated_at: datetime


class RecruitmentKnowledgeRetrievalCitation(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    version_number: int
    category: RecruitmentKnowledgeCategory
    heading_path: list[str] = Field(default_factory=list)
    source_locator: str | None = None
    snippet: str
    score: float


class RecruitmentKnowledgeRetrievalResponse(BaseModel):
    query_hash: str
    returned_count: int
    filtered_count: int
    citations: list[RecruitmentKnowledgeRetrievalCitation]


class RecruitmentKnowledgeRetrievalRequest(BaseModel):
    scenario: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=4000)
    category: RecruitmentKnowledgeCategory | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=5, ge=1, le=20)
    resource_type: str | None = Field(default=None, max_length=80)
    resource_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None


class RecruitmentKnowledgeDocumentListItem(RecruitmentKnowledgeDocumentResponse):
    version_count: int
    current_source_type: Literal["manual", "upload"] | None = None
    current_source_filename: str | None = None
    chunk_count: int
    chunk_completed: int
    chunk_failed: int
    chunk_pending: int
    chunk_processing: int
    embedding_enabled: bool


class RecruitmentKnowledgeDocumentListResponse(BaseModel):
    total: int
    items: list[RecruitmentKnowledgeDocumentListItem]


class RecruitmentKnowledgeDocumentDetailResponse(RecruitmentKnowledgeDocumentResponse):
    versions: list[RecruitmentKnowledgeVersionResponse]
    raw_text: str | None
    source_type: Literal["manual", "upload"] | None = None
    source_filename: str | None = None
    mime_type: str | None = None
    parser_name: str | None = None
    current_chunks: list[RecruitmentKnowledgeChunkResponse]
    embedding_enabled: bool


class RecruitmentKnowledgeDocumentVersionCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=1000)
    category: RecruitmentKnowledgeCategory
    tags: list[str] = Field(default_factory=list, max_length=20)
    visibility_scope: RecruitmentKnowledgeVisibilityScope = "all_internal"
    related_job_id: uuid.UUID | None = None
    change_note: str = Field(min_length=1, max_length=500)
    raw_text: str = Field(min_length=1, max_length=200000)
    idempotency_key: uuid.UUID


class RecruitmentKnowledgeDocumentVersionCreateResponse(BaseModel):
    document: RecruitmentKnowledgeDocumentResponse
    version: RecruitmentKnowledgeVersionResponse
    chunk_count: int
    embedding_enabled: bool
    index_task_id: str | None
