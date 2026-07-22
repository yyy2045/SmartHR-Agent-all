import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

BatchStatus = Literal[
    "uploading",
    "ready",
    "partial_failure",
    "failed",
    "processing",
    "completed",
]
DocumentStatus = Literal["uploaded", "queued", "processing", "completed", "failed"]


class ResumeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_id: uuid.UUID
    original_filename: str
    file_extension: str
    content_type: str
    detected_type: str
    size_bytes: int
    sha256: str | None
    status: DocumentStatus
    failure_code: str | None
    failure_message: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime


class ScreeningBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    criteria_version_id: uuid.UUID
    criteria_version_number: int
    name: str
    status: BatchStatus
    total_count: int
    success_count: int
    failed_count: int
    processing_count: int
    created_at: datetime
    updated_at: datetime
    documents: list[ResumeDocumentResponse]
