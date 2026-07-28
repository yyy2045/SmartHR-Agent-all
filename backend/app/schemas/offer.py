import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OfferStatus = Literal[
    "draft",
    "pending_manager_confirmation",
    "pending_approval",
    "approved",
    "rejected",
    "pending_response",
    "accepted",
    "declined",
]
class OfferContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_salary: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    annual_salary_months: Decimal = Field(
        ge=1,
        le=36,
        max_digits=4,
        decimal_places=2,
    )
    probation_months: int = Field(ge=0, le=12)
    probation_monthly_salary: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    bonus_description: str = Field(default="", max_length=5_000)
    expected_start_date: date
    valid_until: date
    notes: str = Field(default="", max_length=5_000)

    @field_validator("bonus_description", "notes")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_probation_salary(self) -> Self:
        if self.probation_months == 0 and self.probation_monthly_salary is not None:
            raise ValueError("无试用期时不能填写试用期月薪")
        if self.probation_months > 0 and self.probation_monthly_salary is None:
            raise ValueError("有试用期时必须填写试用期月薪")
        return self


class OfferCreateRequest(OfferContent):
    idempotency_key: uuid.UUID


class OfferVersionCreateRequest(OfferContent):
    idempotency_key: uuid.UUID
    source_version_id: uuid.UUID


class OfferSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID
    version_id: uuid.UUID


class OfferManagerDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID
    version_id: uuid.UUID
    decision: Literal["confirmed", "rejected"]
    comment: str = Field(default="", max_length=5_000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_rejection_comment(self) -> Self:
        if self.decision == "rejected" and not self.comment:
            raise ValueError("驳回时必须填写原因")
        return self


class OfferApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: uuid.UUID
    version_id: uuid.UUID
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=5_000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_rejection_comment(self) -> Self:
        if self.decision == "rejected" and not self.comment:
            raise ValueError("驳回时必须填写原因")
        return self


class OfferManagerConfirmationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idempotency_key: uuid.UUID
    confirmer_id: uuid.UUID | None
    confirmer_username: str
    confirmer_display_name: str
    decision: Literal["confirmed", "rejected"]
    comment: str
    decided_at: datetime


class OfferApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idempotency_key: uuid.UUID
    approver_id: uuid.UUID | None
    approver_username: str
    approver_display_name: str
    decision: Literal["approved", "rejected"]
    comment: str
    decided_at: datetime


class OfferVersionResponse(OfferContent):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    idempotency_key: uuid.UUID
    submission_idempotency_key: uuid.UUID | None
    submitted_at: datetime | None
    source_version_id: uuid.UUID | None
    source_interview_report_version_id: uuid.UUID | None
    currency: Literal["CNY"]
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    created_at: datetime
    manager_confirmation: OfferManagerConfirmationResponse | None
    approval: OfferApprovalResponse | None


class OfferResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    application_status: Literal["active", "merged"]
    job_id: uuid.UUID
    job_title: str
    candidate_id: uuid.UUID
    candidate_code: str
    candidate_name: str | None
    status: OfferStatus
    current_version_number: int
    current_version: OfferVersionResponse
    versions: list[OfferVersionResponse]
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class OfferSummaryResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    candidate_id: uuid.UUID
    candidate_code: str
    candidate_name: str | None
    status: OfferStatus
    current_version_number: int
    current_version: OfferVersionResponse
    updated_at: datetime
