import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RecruitmentRequestPriority = Literal["urgent", "high", "normal", "low"]
RecruitmentRequestStatus = Literal[
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "converted",
]
RecruitmentRequestDecisionValue = Literal["approved", "rejected"]


class RecruitmentRequestContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_title: str = Field(min_length=1, max_length=200)
    headcount: int = Field(ge=1, le=10_000)
    reason: str = Field(min_length=1, max_length=5_000)
    priority: RecruitmentRequestPriority = "normal"
    target_start_date: date
    salary_min: int = Field(ge=0, le=100_000_000)
    salary_max: int = Field(ge=0, le=100_000_000)
    notes: str = Field(default="", max_length=5_000)

    @field_validator("job_title", "reason")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_salary_range(self) -> Self:
        if self.salary_max < self.salary_min:
            raise ValueError("薪酬上限不能低于下限")
        return self


class RecruitmentRequestCreate(RecruitmentRequestContent):
    idempotency_key: uuid.UUID
    requester_id: uuid.UUID | None = None
    recruiter_id: uuid.UUID


class RecruitmentRequestVersionCreate(RecruitmentRequestContent):
    source_version_id: uuid.UUID


class RecruitmentRequestSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID


class RecruitmentRequestJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department: str = Field(default="", max_length=100)
    original_jd: str = Field(min_length=1, max_length=50_000)

    @field_validator("department")
    @classmethod
    def normalize_department(cls, value: str) -> str:
        return value.strip()

    @field_validator("original_jd")
    @classmethod
    def normalize_original_jd(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("职位描述不能为空")
        return value


class RecruitmentRequestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    decision: RecruitmentRequestDecisionValue
    comment: str = Field(default="", max_length=5_000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_rejection_comment(self) -> Self:
        if self.decision == "rejected" and not self.comment:
            raise ValueError("驳回时必须填写审批意见")
        return self


class UserReference(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str


class RecruitmentRequestVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    source_version_id: uuid.UUID | None
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    job_title: str
    headcount: int
    reason: str
    priority: RecruitmentRequestPriority
    target_start_date: date
    salary_min: int
    salary_max: int
    notes: str
    created_at: datetime


class RecruitmentRequestApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_id: uuid.UUID
    approver_id: uuid.UUID | None
    approver_username: str
    approver_display_name: str
    decision: RecruitmentRequestDecisionValue
    comment: str
    decided_at: datetime


class RecruitmentRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idempotency_key: uuid.UUID
    requester: UserReference
    recruiter: UserReference
    created_by: UserReference
    status: RecruitmentRequestStatus
    current_version_number: int
    current_version: RecruitmentRequestVersionResponse
    linked_job_id: uuid.UUID | None
    versions: list[RecruitmentRequestVersionResponse]
    approvals: list[RecruitmentRequestApprovalResponse]
    created_at: datetime
    updated_at: datetime
