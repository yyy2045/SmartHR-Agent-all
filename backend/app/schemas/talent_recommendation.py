import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TalentRecommendationRunStatus = Literal[
    "queued",
    "retrieving",
    "rescoring",
    "completed",
    "partial",
    "failed",
    "cancelled",
]
TalentRecommendationResultStatus = Literal[
    "retrieved",
    "rescoring",
    "completed",
    "failed",
    "excluded",
]
TalentRecommendationAction = Literal["cancel", "retry_failed_items"]


class TalentRecommendationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    ai_input_mode: Literal["raw", "redacted"] = "raw"
    idempotency_key: uuid.UUID

    @field_validator("group_ids")
    @classmethod
    def unique_group_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("同一推荐任务不能重复选择人才组")
        return value


class TalentRecommendationActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    idempotency_key: uuid.UUID


class TalentRecommendationGroupSnapshotResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    group_version: int


class TalentRecommendationRunResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    criteria_version_id: uuid.UUID
    criteria_version_number: int
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    status: TalentRecommendationRunStatus
    ai_input_mode: Literal["raw", "redacted"]
    recall_limit: int
    rescore_limit: int
    scope_candidate_count: int
    retrieved_count: int
    rescored_count: int
    completed_count: int
    failed_count: int
    excluded_count: int
    criteria_stale: bool
    criteria_stale_at: datetime | None
    failure_code: str | None
    failure_summary: str | None
    resource_version: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    groups: list[TalentRecommendationGroupSnapshotResponse]
    allowed_actions: list[TalentRecommendationAction]


class TalentRecommendationCreateResponse(BaseModel):
    run: TalentRecommendationRunResponse
    replayed: bool
    reused_active_run: bool


class TalentRecommendationRunListResponse(BaseModel):
    items: list[TalentRecommendationRunResponse]
    total: int
    limit: int
    offset: int


class TalentRecommendationResultResponse(BaseModel):
    id: uuid.UUID
    candidate_id: uuid.UUID
    resolved_candidate_id: uuid.UUID
    candidate_code: str
    candidate_name: str | None
    candidate_merged_at: datetime | None
    document_id: uuid.UUID
    candidate_profile_id: uuid.UUID
    profile_version: int
    vector_rank: int
    similarity_score: Decimal
    matched_group_ids: list[str]
    matched_chunks: list[dict[str, object]]
    status: TalentRecommendationResultStatus
    ai_score: Decimal | None
    ai_group: Literal["passed", "low_match", "auto_rejected"] | None
    ai_dimension_scores: list[dict[str, object]]
    ai_hard_requirement_results: list[dict[str, object]]
    ai_strengths: list[str]
    ai_gaps: list[str]
    ai_missing_items: list[str]
    ai_interview_questions: list[str]
    ai_evidence: list[dict[str, object]]
    processing_attempt_count: int
    failure_code: str | None
    failure_message: str | None
    exclusion_code: str | None
    exclusion_reason: str | None
    document_stale: bool
    profile_stale: bool
    embedding_stale: bool
    stale_at: datetime | None
    completed_at: datetime | None


class TalentRecommendationRunDetailResponse(TalentRecommendationRunResponse):
    results: list[TalentRecommendationResultResponse]
