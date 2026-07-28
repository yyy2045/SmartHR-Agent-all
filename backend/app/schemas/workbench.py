import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WorkbenchSection = Literal["action_required", "waiting_external", "risk_failure"]
WorkbenchPriority = Literal["urgent", "high", "normal"]
WorkbenchItemType = Literal[
    "recruitment_request_revision",
    "recruitment_request_approval",
    "manual_screening",
    "interview_scheduling",
    "interview_evaluation",
    "interview_report",
    "offer_manager_confirmation",
    "offer_approval",
    "offer_link",
    "onboarding_date",
    "onboarding_outcome",
    "system_failure",
    "temporary_password_account",
]
WorkbenchSource = Literal[
    "recruitment_requests",
    "screening",
    "interviews",
    "offers",
    "onboardings",
    "system_failures",
    "accounts",
]


class WorkbenchItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stable_key: str = Field(min_length=1, max_length=300)
    section: WorkbenchSection
    item_type: WorkbenchItemType
    source: WorkbenchSource
    priority: WorkbenchPriority
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1_000)
    count: int = Field(ge=1)
    occurred_at: datetime
    risk_at: datetime | None = None
    job_id: uuid.UUID | None = None
    job_title: str | None = Field(default=None, max_length=200)
    target_path: str = Field(min_length=1, max_length=2_000)

    @field_validator("target_path")
    @classmethod
    def validate_internal_target(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("工作台目标必须是站内路径")
        return value


class WorkbenchSectionCount(BaseModel):
    section: WorkbenchSection
    count: int = Field(ge=0)


class WorkbenchPriorityCount(BaseModel):
    priority: WorkbenchPriority
    count: int = Field(ge=0)


class WorkbenchTypeCount(BaseModel):
    item_type: WorkbenchItemType
    count: int = Field(ge=0)


class WorkbenchSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    total_count: int = Field(ge=0)
    action_required_count: int = Field(ge=0)
    sections: list[WorkbenchSectionCount]
    priorities: list[WorkbenchPriorityCount]
    types: list[WorkbenchTypeCount]
    partial: bool = False
    failed_sources: list[WorkbenchSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        section_keys = [item.section for item in self.sections]
        if len(section_keys) != len(set(section_keys)):
            raise ValueError("工作台分区计数不能重复")
        priority_keys = [item.priority for item in self.priorities]
        if len(priority_keys) != len(set(priority_keys)):
            raise ValueError("工作台优先级计数不能重复")
        type_keys = [item.item_type for item in self.types]
        if len(type_keys) != len(set(type_keys)):
            raise ValueError("工作台类型计数不能重复")
        if sum(item.count for item in self.sections) != self.total_count:
            raise ValueError("工作台分区合计与总数不一致")
        action_count = next(
            (item.count for item in self.sections if item.section == "action_required"),
            0,
        )
        if action_count != self.action_required_count:
            raise ValueError("工作台需处理数量与分区计数不一致")
        if self.partial != bool(self.failed_sources):
            raise ValueError("部分失败标记与失败来源不一致")
        return self


class WorkbenchListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    items: list[WorkbenchItemResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    partial: bool = False
    failed_sources: list[WorkbenchSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_partial_state(self) -> Self:
        if self.partial != bool(self.failed_sources):
            raise ValueError("部分失败标记与失败来源不一致")
        return self
