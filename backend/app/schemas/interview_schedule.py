import uuid
from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InterviewMethod = Literal["onsite", "online", "phone"]
InterviewScheduleStatus = Literal["scheduled", "partially_cancelled", "cancelled"]
InterviewScheduleRoundStatus = Literal["scheduled", "rescheduled", "cancelled"]


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_arrangement(
    method: InterviewMethod,
    location: str | None,
    meeting_url: str | None,
) -> None:
    if method == "onsite" and location is None:
        raise ValueError("线下面试必须填写地点")
    if method == "onsite" and meeting_url is not None:
        raise ValueError("线下面试不能填写会议链接")
    if method == "online":
        if meeting_url is None:
            raise ValueError("在线面试必须填写会议链接")
        if location is not None:
            raise ValueError("在线面试不能填写线下地点")
        parsed = urlparse(meeting_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("会议链接必须是有效的 HTTP 或 HTTPS 地址")
    if method == "phone" and (location is not None or meeting_url is not None):
        raise ValueError("电话面试不需要填写地点或会议链接")


class InterviewScheduleRoundArrangement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_start_at: datetime
    interview_method: InterviewMethod
    location: str | None = Field(default=None, max_length=500)
    meeting_url: str | None = Field(default=None, max_length=2_000)

    @field_validator("scheduled_start_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("面试时间必须包含时区")
        return value

    @field_validator("location", "meeting_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional(value)

    @model_validator(mode="after")
    def validate_method_fields(self) -> Self:
        _validate_arrangement(self.interview_method, self.location, self.meeting_url)
        return self


class InterviewScheduleRoundCreate(InterviewScheduleRoundArrangement):
    plan_round_id: uuid.UUID


class InterviewScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_version_id: uuid.UUID
    rounds: list[InterviewScheduleRoundCreate] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_unique_rounds(self) -> Self:
        round_ids = [item.plan_round_id for item in self.rounds]
        if len(round_ids) != len(set(round_ids)):
            raise ValueError("面试轮次不能重复")
        return self


class InterviewRoundReschedule(InterviewScheduleRoundArrangement):
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("改期原因不能为空")
        return value


class InterviewRoundCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("取消原因不能为空")
        return value


class InterviewScheduleRoundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_round_id: uuid.UUID
    name: str
    round_type: str
    duration_minutes: int
    sort_order: int
    scheduled_start_at: datetime
    interview_method: InterviewMethod
    location: str | None
    meeting_url: str | None
    status: InterviewScheduleRoundStatus
    reschedule_count: int
    last_change_reason: str | None
    updated_by_id: uuid.UUID | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InterviewScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    document_id: uuid.UUID
    candidate_code: str
    plan_version_id: uuid.UUID
    plan_version_number: int
    status: InterviewScheduleStatus
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    rounds: list[InterviewScheduleRoundResponse]
