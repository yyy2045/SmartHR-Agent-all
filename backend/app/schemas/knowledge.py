import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

KnowledgeIndexStatus = Literal[
    "not_indexed",
    "pending",
    "processing",
    "completed",
    "partial_failure",
    "failed",
]


class KnowledgeChunkStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_type: str
    chunk_index: int
    source_segment_keys: list[str]
    status: str
    embedding_model: str
    embedding_dimension: int
    embedding_version: str
    attempt_count: int
    failure_code: str | None
    failure_message: str | None
    embedded_at: datetime | None
    updated_at: datetime


class KnowledgeIndexStatusResponse(BaseModel):
    document_id: uuid.UUID
    candidate_profile_id: uuid.UUID
    profile_version: int
    status: KnowledgeIndexStatus
    embedding_enabled: bool
    embedding_model: str
    embedding_dimension: int
    embedding_version: str
    chunk_count: int
    completed_count: int
    failed_count: int
    chunks: list[KnowledgeChunkStatusResponse]


class KnowledgeIndexTaskResponse(BaseModel):
    status: Literal["queued"]
    document_id: uuid.UUID
    candidate_profile_id: uuid.UUID
    profile_version: int
    task_id: str
