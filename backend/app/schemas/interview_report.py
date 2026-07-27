import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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
