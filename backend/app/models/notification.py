from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class InternalNotification(Base):
    __tablename__ = "internal_notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_user_id",
            "event_key",
            "notification_type",
            name="uq_internal_notifications_event_recipient",
        ),
        CheckConstraint(
            "length(trim(event_key)) BETWEEN 1 AND 160",
            name="ck_internal_notifications_event_key",
        ),
        CheckConstraint(
            "length(trim(notification_type)) BETWEEN 1 AND 60",
            name="ck_internal_notifications_type",
        ),
        CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 200",
            name="ck_internal_notifications_title",
        ),
        CheckConstraint(
            "length(summary) <= 500",
            name="ck_internal_notifications_summary_length",
        ),
        CheckConstraint(
            "length(trim(resource_type)) BETWEEN 1 AND 60",
            name="ck_internal_notifications_resource_type",
        ),
        CheckConstraint(
            "route_path LIKE '/%' AND length(trim(route_path)) BETWEEN 1 AND 500",
            name="ck_internal_notifications_route_path",
        ),
        Index(
            "ix_internal_notifications_recipient_unread_created",
            "recipient_user_id",
            "read_at",
            "created_at",
        ),
        Index(
            "ix_internal_notifications_resource",
            "resource_type",
            "resource_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_key: Mapped[str] = mapped_column(String(160), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    route_path: Mapped[str] = mapped_column(String(500), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    recipient: Mapped[User] = relationship()