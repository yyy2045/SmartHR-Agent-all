import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import InternalNotification, Role, User, UserRole
from app.services.internal_notifications import (
    InternalNotificationError,
    InternalNotificationPayload,
    create_internal_notification,
    create_internal_notifications,
)
from app.services.security import hash_password


@pytest.fixture
def notification_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        recruiter_role = Role(key="recruiter", display_name="招聘专员")
        manager_role = Role(key="hiring_manager", display_name="用人经理")
        active_user = User(
            username="active-user",
            password_hash=hash_password("correct-password"),
            display_name="活跃用户",
            role_assignments=[UserRole(role=recruiter_role), UserRole(role=manager_role)],
        )
        inactive_user = User(
            username="inactive-user",
            password_hash=hash_password("correct-password"),
            display_name="停用用户",
            is_active=False,
            role_assignments=[UserRole(role=recruiter_role)],
        )
        db.add_all([recruiter_role, manager_role, active_user, inactive_user])
        db.commit()
    yield testing_session
    engine.dispose()


def payload(**changes: object) -> InternalNotificationPayload:
    values: dict[str, object] = {
        "notification_type": "offer_approval_requested",
        "event_key": "offer:approval:123",
        "title": "Offer 待审批",
        "summary": "高级后端工程师有一条 Offer 待处理",
        "resource_type": "offer",
        "resource_id": uuid.uuid4(),
        "route_path": "/offers?selected=123",
    }
    values.update(changes)
    return InternalNotificationPayload(**values)


def test_notification_creation_is_transactional_and_idempotent(
    notification_session_factory: sessionmaker[Session],
) -> None:
    with notification_session_factory() as db:
        user = db.scalar(select(User).where(User.username == "active-user"))
        assert user is not None
        created, created_flag = create_internal_notification(db, recipient=user, payload=payload())
        assert created is not None
        assert created_flag is True
        db.rollback()
        assert db.scalar(select(func.count(InternalNotification.id))) == 0

        first, first_flag = create_internal_notification(db, recipient=user, payload=payload())
        second, second_flag = create_internal_notification(db, recipient=user, payload=payload())
        db.commit()

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert first_flag is True
        assert second_flag is False
        assert db.scalar(select(func.count(InternalNotification.id))) == 1


def test_multiple_recipients_are_deduplicated_and_inactive_users_are_skipped(
    notification_session_factory: sessionmaker[Session],
) -> None:
    with notification_session_factory() as db:
        active_user = db.scalar(select(User).where(User.username == "active-user"))
        inactive_user = db.scalar(select(User).where(User.username == "inactive-user"))
        assert active_user is not None and inactive_user is not None

        notifications = create_internal_notifications(
            db,
            recipients=[active_user, active_user, inactive_user],
            payload=payload(),
        )
        db.commit()

        assert len(notifications) == 1
        assert notifications[0].recipient_user_id == active_user.id
        assert db.scalar(select(func.count(InternalNotification.id))) == 1


def test_sensitive_notification_content_is_rejected(
    notification_session_factory: sessionmaker[Session],
) -> None:
    with notification_session_factory() as db:
        user = db.scalar(select(User).where(User.username == "active-user"))
        assert user is not None
        sensitive_payloads = [
            payload(summary="候选人电话 13800001234"),
            payload(summary="候选人邮箱 candidate@example.com"),
            payload(summary="Offer 链接 /portal/offers/raw-token-value-that-must-never-persist"),
            payload(summary="月薪 30000 待审批"),
        ]
        for item in sensitive_payloads:
            with pytest.raises(InternalNotificationError):
                create_internal_notification(db, recipient=user, payload=item)


def test_database_constraints_reject_invalid_notification_rows(
    notification_session_factory: sessionmaker[Session],
) -> None:
    with notification_session_factory() as db:
        user = db.scalar(select(User).where(User.username == "active-user"))
        assert user is not None
        db.add(
            InternalNotification(
                recipient_user_id=user.id,
                event_key="event",
                notification_type="offer",
                title="非法路径通知",
                summary="安全摘要",
                resource_type="offer",
                resource_id=uuid.uuid4(),
                route_path="https://example.com/offers/1",
            )
        )
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert "ck_internal_notifications_route_path" in str(error.value)