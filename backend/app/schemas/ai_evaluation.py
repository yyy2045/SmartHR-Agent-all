from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AiEvaluationScenario = Literal[
    "resume_analysis",
    "candidate_qa",
    "interview_report",
    "offer_copy",
    "candidate_comparison",
]
AiEvaluationDatasetStatus = Literal["active", "archived"]
AiEvaluationSampleDifficulty = Literal["easy", "medium", "hard"]
AiEvaluationRunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
AiEvaluationResultStatus = Literal["passed", "failed", "error", "skipped"]
AiEvaluationErrorType = Literal[
    "wrong_recommendation",
    "evidence_missing",
    "hallucination",
    "format_error",
    "risk_omission",
    "timeout",
    "other",
]
AiEvaluationErrorSeverity = Literal["low", "medium", "high", "critical"]
AiEvaluationErrorStatus = Literal["open", "resolved", "ignored"]


class AiEvaluationDatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    scenario: AiEvaluationScenario
    description: str | None
    version_number: int
    status: AiEvaluationDatasetStatus
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class AiEvaluationSampleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    case_key: str
    title: str
    scenario: AiEvaluationScenario
    difficulty: AiEvaluationSampleDifficulty
    input_payload: dict[str, object]
    expected_output: dict[str, object]
    expected_recommendation: str | None
    expected_evidence_keywords: list[str]
    tags: list[str]
    is_active: bool
    created_at: datetime


class AiEvaluationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    scenario: AiEvaluationScenario
    status: AiEvaluationRunStatus
    provider: str
    model_name: str | None
    prompt_template_version_id: uuid.UUID | None
    prompt_version: str | None
    run_config: dict[str, object]
    metrics_summary: dict[str, object]
    total_samples: int
    completed_samples: int
    passed_samples: int
    failed_samples: int
    average_score: float | None
    duration_ms: int | None
    failure_code: str | None
    failure_message: str | None
    created_by_id: uuid.UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AiEvaluationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    sample_id: uuid.UUID
    status: AiEvaluationResultStatus
    score: float | None
    actual_output: dict[str, object]
    expected_snapshot: dict[str, object]
    error_types: list[AiEvaluationErrorType] = Field(default_factory=list)
    evidence_coverage_score: float | None
    format_valid: bool | None
    recommendation_matched: bool | None
    ai_call_log_id: uuid.UUID | None
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime


class AiEvaluationErrorCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    result_id: uuid.UUID
    dataset_id: uuid.UUID
    run_id: uuid.UUID
    sample_id: uuid.UUID
    error_type: AiEvaluationErrorType
    severity: AiEvaluationErrorSeverity
    status: AiEvaluationErrorStatus
    title: str
    description: str | None
    expected_behavior: str | None
    actual_behavior: str | None
    remediation_note: str | None
    created_by_id: uuid.UUID | None
    resolved_by_id: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AiEvaluationDatasetListResponse(BaseModel):
    items: list[AiEvaluationDatasetResponse]


class AiEvaluationRunCreateRequest(BaseModel):
    model_name: str = Field(default="deterministic-evaluator", min_length=1, max_length=200)
    prompt_version: str = Field(default="synthetic-baseline-v1", min_length=1, max_length=120)
    forced_error_case_keys: list[str] = Field(default_factory=list, max_length=20)


class AiEvaluationRunListResponse(BaseModel):
    total: int
    items: list[AiEvaluationRunResponse]


class AiEvaluationRunDetailResponse(BaseModel):
    run: AiEvaluationRunResponse
    results: list[AiEvaluationResultResponse]


class AiEvaluationErrorCaseListResponse(BaseModel):
    total: int
    items: list[AiEvaluationErrorCaseResponse]


class AiEvaluationErrorCaseUpdateRequest(BaseModel):
    status: AiEvaluationErrorStatus
    remediation_note: str | None = Field(default=None, max_length=4000)
