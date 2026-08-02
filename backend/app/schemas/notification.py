import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

InternalNotificationReadStatus = Literal["all", "unread", "read"]


class InternalNotificationResponse(BaseModel):
    id: uuid.UUID
    notification_type: str
    title: str
    summary: str
    resource_type: str
    resource_id: uuid.UUID
    route_path: str
    read_at: datetime | None
    created_at: datetime


class InternalNotificationListResponse(BaseModel):
    items: list[InternalNotificationResponse]
    total: int
    unread_count: int
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class InternalNotificationUnreadCountResponse(BaseModel):
    unread_count: int


class InternalNotificationReadResponse(BaseModel):
    id: uuid.UUID
    read_at: datetime


class InternalNotificationReadAllResponse(BaseModel):
    updated_count: int
    read_at: datetime
