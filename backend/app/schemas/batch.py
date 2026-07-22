import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    has_original_file: bool
    extraction_method: str | None
    segment_count: int
    text_character_count: int
    candidate_code: str
    redaction_count: int
    status: DocumentStatus
    failure_code: str | None
    failure_message: str | None
    attempt_count: int
    processing_attempt_count: int
    processing_started_at: datetime | None
    parsed_at: datetime | None
    redacted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ResumeTextSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    segment_key: str
    source_type: Literal["pdf_page", "docx_paragraph", "image_ocr"]
    source_index: int
    page_number: int | None
    paragraph_index: int | None
    raw_text: str
    normalized_text: str
    redacted_text: str | None
    ocr_confidence: float | None
    sort_order: int


class ResumeDocumentDetailResponse(ResumeDocumentResponse):
    text_segments: list[ResumeTextSegmentResponse]


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


class BatchDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(min_length=1, max_length=200)


class BatchDeletionResponse(BaseModel):
    status: Literal["deleted", "cleanup_pending"]
    batch_id: uuid.UUID
    deleted_document_count: int
    deleted_file_count: int
    message: str | None = None
