import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CandidateStage = Literal[
    "unprocessed",
    "pending",
    "shortlisted",
    "to_contact",
    "contacted",
    "to_interview",
    "completed",
    "rejected",
    "offer_pending_response",
    "offer_rejected",
    "onboarding_pending_confirmation",
    "onboarding_pending_start",
    "onboarding_completed",
    "onboarding_abandoned",
]
CandidateProcessEventType = Literal["decision", "stage"]
InterviewEvaluationProgressStatus = Literal[
    "not_started",
    "in_progress",
    "completed",
    "cancelled",
]
InterviewEvaluationActionStatus = Literal["not_started", "draft", "submitted"]


class InterviewEvaluationProgressResponse(BaseModel):
    status: InterviewEvaluationProgressStatus
    total_rounds: int
    submitted_count: int
    draft_count: int
    pending_count: int
    cancelled_count: int
    action_round_id: uuid.UUID | None
    action_round_name: str | None
    action_evaluation_status: InterviewEvaluationActionStatus | None


class CandidateProcessOnboardingResponse(BaseModel):
    id: uuid.UUID
    status: Literal[
        "pending_confirmation",
        "candidate_proposed_date",
        "pending_start",
        "onboarded",
        "abandoned",
    ]


class CandidateProcessCardResponse(BaseModel):
    process_id: uuid.UUID | None
    application_id: uuid.UUID
    screening_result_id: uuid.UUID
    batch_id: uuid.UUID | None
    batch_name: str
    document_id: uuid.UUID
    candidate_code: str
    original_filename: str
    phone: str | None
    ai_group: Literal["passed", "low_match", "auto_rejected"]
    total_score: float
    current_decision: Literal["unprocessed", "shortlisted", "pending", "rejected"]
    current_stage: CandidateStage
    stage_entered_at: datetime
    skills: list[str]
    analysis_created_at: datetime
    interview_evaluation: InterviewEvaluationProgressResponse | None
    onboarding: CandidateProcessOnboardingResponse | None


class CandidateStageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_stage: CandidateStage
    target_stage: CandidateStage
    reason: str | None = Field(default=None, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CandidateStageUpdateResponse(BaseModel):
    process_id: uuid.UUID
    application_id: uuid.UUID
    document_id: uuid.UUID
    previous_stage: CandidateStage
    current_stage: CandidateStage
    stage_entered_at: datetime


class CandidateProcessTimelineEventResponse(BaseModel):
    event_type: CandidateProcessEventType
    from_stage: CandidateStage
    to_stage: CandidateStage
    reason: str | None
    operator_id: uuid.UUID | None
    operator_display_name: str
    created_at: datetime
