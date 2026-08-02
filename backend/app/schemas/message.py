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
CommunicationContextType = Literal["interview_round", "offer", "onboarding"]
CommunicationChannel = Literal["wechat", "phone", "sms", "email", "other"]
CommunicationRecordKind = Literal["sent", "correction"]
CommunicationAction = Literal["copy", "record_send", "correct"]

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

class CommunicationRecordCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_type: CommunicationContextType
    context_id: uuid.UUID
    template_version_id: uuid.UUID | None = None
    channel: CommunicationChannel
    channel_detail: str | None = Field(default=None, min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10_000)
    sent_at: datetime
    is_historical: bool = False
    historical_note: str | None = Field(default=None, min_length=1, max_length=2_000)
    idempotency_key: uuid.UUID

    @field_validator("channel_detail", "historical_note")
    @classmethod
    def normalize_optional_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_text(value, detail="沟通说明不能为空")

    @field_validator("subject", "body")
    @classmethod
    def normalize_record_text(cls, value: str) -> str:
        return _normalized_text(value, detail="沟通文案不能为空")


class CommunicationCorrectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_version_id: uuid.UUID | None = None
    channel: CommunicationChannel
    channel_detail: str | None = Field(default=None, min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10_000)
    sent_at: datetime
    correction_reason: str = Field(min_length=1, max_length=2_000)
    idempotency_key: uuid.UUID

    @field_validator("channel_detail")
    @classmethod
    def normalize_channel_detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_text(value, detail="渠道说明不能为空")

    @field_validator("subject", "body")
    @classmethod
    def normalize_record_text(cls, value: str) -> str:
        return _normalized_text(value, detail="沟通文案不能为空")

    @field_validator("correction_reason")
    @classmethod
    def normalize_correction_reason(cls, value: str) -> str:
        return _normalized_text(value, detail="更正原因不能为空")


class CommunicationCopyAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_type: CommunicationContextType
    context_id: uuid.UUID
    template_version_id: uuid.UUID | None = None
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10_000)
    idempotency_key: uuid.UUID

    @field_validator("subject", "body")
    @classmethod
    def normalize_copied_text(cls, value: str) -> str:
        return _normalized_text(value, detail="复制文案不能为空")


class CommunicationRecordResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    context_type: CommunicationContextType
    context_id: uuid.UUID
    template_version_id: uuid.UUID | None
    record_kind: CommunicationRecordKind
    root_record_id: uuid.UUID | None
    corrects_record_id: uuid.UUID | None
    correction_sequence: int
    correction_reason: str | None
    channel: CommunicationChannel
    channel_detail: str | None
    recipient_type: Literal["phone", "email", "other"]
    recipient_masked: str
    candidate_name_snapshot: str
    subject_snapshot: str
    body_snapshot: str
    sent_at: datetime
    is_historical: bool
    historical_note: str | None
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    created_at: datetime
    allowed_actions: list[CommunicationAction]


class CommunicationRecordSummaryResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    context_type: CommunicationContextType
    context_id: uuid.UUID
    record_kind: CommunicationRecordKind
    channel: CommunicationChannel
    channel_detail: str | None
    recipient_masked: str
    candidate_name_snapshot: str
    subject_snapshot: str
    sent_at: datetime
    correction_count: int
    latest_correction_id: uuid.UUID | None
    allowed_actions: list[CommunicationAction]


class CommunicationRecordListResponse(BaseModel):
    items: list[CommunicationRecordSummaryResponse]
    total: int
    limit: int
    offset: int


class CommunicationRecordDetailResponse(CommunicationRecordResponse):
    corrections: list[CommunicationRecordResponse]


class CommunicationCopyAuditResponse(BaseModel):
    audit_id: uuid.UUID
    context_type: CommunicationContextType
    context_id: uuid.UUID
    template_version_id: uuid.UUID | None
    copied_at: datetime

class CommunicationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_version_id: uuid.UUID
    context_type: CommunicationContextType
    context_id: uuid.UUID
    subject_override: str | None = Field(default=None, min_length=1, max_length=100)
    body_override: str | None = Field(default=None, min_length=1, max_length=5_000)

    @field_validator("subject_override", "body_override")
    @classmethod
    def normalize_optional_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalized_text(value, detail="人工修改后的文案不能为空")


class CommunicationPreviewResponse(BaseModel):
    template_id: uuid.UUID
    template_version_id: uuid.UUID
    template_type: MessageTemplateType
    context_type: CommunicationContextType
    context_id: uuid.UUID
    subject: str
    body: str
    variables_used: list[str]
    resolved_variables: dict[str, str]
    missing_optional_variables: list[str]
