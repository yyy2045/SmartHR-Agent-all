import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AiTaskStatus = Literal["queued", "running", "succeeded", "failed", "retrying", "cancelled"]
AiCallStatus = Literal["succeeded", "failed"]


class AiObservabilityCount(BaseModel):
    key: str
    count: int


class AiObservabilitySummaryResponse(BaseModel):
    task_total: int
    call_total: int
    failed_task_count: int
    failed_call_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    avg_task_duration_ms: int | None
    avg_call_duration_ms: int | None
    task_status_counts: list[AiObservabilityCount]
    call_status_counts: list[AiObservabilityCount]
    call_scenario_counts: list[AiObservabilityCount]


class AiTaskRecord(BaseModel):
    id: uuid.UUID
    celery_task_id: str | None
    task_name: str
    scenario: str
    status: AiTaskStatus
    attempt_count: int
    max_retries: int
    resource_type: str | None
    resource_id: uuid.UUID | None
    job_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    document_id: uuid.UUID | None
    application_id: uuid.UUID | None
    candidate_profile_id: uuid.UUID | None
    failure_code: str | None
    failure_message: str | None
    duration_ms: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class AiTaskListResponse(BaseModel):
    items: list[AiTaskRecord]
    total: int
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AiCallLogRecord(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID | None
    scenario: str
    status: AiCallStatus
    model_name: str | None
    prompt_version: str | None
    prompt_template_version_id: uuid.UUID | None
    provider: str
    retry_count: int
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    resource_type: str | None
    resource_id: uuid.UUID | None
    job_id: uuid.UUID | None
    batch_id: uuid.UUID | None
    document_id: uuid.UUID | None
    application_id: uuid.UUID | None
    candidate_profile_id: uuid.UUID | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime


class AiCallLogListResponse(BaseModel):
    items: list[AiCallLogRecord]
    total: int
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
