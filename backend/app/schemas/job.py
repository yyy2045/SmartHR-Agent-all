import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HardRequirementType = Literal[
    "min_experience_years",
    "min_education",
    "required_certification",
    "language_level",
    "other",
]
OBJECTIVE_REQUIREMENT_TYPES = {
    "min_experience_years",
    "min_education",
    "required_certification",
    "language_level",
}


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    department: str = Field(default="", max_length=100)
    original_jd: str = Field(min_length=1, max_length=50_000)

    @field_validator("title", "original_jd")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @field_validator("department")
    @classmethod
    def normalize_department(cls, value: str) -> str:
        return value.strip()


class JobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    original_jd: str | None = Field(default=None, min_length=1, max_length=50_000)

    @field_validator("title", "original_jd")
    @classmethod
    def validate_optional_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @field_validator("department")
    @classmethod
    def normalize_optional_department(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    department: str
    original_jd: str
    status: Literal["active", "archived"]
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class HardRequirementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_type: HardRequirementType
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    expected_value: str = Field(min_length=1, max_length=200)
    auto_reject: bool = False
    sort_order: int = Field(default=0, ge=0, le=1_000)

    @field_validator("title", "expected_value")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_auto_reject_type(self) -> Self:
        if self.auto_reject and self.requirement_type not in OBJECTIVE_REQUIREMENT_TYPES:
            raise ValueError("只有客观硬性条件允许自动淘汰")
        return self


class ScoringDimensionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2_000)
    weight_percent: int = Field(ge=0, le=100)
    sort_order: int = Field(default=0, ge=0, le=1_000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()


class CriteriaVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version_id: uuid.UUID | None = None


class CriteriaDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pass_threshold: int = Field(default=60, ge=0, le=100)
    hard_requirements: list[HardRequirementInput] = Field(default_factory=list, max_length=100)
    scoring_dimensions: list[ScoringDimensionInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_dimensions(self) -> Self:
        names = [item.name.casefold() for item in self.scoring_dimensions]
        if len(names) != len(set(names)):
            raise ValueError("评分维度名称不能重复")
        return self


class HardRequirementResponse(HardRequirementInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class ScoringDimensionResponse(ScoringDimensionInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class CriteriaVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    version_number: int
    status: Literal["draft", "confirmed"]
    pass_threshold: int
    source_version_id: uuid.UUID | None
    confirmed_by_id: uuid.UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    hard_requirements: list[HardRequirementResponse]
    scoring_dimensions: list[ScoringDimensionResponse]


class JobDetailResponse(JobResponse):
    criteria_versions: list[CriteriaVersionResponse]
