import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import InternalNotification
from app.schemas.notification import (
    InternalNotificationListResponse,
    InternalNotificationReadAllResponse,
    InternalNotificationReadResponse,
    InternalNotificationReadStatus,
    InternalNotificationResponse,
    InternalNotificationUnreadCountResponse,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _owned_notification(
    db: Session,
    notification_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> InternalNotification:
    query = select(InternalNotification).where(
        InternalNotification.id == notification_id,
        InternalNotification.recipient_user_id == recipient_user_id,
    )
    if for_update:
        query = query.with_for_update()
    notification = db.scalar(query)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="站内通知不存在",
        )
    return notification


def _response(notification: InternalNotification) -> InternalNotificationResponse:
    return InternalNotificationResponse(
        id=notification.id,
        notification_type=notification.notification_type,
        title=notification.title,
        summary=notification.summary,
        resource_type=notification.resource_type,
        resource_id=notification.resource_id,
        route_path=notification.route_path,
        read_at=_ensure_utc(notification.read_at),
        created_at=_ensure_utc(notification.created_at),
    )



def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
def _unread_count(db: Session, recipient_user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count(InternalNotification.id)).where(
                InternalNotification.recipient_user_id == recipient_user_id,
                InternalNotification.read_at.is_(None),
            )
        )
        or 0
    )


@router.get("", response_model=InternalNotificationListResponse)
def list_internal_notifications(
    current_user: CurrentUser,
    db: DbSession,
    read_status: Annotated[
        InternalNotificationReadStatus,
        Query(alias="status"),
    ] = "all",
    notification_type: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InternalNotificationListResponse:
    filters = [InternalNotification.recipient_user_id == current_user.id]
    if read_status == "unread":
        filters.append(InternalNotification.read_at.is_(None))
    elif read_status == "read":
        filters.append(InternalNotification.read_at.is_not(None))
    if notification_type is not None:
        filters.append(InternalNotification.notification_type == notification_type.strip())

    total = db.scalar(select(func.count(InternalNotification.id)).where(*filters)) or 0
    items = list(
        db.scalars(
            select(InternalNotification)
            .where(*filters)
            .order_by(InternalNotification.created_at.desc(), InternalNotification.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return InternalNotificationListResponse(
        items=[_response(item) for item in items],
        total=total,
        unread_count=_unread_count(db, current_user.id),
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count", response_model=InternalNotificationUnreadCountResponse)
def get_internal_notification_unread_count(
    current_user: CurrentUser,
    db: DbSession,
) -> InternalNotificationUnreadCountResponse:
    return InternalNotificationUnreadCountResponse(
        unread_count=_unread_count(db, current_user.id),
    )


@router.post("/{notification_id}/read", response_model=InternalNotificationReadResponse)
def mark_internal_notification_read(
    notification_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> InternalNotificationReadResponse:
    notification = _owned_notification(
        db,
        notification_id,
        current_user.id,
        for_update=True,
    )
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
    else:
        db.rollback()
    assert notification.read_at is not None
    return InternalNotificationReadResponse(
        id=notification.id,
        read_at=_ensure_utc(notification.read_at),
    )


@router.post("/read-all", response_model=InternalNotificationReadAllResponse)
def mark_all_internal_notifications_read(
    current_user: CurrentUser,
    db: DbSession,
) -> InternalNotificationReadAllResponse:
    read_at = datetime.now(UTC)
    notifications = list(
        db.scalars(
            select(InternalNotification)
            .where(
                InternalNotification.recipient_user_id == current_user.id,
                InternalNotification.read_at.is_(None),
            )
            .with_for_update()
        )
    )
    for notification in notifications:
        notification.read_at = read_at
    db.commit()
    return InternalNotificationReadAllResponse(
        updated_count=len(notifications),
        read_at=read_at,
    )
