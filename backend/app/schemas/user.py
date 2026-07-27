import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.schemas.auth import RoleKey


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    display_name: str = Field(min_length=1, max_length=100)
    temporary_password: SecretStr = Field(min_length=8, max_length=256)
    roles: list[RoleKey] = Field(min_length=1, max_length=4)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value

    @model_validator(mode="after")
    def validate_unique_roles(self) -> Self:
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("角色不能重复")
        return self


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
    roles: list[RoleKey] | None = Field(default=None, min_length=1, max_length=4)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value

    @model_validator(mode="after")
    def validate_unique_roles(self) -> Self:
        if self.roles is not None and len(self.roles) != len(set(self.roles)):
            raise ValueError("角色不能重复")
        return self


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temporary_password: SecretStr = Field(min_length=8, max_length=256)


class ManagedUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    is_active: bool
    must_change_password: bool
    roles: list[RoleKey] = Field(validation_alias="role_keys")
    created_at: datetime
    updated_at: datetime


class UserOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    roles: list[RoleKey] = Field(validation_alias="role_keys")
