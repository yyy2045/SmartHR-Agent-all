from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


MESSAGE_TEMPLATE_TYPES = (
    "interview_invitation",
    "interview_reschedule",
    "interview_cancellation",
    "meeting_details",
    "offer_notification",
    "offer_reminder",
    "onboarding_date_confirmation",
)


class MessageTemplate(Base):
    __tablename__ = "message_templates"
    __table_args__ = (
        CheckConstraint(
            "template_type IN ("
            "'interview_invitation', 'interview_reschedule', "
            "'interview_cancellation', 'meeting_details', "
            "'offer_notification', 'offer_reminder', "
            "'onboarding_date_confirmation')",
            name="ck_message_templates_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_message_templates_status",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_message_templates_name_not_blank",
        ),
        CheckConstraint(
            "current_version_number >= 1",
            name="ck_message_templates_current_version",
        ),
        CheckConstraint(
            "resource_version >= 1",
            name="ck_message_templates_resource_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    system_key: Mapped[str | None] = mapped_column(String(60), unique=True)
    template_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active", index=True
    )
    current_version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    resource_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    versions: Mapped[list[MessageTemplateVersion]] = relationship(
        back_populates="template",
        order_by="MessageTemplateVersion.version_number",
        passive_deletes="all",
    )

    @property
    def current_version(self) -> MessageTemplateVersion:
        for version in reversed(self.versions):
            if version.version_number == self.current_version_number:
                return version
        raise RuntimeError("沟通模板当前版本不存在")


Index(
    "uq_message_templates_active_name_ci",
    func.lower(MessageTemplate.name),
    unique=True,
    postgresql_where=text("status = 'active'"),
    sqlite_where=text("status = 'active'"),
)


class MessageTemplateVersion(Base):
    __tablename__ = "message_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_message_template_versions_number",
        ),
        UniqueConstraint(
            "template_id",
            "idempotency_key",
            name="uq_message_template_versions_idempotency",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_message_template_versions_number",
        ),
        CheckConstraint(
            "length(trim(subject)) BETWEEN 1 AND 100",
            name="ck_message_template_versions_subject_length",
        ),
        CheckConstraint(
            "length(trim(body)) BETWEEN 1 AND 5000",
            name="ck_message_template_versions_body_length",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_template_versions.id", ondelete="RESTRICT"), index=True
    )
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    template: Mapped[MessageTemplate] = relationship(back_populates="versions")
    source_version: Mapped[MessageTemplateVersion | None] = relationship(
        remote_side=[id], foreign_keys=[source_version_id]
    )
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


@event.listens_for(MessageTemplateVersion, "before_update")
def _protect_message_template_version_update(
    _mapper: object,
    _connection: object,
    _target: MessageTemplateVersion,
) -> None:
    raise ValueError("沟通模板历史版本不可修改")


@event.listens_for(MessageTemplateVersion, "before_delete")
def _protect_message_template_version_delete(
    _mapper: object,
    _connection: object,
    _target: MessageTemplateVersion,
) -> None:
    raise ValueError("沟通模板历史版本不可删除")
