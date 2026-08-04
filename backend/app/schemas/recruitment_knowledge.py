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


class RecruitmentKnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    status: Literal["active", "inactive"]
    resource_version: int
    created_at: datetime
    updated_at: datetime


class RecruitmentKnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    knowledge_base_id: uuid.UUID
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


class RecruitmentKnowledgeBaseListResponse(BaseModel):
    items: list[RecruitmentKnowledgeBaseResponse]


class RecruitmentKnowledgeDocumentVersionCreateRequest(BaseModel):
    knowledge_base_id: uuid.UUID | None = None
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
