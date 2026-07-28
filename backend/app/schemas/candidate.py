import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.candidate_process import CandidateStage

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


class CandidateListItemResponse(CandidateSummaryResponse):
    pending_duplicate_count: int
    created_at: datetime
    updated_at: datetime


class CandidateListResponse(BaseModel):
    items: list[CandidateListItemResponse]
    total: int
    limit: int
    offset: int


class CandidateApplicationSummaryResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    job_status: Literal["active", "archived"]
    status: Literal["active", "merged"]
    merged_into_application_id: uuid.UUID | None
    current_stage: CandidateStage | None
    document_count: int
    created_at: datetime


class CandidateResumeSummaryResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID | None
    job_id: uuid.UUID
    job_title: str
    batch_id: uuid.UUID
    batch_name: str
    original_filename: str
    status: Literal["uploaded", "queued", "processing", "completed", "failed"]
    created_at: datetime


class CandidateDetailResponse(CandidateListItemResponse):
    applications: list[CandidateApplicationSummaryResponse]
    resumes: list[CandidateResumeSummaryResponse]


class CandidatePhoneUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("phone", "reason")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("手机号和修改原因不能为空")
        return normalized


class CandidatePhoneUpdateResponse(BaseModel):
    candidate_id: uuid.UUID
    phone: str
    revoked_portal_link_count: int


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
