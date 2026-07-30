import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TalentPoolGroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2_000)
    idempotency_key: uuid.UUID

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("人才分组名称不能为空")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TalentPoolGroupUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2_000)
    expected_version: int = Field(ge=1)
    idempotency_key: uuid.UUID

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("人才分组名称不能为空")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_change(self) -> "TalentPoolGroupUpdateRequest":
        if "name" not in self.model_fields_set and "description" not in self.model_fields_set:
            raise ValueError("至少提交名称或说明中的一项")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("人才分组名称不能设为空")
        return self


class TalentPoolGroupArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    idempotency_key: uuid.UUID
    reason: str = Field(min_length=1, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("归档原因不能为空")
        return normalized


class TalentPoolGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    version: int
    is_archived: bool
    member_count: int
    created_by_id: uuid.UUID | None
    created_by_display_name: str | None
    archived_at: datetime | None
    archived_by_id: uuid.UUID | None
    archived_by_display_name: str | None
    created_at: datetime
    updated_at: datetime


class TalentPoolGroupListResponse(BaseModel):
    items: list[TalentPoolGroupResponse]
    total: int
    limit: int
    offset: int


class TalentPoolMemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: uuid.UUID
    source_application_id: uuid.UUID | None = None


class TalentPoolMembershipAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    members: list[TalentPoolMemberInput] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2_000)
    expected_group_version: int = Field(ge=1)
    idempotency_key: uuid.UUID

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("入库原因不能为空")
        return normalized

    @field_validator("members")
    @classmethod
    def unique_candidates(
        cls, value: list[TalentPoolMemberInput]
    ) -> list[TalentPoolMemberInput]:
        candidate_ids = [item.candidate_id for item in value]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("同一批次不能重复提交候选人")
        return value


class TalentPoolMembershipRemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=2_000)
    expected_group_version: int = Field(ge=1)
    idempotency_key: uuid.UUID

    @field_validator("candidate_ids")
    @classmethod
    def unique_candidates(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("同一批次不能重复提交候选人")
        return value

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("移出原因不能为空")
        return normalized


TalentPoolMembershipOperationStatus = Literal[
    "added",
    "reactivated",
    "already_active",
    "removed",
    "already_removed",
    "not_member",
]


class TalentPoolMembershipOperationItemResponse(BaseModel):
    requested_candidate_id: uuid.UUID
    candidate_id: uuid.UUID
    membership_id: uuid.UUID | None
    status: TalentPoolMembershipOperationStatus


class TalentPoolMembershipOperationResponse(BaseModel):
    group_id: uuid.UUID
    group_version: int
    items: list[TalentPoolMembershipOperationItemResponse]


class TalentPoolMembershipResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    group_archived: bool
    candidate_id: uuid.UUID
    candidate_code: str
    candidate_name: str | None
    phone: str | None
    email: str | None
    status: Literal["active", "removed"]
    reason: str
    source_application_id: uuid.UUID | None
    version: int
    joined_at: datetime
    removed_at: datetime | None
    updated_at: datetime


class TalentPoolMembershipListResponse(BaseModel):
    items: list[TalentPoolMembershipResponse]
    total: int
    limit: int
    offset: int
