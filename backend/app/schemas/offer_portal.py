import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PortalLinkState = Literal["active", "expired", "revoked", "responded"]
CandidateOfferDecision = Literal["accepted", "rejected"]
CandidateRejectionReason = Literal[
    "compensation",
    "career",
    "location",
    "timing",
    "other",
]


class OfferPortalLinkCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID


class OfferPortalLinkRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID
    revocation_idempotency_key: uuid.UUID
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("重新生成链接时必须填写原因")
        return normalized


class OfferPortalLinkRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("撤回链接时必须填写原因")
        return normalized


class OfferPortalLinkResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    state: PortalLinkState
    expires_at: datetime
    created_by_username: str
    created_by_display_name: str
    created_at: datetime
    revoked_at: datetime | None
    revoked_by_username: str | None
    revoked_by_display_name: str | None
    revocation_reason: str | None


class OfferPortalLinkIssuedResponse(OfferPortalLinkResponse):
    portal_token: str | None


class OfferPortalTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=256)

    @field_validator("token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 32:
            raise ValueError("候选人链接令牌格式不正确")
        return normalized


class OfferPortalVerifyRequest(OfferPortalTokenRequest):
    phone_last_four: str = Field(pattern=r"^[0-9]{4}$")


class OfferPortalDetailRequest(OfferPortalTokenRequest):
    verification_token: str = Field(min_length=32, max_length=256)


class OfferPortalStatusResponse(BaseModel):
    status: Literal["verification_required"]


class CandidateOfferResponse(BaseModel):
    decision: CandidateOfferDecision
    rejection_reason_code: CandidateRejectionReason | None
    rejection_note: str | None
    responded_at: datetime


class CandidateOfferView(BaseModel):
    candidate_name: str | None
    job_title: str
    progress: Literal["offer_pending_response", "accepted", "declined"]
    currency: Literal["CNY"]
    monthly_salary: Decimal
    annual_salary_months: Decimal
    probation_months: int
    probation_monthly_salary: Decimal | None
    bonus_description: str
    expected_start_date: date
    valid_until: date
    notes: str
    response: CandidateOfferResponse | None


class OfferPortalVerifiedResponse(CandidateOfferView):
    verification_token: str
    verification_expires_at: datetime
