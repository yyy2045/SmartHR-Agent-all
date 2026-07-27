import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DuplicateConfidence = Literal["strong", "weak"]
DuplicateReviewStatus = Literal["pending", "not_duplicate", "merged"]


class CandidateSummaryResponse(BaseModel):
    id: uuid.UUID
    candidate_code: str
    full_name: str | None
    phone: str | None
    email: str | None
    status: Literal["active", "merged"]
    merged_into_candidate_id: uuid.UUID | None
    application_count: int
    resume_count: int


class CandidateDuplicateReviewResponse(BaseModel):
    id: uuid.UUID
    candidate_a: CandidateSummaryResponse
    candidate_b: CandidateSummaryResponse
    source_document_id: uuid.UUID | None
    confidence: DuplicateConfidence
    signals: list[str]
    status: DuplicateReviewStatus
    resolved_by_id: uuid.UUID | None
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CandidateDuplicateResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("处理原因不能为空")
        return normalized


class CandidateMergeRequest(CandidateDuplicateResolutionRequest):
    target_candidate_id: uuid.UUID


class CandidateMergeResponse(BaseModel):
    review: CandidateDuplicateReviewResponse
    target_candidate: CandidateSummaryResponse
    merged_candidate: CandidateSummaryResponse
    moved_application_ids: list[uuid.UUID]
    merged_application_ids: list[uuid.UUID]
    moved_document_count: int
