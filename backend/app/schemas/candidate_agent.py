import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CandidateAgentSessionStatus = Literal["active", "archived"]
CandidateAgentExchangeStatus = Literal["pending", "succeeded", "failed", "manual_fallback"]


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
