from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InternalNotification, User

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_OFFER_PORTAL_TOKEN_PATTERN = re.compile(r"/portal/offers/[A-Za-z0-9_-]{16,}")
_COMPENSATION_PATTERN = re.compile(r"(月薪|薪资|年薪|试用期薪资)\s*[:：]?\s*\d+")


class InternalNotificationError(Exception):
    pass


@dataclass(frozen=True)
class InternalNotificationPayload:
    notification_type: str
    event_key: str
    title: str
    summary: str
    resource_type: str
    resource_id: uuid.UUID
    route_path: str


def _normalize_required(value: str, *, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise InternalNotificationError(f"{field_name}不能为空")
    if len(normalized) > max_length:
        raise InternalNotificationError(f"{field_name}过长")
    return normalized


def _normalize_summary(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > 500:
        raise InternalNotificationError("通知摘要过长")
    return normalized


def _ensure_safe_text(title: str, summary: str) -> None:
    text = f"{title}\n{summary}"
    if _EMAIL_PATTERN.search(text):
        raise InternalNotificationError("站内通知不能包含完整邮箱")
    if _PHONE_PATTERN.search(text):
        raise InternalNotificationError("站内通知不能包含完整手机号")
    if _OFFER_PORTAL_TOKEN_PATTERN.search(text):
        raise InternalNotificationError("站内通知不能包含 Offer 原始链接")
    if _COMPENSATION_PATTERN.search(text):
        raise InternalNotificationError("站内通知不能包含薪酬明细")


def normalize_notification_payload(
    payload: InternalNotificationPayload,
) -> InternalNotificationPayload:
    notification_type = _normalize_required(
        payload.notification_type,
        field_name="通知类型",
        max_length=60,
    )
    event_key = _normalize_required(payload.event_key, field_name="通知事件键", max_length=160)
    title = _normalize_required(payload.title, field_name="通知标题", max_length=200)
    summary = _normalize_summary(payload.summary)
    resource_type = _normalize_required(payload.resource_type, field_name="资源类型", max_length=60)
    route_path = _normalize_required(payload.route_path, field_name="跳转路径", max_length=500)
    if not route_path.startswith("/"):
        raise InternalNotificationError("站内通知跳转路径必须是内部路径")
    _ensure_safe_text(title, summary)
    return InternalNotificationPayload(
        notification_type=notification_type,
        event_key=event_key,
        title=title,
        summary=summary,
        resource_type=resource_type,
        resource_id=payload.resource_id,
        route_path=route_path,
    )


def create_internal_notification(
    db: Session,
    *,
    recipient: User,
    payload: InternalNotificationPayload,
) -> tuple[InternalNotification | None, bool]:
    if not recipient.is_active:
        return None, False
    normalized = normalize_notification_payload(payload)
    existing = db.scalar(
        select(InternalNotification).where(
            InternalNotification.recipient_user_id == recipient.id,
            InternalNotification.event_key == normalized.event_key,
            InternalNotification.notification_type == normalized.notification_type,
        )
    )
    if existing is not None:
        return existing, False
    notification = InternalNotification(
        recipient_user_id=recipient.id,
        event_key=normalized.event_key,
        notification_type=normalized.notification_type,
        title=normalized.title,
        summary=normalized.summary,
        resource_type=normalized.resource_type,
        resource_id=normalized.resource_id,
        route_path=normalized.route_path,
    )
    db.add(notification)
    db.flush()
    return notification, True


def create_internal_notifications(
    db: Session,
    *,
    recipients: list[User],
    payload: InternalNotificationPayload,
) -> list[InternalNotification]:
    created_or_existing: list[InternalNotification] = []
    seen_user_ids: set[uuid.UUID] = set()
    for recipient in recipients:
        if recipient.id in seen_user_ids:
            continue
        seen_user_ids.add(recipient.id)
        notification, _created = create_internal_notification(
            db,
            recipient=recipient,
            payload=payload,
        )
        if notification is not None:
            created_or_existing.append(notification)
    return created_or_existing