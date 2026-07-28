import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OnboardingStatus = Literal[
    "pending_confirmation",
    "candidate_proposed_date",
    "pending_start",
    "onboarded",
    "abandoned",
]
OnboardingActionOwner = Literal["candidate", "recruiter", "none"]
OnboardingAbandonmentSource = Literal[
    "candidate_withdrew",
    "company_cancelled",
    "other",
]
OnboardingAbandonmentReason = Literal[
    "compensation",
    "career",
    "location",
    "start_date",
    "personal",
    "position_cancelled",
    "business_change",
    "other",
]
OnboardingEventAction = Literal[
    "created",
    "candidate_confirmed_date",
    "candidate_proposed_date",
    "recruiter_accepted_date",
    "recruiter_proposed_date",
    "onboarded",
    "abandoned",
    "onboarded_corrected",
]


class OnboardingEventResponse(BaseModel):
    id: uuid.UUID
    sequence_number: int
    action: OnboardingEventAction
    from_status: OnboardingStatus | None
    to_status: OnboardingStatus
    date_before: date | None
    date_after: date | None
    reason: str | None
    actor_type: Literal["system", "candidate", "recruiter", "admin"]
    actor_username: str | None
    actor_display_name: str | None
    created_at: datetime


class CandidateOnboardingView(BaseModel):
    status: OnboardingStatus
    version: int
    action_owner: OnboardingActionOwner
    expected_start_date: date
    candidate_proposed_date: date | None
    recruiter_proposed_date: date | None
    confirmed_start_date: date | None
    actual_start_date: date | None
    abandonment_source: OnboardingAbandonmentSource | None
    abandonment_reason_code: OnboardingAbandonmentReason | None


class OnboardingSummaryResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    offer_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    candidate_id: uuid.UUID
    candidate_code: str
    candidate_name: str | None
    candidate_phone: str | None
    status: OnboardingStatus
    version: int
    action_owner: OnboardingActionOwner
    expected_start_date: date
    candidate_proposed_date: date | None
    recruiter_proposed_date: date | None
    confirmed_start_date: date | None
    actual_start_date: date | None
    abandonment_source: OnboardingAbandonmentSource | None
    abandonment_reason_code: OnboardingAbandonmentReason | None
    updated_at: datetime


class OnboardingDetailResponse(OnboardingSummaryResponse):
    abandonment_note: str | None
    events: list[OnboardingEventResponse]


class OnboardingListResponse(BaseModel):
    items: list[OnboardingSummaryResponse]
    total: int
    page: int
    page_size: int


class IdempotentOnboardingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID
    version: int = Field(ge=1)


class PortalOnboardingConfirmDateRequest(IdempotentOnboardingRequest):
    token: str = Field(min_length=32, max_length=256)
    verification_token: str = Field(min_length=32, max_length=256)
    start_date: date

    @field_validator("token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 32:
            raise ValueError("候选人链接令牌格式不正确")
        return normalized


class PortalOnboardingProposeDateRequest(PortalOnboardingConfirmDateRequest):
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PortalOnboardingAbandonRequest(IdempotentOnboardingRequest):
    token: str = Field(min_length=32, max_length=256)
    verification_token: str = Field(min_length=32, max_length=256)
    reason_code: OnboardingAbandonmentReason
    note: str = Field(min_length=1, max_length=2_000)

    @field_validator("token", "note")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized


class OnboardingDateDecisionRequest(IdempotentOnboardingRequest):
    decision: Literal["accept", "propose"]
    proposed_date: date | None = None
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_decision_fields(self) -> "OnboardingDateDecisionRequest":
        if self.decision == "accept" and self.proposed_date is not None:
            raise ValueError("接受候选人日期时不能另填日期")
        if self.decision == "propose" and self.proposed_date is None:
            raise ValueError("提出新日期时必须填写日期")
        return self


class OnboardingOnboardRequest(IdempotentOnboardingRequest):
    actual_start_date: date
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class OnboardingAbandonRequest(IdempotentOnboardingRequest):
    source: OnboardingAbandonmentSource
    reason_code: OnboardingAbandonmentReason
    note: str = Field(min_length=1, max_length=2_000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("放弃入职时必须填写说明")
        return normalized


class OnboardingCorrectionRequest(IdempotentOnboardingRequest):
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("更正已入职状态时必须填写原因")
        return normalized
