import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MessageTemplateType = Literal[
    "interview_invitation",
    "interview_reschedule",
    "interview_cancellation",
    "meeting_details",
    "offer_notification",
    "offer_reminder",
    "onboarding_date_confirmation",
]
MessageTemplateStatus = Literal["active", "inactive"]
MessageTemplateAction = Literal["create_version", "activate", "deactivate"]

_VARIABLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _normalized_text(value: str, *, detail: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(detail)
    return normalized


class MessageTemplateContent(BaseModel):
    subject: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=5_000)
    variables: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str) -> str:
        return _normalized_text(value, detail="模板标题不能为空")

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        return _normalized_text(value, detail="模板正文不能为空")

    @field_validator("variables")
    @classmethod
    def validate_variables(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("模板变量不能重复")
        if any(not _VARIABLE_PATTERN.fullmatch(item) for item in value):
            raise ValueError("模板变量必须使用小写字母、数字和下划线")
        return value


class MessageTemplateCreateRequest(MessageTemplateContent):
    model_config = ConfigDict(extra="forbid")

    template_type: MessageTemplateType
    name: str = Field(min_length=1, max_length=100)
    idempotency_key: uuid.UUID

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _normalized_text(value, detail="模板名称不能为空")


class MessageTemplateVersionCreateRequest(MessageTemplateContent):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    idempotency_key: uuid.UUID


class MessageTemplateStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    idempotency_key: uuid.UUID


class MessageTemplateVersionResponse(BaseModel):
    id: uuid.UUID
    version_number: int
    source_version_id: uuid.UUID | None
    subject: str
    body: str
    variables: list[str]
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    created_at: datetime


class MessageTemplateSummaryResponse(BaseModel):
    id: uuid.UUID
    system_key: str | None
    template_type: MessageTemplateType
    name: str
    status: MessageTemplateStatus
    current_version_number: int
    resource_version: int
    current_subject: str
    updated_at: datetime
    allowed_actions: list[MessageTemplateAction]


class MessageTemplateResponse(MessageTemplateSummaryResponse):
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    created_at: datetime
    current_version: MessageTemplateVersionResponse
    versions: list[MessageTemplateVersionResponse]


class MessageTemplateListResponse(BaseModel):
    items: list[MessageTemplateSummaryResponse]
    total: int
    limit: int
    offset: int
