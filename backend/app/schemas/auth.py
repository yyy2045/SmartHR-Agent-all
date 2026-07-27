import uuid
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

RoleKey = Literal["administrator", "recruiter", "hiring_manager", "approver"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=8, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: SecretStr = Field(min_length=8, max_length=256)
    new_password: SecretStr = Field(min_length=8, max_length=256)

    @model_validator(mode="after")
    def validate_password_changed(self) -> Self:
        if self.current_password.get_secret_value() == self.new_password.get_secret_value():
            raise ValueError("新密码不能与当前密码相同")
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    is_active: bool
    must_change_password: bool
    roles: list[RoleKey] = Field(validation_alias="role_keys")
