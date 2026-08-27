import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CandidateAgentSessionStatus = Literal["active", "archived"]
CandidateAgentExchangeStatus = Literal["pending", "succeeded", "failed", "manual_fallback"]
CandidateAgentReportStatus = Literal["pending", "succeeded", "manual_fallback"]
CandidateAgentRecommendation = Literal["hire", "next_round", "reserve", "reject"]


class CandidateAgentSessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)


class CandidateAgentSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    application_id: uuid.UUID
    title: str | None
    status: CandidateAgentSessionStatus
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CandidateAgentEvidenceReference(BaseModel):
    source_type: str = Field(min_length=1, max_length=80)
    source_id: uuid.UUID | None = None
    source_label: str = Field(min_length=1, max_length=200)
    quote: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, object] = Field(default_factory=dict)


class CandidateAgentKnowledgeCitation(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str = Field(min_length=1, max_length=200)
    snippet: str = Field(min_length=1, max_length=1000)
    score: float | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CandidateAgentExchangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    sequence_number: int
    idempotency_key: uuid.UUID
    status: CandidateAgentExchangeStatus
    question: str
    answer: str | None
    evidence_snapshot: dict[str, object]
    evidence_references: list[dict[str, object]]
    knowledge_citations: list[dict[str, object]]
    ai_call_log_id: uuid.UUID | None
    prompt_template_version_id: uuid.UUID | None
    model_name: str | None
    prompt_version: str | None
    failure_code: str | None
    failure_message: str | None
    created_by_id: uuid.UUID | None
    created_at: datetime


class CandidateAgentSessionDetailResponse(CandidateAgentSessionResponse):
    exchanges: list[CandidateAgentExchangeResponse]


class CandidateAgentAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    idempotency_key: uuid.UUID


class CandidateAgentAnswerDraft(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)
    evidence_references: list[CandidateAgentEvidenceReference] = Field(
        default_factory=list,
        max_length=12,
    )
    knowledge_citations: list[CandidateAgentKnowledgeCitation] = Field(
        default_factory=list,
        max_length=8,
    )
    limitations: list[str] = Field(default_factory=list, max_length=8)
    suggested_follow_up_questions: list[str] = Field(default_factory=list, max_length=6)


class CandidateAgentReportAIDraft(BaseModel):
    match_assessment: str = Field(min_length=1, max_length=4000)
    strengths: list[str] = Field(default_factory=list, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=12)
    contradictions: list[str] = Field(default_factory=list, max_length=8)
    evidence_gaps: list[str] = Field(default_factory=list, max_length=8)
    next_step_suggestions: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=8)
    overall_recommendation: CandidateAgentRecommendation | None = None
    evidence_references: list[CandidateAgentEvidenceReference] = Field(
        default_factory=list,
        max_length=20,
    )
    knowledge_citations: list[CandidateAgentKnowledgeCitation] = Field(
        default_factory=list,
        max_length=10,
    )


class CandidateAgentReportGenerateRequest(BaseModel):
    idempotency_key: uuid.UUID


class CandidateAgentToolResultSchema(BaseModel):
    name: str
    step: int
    status: str
    duration_ms: int | None = None
    request_snapshot: dict[str, object] | None = None
    result_snapshot: dict[str, object] | None = None
    error: str | None = None


class CandidateAgentReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    status: CandidateAgentReportStatus
    match_assessment: str | None
    strengths: list[str]
    risks: list[str]
    contradictions: list[str]
    evidence_gaps: list[str]
    next_step_suggestions: list[str]
    open_questions: list[str]
    overall_recommendation: str | None
    evidence_references: list[dict[str, object]]
    knowledge_citations: list[dict[str, object]]
    tool_trajectory: list[CandidateAgentToolResultSchema]
    ai_call_log_ids: list[str]
    prompt_template_version_id: uuid.UUID | None
    model_name: str | None
    prompt_version: str | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime
