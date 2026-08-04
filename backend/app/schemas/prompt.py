import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PromptScenario = Literal[
    "jd_generation",
    "resume_analysis",
    "resume_analysis_repair",
    "interview_report",
    "offer_copy",
    "candidate_comparison",
    "candidate_qa",
]
PromptTemplateStatus = Literal["active", "inactive"]
PromptVersionStatus = Literal["draft", "published", "retired"]


class PromptTemplateVersionContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_note: str = Field(min_length=1, max_length=500)
    system_prompt: str = Field(min_length=1, max_length=20_000)
    user_prompt_template: str = Field(min_length=1, max_length=20_000)
    variables: list[str] = Field(default_factory=list, max_length=50)
    output_schema: dict[str, object] | None = None
    model_parameters: dict[str, object] = Field(default_factory=dict)

    @field_validator("change_note", "system_prompt", "user_prompt_template")
    @classmethod
    def strip_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("variables")
    @classmethod
    def normalize_variables(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            key = item.strip()
            if not key:
                raise ValueError("变量名不能为空")
            if key in seen:
                raise ValueError("变量名不能重复")
            seen.add(key)
            normalized.append(key)
        return normalized


class PromptTemplateCreateRequest(PromptTemplateVersionContent):
    scenario: PromptScenario
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    idempotency_key: uuid.UUID

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("模板名称不能为空")
        return value

    @field_validator("description")
    @classmethod
    def strip_optional_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class PromptTemplateVersionCreateRequest(PromptTemplateVersionContent):
    source_version_id: uuid.UUID | None = None
    idempotency_key: uuid.UUID


class PromptTemplatePublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    expected_version: int = Field(ge=1)
    idempotency_key: uuid.UUID


class PromptTemplateVersionResponse(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    version_number: int
    status: PromptVersionStatus
    source_version_id: uuid.UUID | None
    change_note: str
    system_prompt: str
    user_prompt_template: str
    variables: list[str]
    output_schema: dict[str, object] | None
    model_parameters: dict[str, object]
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    published_by_id: uuid.UUID | None
    published_by_username: str | None
    published_by_display_name: str | None
    published_at: datetime | None
    created_at: datetime


class PromptTemplateResponse(BaseModel):
    id: uuid.UUID
    scenario: PromptScenario
    name: str
    description: str | None
    status: PromptTemplateStatus
    current_version_number: int | None
    resource_version: int
    created_by_id: uuid.UUID | None
    created_by_username: str
    created_by_display_name: str
    created_at: datetime
    updated_at: datetime
    versions: list[PromptTemplateVersionResponse]


class PromptTemplateListResponse(BaseModel):
    items: list[PromptTemplateResponse]
