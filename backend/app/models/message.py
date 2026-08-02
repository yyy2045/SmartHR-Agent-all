from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
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
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.candidate import Candidate, JobApplication
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

COMMUNICATION_CONTEXT_TYPES = ("interview_round", "offer", "onboarding")
COMMUNICATION_CHANNELS = ("wechat", "phone", "sms", "email", "other")
COMMUNICATION_RECIPIENT_TYPES = ("phone", "email", "other")
COMMUNICATION_RECORD_KINDS = ("sent", "correction")


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


class CommunicationRecord(Base):
    __tablename__ = "communication_records"
    __table_args__ = (
        CheckConstraint(
            "record_kind IN ('sent', 'correction')",
            name="ck_communication_records_kind",
        ),
        CheckConstraint(
            "context_type IN ('interview_round', 'offer', 'onboarding')",
            name="ck_communication_records_context_type",
        ),
        CheckConstraint(
            "channel IN ('wechat', 'phone', 'sms', 'email', 'other')",
            name="ck_communication_records_channel",
        ),
        CheckConstraint(
            "recipient_type IN ('phone', 'email', 'other')",
            name="ck_communication_records_recipient_type",
        ),
        CheckConstraint(
            "(channel IN ('wechat', 'phone', 'sms') AND recipient_type = 'phone') OR "
            "(channel = 'email' AND recipient_type = 'email') OR "
            "(channel = 'other' AND recipient_type = 'other')",
            name="ck_communication_records_channel_recipient",
        ),
        CheckConstraint(
            "(channel = 'other' AND channel_detail IS NOT NULL "
            "AND length(trim(channel_detail)) > 0) OR "
            "(channel <> 'other' AND channel_detail IS NULL)",
            name="ck_communication_records_channel_detail",
        ),
        CheckConstraint(
            "recipient_type = 'other' OR recipient_masked LIKE '%*%'",
            name="ck_communication_records_recipient_masked",
        ),
        CheckConstraint(
            "length(trim(candidate_name_snapshot)) BETWEEN 1 AND 200",
            name="ck_communication_records_candidate_name",
        ),
        CheckConstraint(
            "length(trim(recipient_masked)) BETWEEN 1 AND 320",
            name="ck_communication_records_recipient_length",
        ),
        CheckConstraint(
            "length(trim(subject_snapshot)) BETWEEN 1 AND 500",
            name="ck_communication_records_subject_length",
        ),
        CheckConstraint(
            "length(trim(body_snapshot)) BETWEEN 1 AND 10000",
            name="ck_communication_records_body_length",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_communication_records_fingerprint_length",
        ),
        CheckConstraint(
            "(NOT is_historical AND historical_note IS NULL) OR "
            "(is_historical AND historical_note IS NOT NULL "
            "AND length(trim(historical_note)) > 0)",
            name="ck_communication_records_historical_note",
        ),
        CheckConstraint(
            "(record_kind = 'sent' AND root_record_id IS NULL "
            "AND corrects_record_id IS NULL AND correction_sequence = 0 "
            "AND correction_reason IS NULL) OR "
            "(record_kind = 'correction' AND root_record_id IS NOT NULL "
            "AND corrects_record_id IS NOT NULL AND correction_sequence >= 1 "
            "AND correction_reason IS NOT NULL "
            "AND length(trim(correction_reason)) > 0)",
            name="ck_communication_records_correction_fields",
        ),
        CheckConstraint(
            "root_record_id IS NULL OR root_record_id <> id",
            name="ck_communication_records_root_not_self",
        ),
        CheckConstraint(
            "corrects_record_id IS NULL OR corrects_record_id <> id",
            name="ck_communication_records_corrects_not_self",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_communication_records_idempotency",
        ),
        UniqueConstraint(
            "corrects_record_id",
            name="uq_communication_records_corrects",
        ),
        UniqueConstraint(
            "root_record_id",
            "correction_sequence",
            name="uq_communication_records_root_sequence",
        ),
        Index(
            "ix_communication_records_context",
            "context_type",
            "context_id",
        ),
        Index(
            "ix_communication_records_application_sent",
            "application_id",
            "sent_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    context_type: Mapped[str] = mapped_column(String(30), nullable=False)
    context_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_template_versions.id", ondelete="RESTRICT"), index=True
    )
    record_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="sent", server_default="sent", index=True
    )
    root_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("communication_records.id", ondelete="RESTRICT"), index=True
    )
    corrects_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("communication_records.id", ondelete="RESTRICT"), index=True
    )
    correction_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    correction_reason: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    channel_detail: Mapped[str | None] = mapped_column(String(100))
    recipient_type: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_masked: Mapped[str] = mapped_column(String(320), nullable=False)
    candidate_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    body_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    is_historical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    historical_note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    application: Mapped[JobApplication] = relationship(back_populates="communication_records")
    candidate: Mapped[Candidate] = relationship()
    template_version: Mapped[MessageTemplateVersion | None] = relationship()
    root_record: Mapped[CommunicationRecord | None] = relationship(
        remote_side=[id], foreign_keys=[root_record_id]
    )
    corrects_record: Mapped[CommunicationRecord | None] = relationship(
        remote_side=[id], foreign_keys=[corrects_record_id]
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


_OFFER_PORTAL_TOKEN_PATTERN = re.compile(r"/portal/offers/[A-Za-z0-9_-]{16,}")


@event.listens_for(CommunicationRecord, "before_insert")
def _validate_communication_record_insert(
    _mapper: object,
    connection: object,
    target: CommunicationRecord,
) -> None:
    sent_at = target.sent_at
    aware_sent_at = sent_at if sent_at.tzinfo is not None else sent_at.replace(tzinfo=UTC)
    if aware_sent_at > datetime.now(UTC):
        raise ValueError("沟通发送时间不能晚于当前时间")
    if _OFFER_PORTAL_TOKEN_PATTERN.search(target.subject_snapshot) or (
        _OFFER_PORTAL_TOKEN_PATTERN.search(target.body_snapshot)
    ):
        raise ValueError("沟通安全快照不能保存 Offer 原始链接")
    application_table = Base.metadata.tables["job_applications"]
    application_candidate_id = connection.execute(  # type: ignore[union-attr]
        select(application_table.c.candidate_id).where(
            application_table.c.id == target.application_id
        )
    ).scalar_one_or_none()
    if application_candidate_id is None:
        raise ValueError("候选人沟通关联的职位应聘记录不存在")
    if application_candidate_id != target.candidate_id:
        raise ValueError("候选人沟通记录与职位应聘候选人不一致")
    if target.record_kind != "correction":
        return
    table = CommunicationRecord.__table__
    parent = connection.execute(  # type: ignore[union-attr]
        select(
            table.c.id,
            table.c.application_id,
            table.c.record_kind,
            table.c.root_record_id,
            table.c.correction_sequence,
        ).where(table.c.id == target.corrects_record_id)
    ).mappings().one_or_none()
    root = connection.execute(  # type: ignore[union-attr]
        select(table.c.id, table.c.application_id, table.c.record_kind).where(
            table.c.id == target.root_record_id
        )
    ).mappings().one_or_none()
    if parent is None or root is None:
        raise ValueError("沟通更正引用的历史记录不存在")
    if root["record_kind"] != "sent":
        raise ValueError("沟通更正根记录必须是原始发送记录")
    expected_root_id = parent["id"] if parent["record_kind"] == "sent" else parent["root_record_id"]
    if target.root_record_id != expected_root_id or root["id"] != expected_root_id:
        raise ValueError("沟通更正链的根记录不一致")
    if parent["application_id"] != target.application_id or (
        root["application_id"] != target.application_id
    ):
        raise ValueError("沟通更正必须属于同一职位应聘记录")
    if target.correction_sequence != parent["correction_sequence"] + 1:
        raise ValueError("沟通更正序号必须连续递增")


@event.listens_for(CommunicationRecord, "before_update")
def _protect_communication_record_update(
    _mapper: object,
    _connection: object,
    _target: CommunicationRecord,
) -> None:
    raise ValueError("候选人沟通记录不可修改")


@event.listens_for(CommunicationRecord, "before_delete")
def _protect_communication_record_delete(
    _mapper: object,
    _connection: object,
    _target: CommunicationRecord,
) -> None:
    raise ValueError("候选人沟通记录不可删除")
