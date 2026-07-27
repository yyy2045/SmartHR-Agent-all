import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

InterviewReportConclusion = Literal["hire", "next_round", "reserve", "reject"]


class InterviewReportContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conclusion: InterviewReportConclusion | None = None
    executive_summary: str = Field(default="", max_length=5_000)
    strengths: list[str] = Field(default_factory=list, max_length=20)
    concerns: list[str] = Field(default_factory=list, max_length=20)
    follow_up_actions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("executive_summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        return value.strip()

    @field_validator("strengths", "concerns", "follow_up_actions")
    @classmethod
    def normalize_items(cls, values: list[str]) -> list[str]:
        normalized = [item.strip() for item in values]
        if any(not item for item in normalized):
            raise ValueError("报告列表项不能为空")
        if any(len(item) > 1_000 for item in normalized):
            raise ValueError("报告列表项不能超过 1000 个字符")
        return normalized


class InterviewReportAIDraft(InterviewReportContent):
    conclusion: InterviewReportConclusion
    executive_summary: str = Field(min_length=1, max_length=5_000)


class InterviewReportCreateRequest(InterviewReportContent):
    idempotency_key: uuid.UUID


class InterviewReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID


class InterviewReportUpdateRequest(InterviewReportContent):
    idempotency_key: uuid.UUID
    source_version_id: uuid.UUID


class InterviewReportConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID


class ReportScreeningCitationResponse(BaseModel):
    id: uuid.UUID
    subject_type: str
    subject_key: str
    quote: str
    source_type: str
    page_number: int | None
    paragraph_index: int | None


class ReportScreeningEvidenceResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    criteria_version_id: uuid.UUID
    analysis_version: int
    ai_group: Literal["passed", "low_match", "auto_rejected"] | None
    total_score: float | None
    pass_threshold: int
    current_decision: Literal["unprocessed", "shortlisted", "pending", "rejected"]
    strengths: list[str]
    gaps: list[str]
    missing_items: list[str]
    completed_at: datetime | None
    citations: list[ReportScreeningCitationResponse]


class ReportQuestionEvidenceResponse(BaseModel):
    question_id: uuid.UUID
    question_text: str
    answer_summary: str
    evidence: str


class ReportDimensionEvidenceResponse(BaseModel):
    dimension_id: uuid.UUID
    dimension_name: str
    score: int | None
    evidence: str


class ReportSubmittedEvaluationResponse(BaseModel):
    evaluation_id: uuid.UUID
    round_id: uuid.UUID
    round_name: str
    round_type: str
    sort_order: int
    total_score: float | None
    passed: bool | None
    overall_recommendation: str
    overall_comment: str
    submitted_at: datetime
    question_responses: list[ReportQuestionEvidenceResponse]
    dimension_ratings: list[ReportDimensionEvidenceResponse]


class ReportMissingRoundResponse(BaseModel):
    round_id: uuid.UUID
    round_name: str
    round_type: str
    sort_order: int
    round_status: Literal["scheduled", "rescheduled", "cancelled"]
    reason: Literal["not_submitted", "cancelled"]


class InterviewReportContextResponse(BaseModel):
    application_id: uuid.UUID
    application_status: Literal["active", "merged"]
    job_id: uuid.UUID
    job_title: str
    candidate_id: uuid.UUID
    candidate_code: str
    candidate_name: str | None
    latest_screening: ReportScreeningEvidenceResponse | None
    submitted_evaluations: list[ReportSubmittedEvaluationResponse]
    missing_rounds: list[ReportMissingRoundResponse]


class InterviewReportVersionResponse(InterviewReportContent):
    id: uuid.UUID
    version_number: int
    source_version_id: uuid.UUID | None
    generation_mode: Literal["ai", "manual"]
    screening_result_id: uuid.UUID | None
    evaluation_ids: list[uuid.UUID]
    evidence_snapshot: InterviewReportContextResponse
    missing_rounds: list[ReportMissingRoundResponse]
    model_name: str | None
    prompt_version: str | None
    ai_failure_code: str | None
    ai_failure_message: str | None
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    created_at: datetime


class InterviewReportResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    application_status: Literal["active", "merged"]
    job_id: uuid.UUID
    job_title: str
    candidate_id: uuid.UUID
    candidate_code: str
    candidate_name: str | None
    status: Literal["draft", "confirmed"]
    current_version_number: int
    confirmed_by_id: uuid.UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    versions: list[InterviewReportVersionResponse]
