import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import InternalNotification, Role, User, UserRole
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class NotificationRouteDependencies:
    session_factory: sessionmaker[Session]
    alice_unread_id: uuid.UUID
    alice_read_id: uuid.UUID
    bob_unread_id: uuid.UUID


@pytest.fixture
def notification_route_dependencies() -> Generator[NotificationRouteDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        role = Role(key="recruiter", display_name="招聘专员")
        alice = User(
            username="alice",
            password_hash=hash_password("correct-password"),
            display_name="Alice",
            role_assignments=[UserRole(role=role)],
        )
        bob = User(
            username="bob",
            password_hash=hash_password("correct-password"),
            display_name="Bob",
            role_assignments=[UserRole(role=role)],
        )
        db.add_all([role, alice, bob])
        db.flush()
        now = datetime.now(UTC)
        alice_unread = InternalNotification(
            recipient_user_id=alice.id,
            event_key="event:alice:unread",
            notification_type="offer_approved",
            title="Offer 已批准",
            summary="高级后端工程师的 Offer 已批准",
            resource_type="offer",
            resource_id=uuid.uuid4(),
            route_path="/offers?selected=alice-unread",
            created_at=now - timedelta(minutes=10),
        )
        alice_read = InternalNotification(
            recipient_user_id=alice.id,
            event_key="event:alice:read",
            notification_type="onboarding_completed",
            title="候选人已入职",
            summary="高级后端工程师的候选人已标记为入职",
            resource_type="onboarding",
            resource_id=uuid.uuid4(),
            route_path="/onboardings?selected=alice-read",
            read_at=now - timedelta(minutes=1),
            created_at=now,
        )
        bob_unread = InternalNotification(
            recipient_user_id=bob.id,
            event_key="event:bob:unread",
            notification_type="offer_approved",
            title="Bob 的通知",
            summary="只属于 Bob",
            resource_type="offer",
            resource_id=uuid.uuid4(),
            route_path="/offers?selected=bob",
            created_at=now + timedelta(minutes=1),
        )
        db.add_all([alice_unread, alice_read, bob_unread])
        db.commit()
        dependencies = NotificationRouteDependencies(
            session_factory=testing_session,
            alice_unread_id=alice_unread.id,
            alice_read_id=alice_read.id,
            bob_unread_id=bob_unread.id,
        )

    store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3_600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: store
    yield dependencies
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def _login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_lists_only_own_notifications_with_filters_and_unread_count(
    notification_route_dependencies: NotificationRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "alice")

        listing = await client.get("/notifications")
        assert listing.status_code == 200
        body = listing.json()
        assert body["total"] == 2
        assert body["unread_count"] == 1
        assert [item["id"] for item in body["items"]] == [
            str(notification_route_dependencies.alice_read_id),
            str(notification_route_dependencies.alice_unread_id),
        ]
        assert all("Bob" not in item["title"] for item in body["items"])

        unread = await client.get("/notifications", params={"status": "unread"})
        assert unread.status_code == 200
        assert unread.json()["total"] == 1
        assert unread.json()["items"][0]["id"] == str(
            notification_route_dependencies.alice_unread_id
        )

        filtered = await client.get(
            "/notifications",
            params={"notification_type": "onboarding_completed"},
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["id"] == str(
            notification_route_dependencies.alice_read_id
        )

        unread_count = await client.get("/notifications/unread-count")
        assert unread_count.status_code == 200
        assert unread_count.json() == {"unread_count": 1}


@pytest.mark.asyncio
async def test_mark_single_notification_read_is_owned_and_idempotent(
    notification_route_dependencies: NotificationRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "alice")

        forbidden = await client.post(
            f"/notifications/{notification_route_dependencies.bob_unread_id}/read"
        )
        assert forbidden.status_code == 404

        first = await client.post(
            f"/notifications/{notification_route_dependencies.alice_unread_id}/read"
        )
        assert first.status_code == 200
        first_body = first.json()
        assert first_body["id"] == str(notification_route_dependencies.alice_unread_id)
        assert first_body["read_at"] is not None

        repeated = await client.post(
            f"/notifications/{notification_route_dependencies.alice_unread_id}/read"
        )
        assert repeated.status_code == 200
        assert repeated.json() == first_body

        unread_count = await client.get("/notifications/unread-count")
        assert unread_count.json() == {"unread_count": 0}


@pytest.mark.asyncio
async def test_mark_all_notifications_read_only_updates_current_user(
    notification_route_dependencies: NotificationRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "alice")

        first = await client.post("/notifications/read-all")
        assert first.status_code == 200
        assert first.json()["updated_count"] == 1

        repeated = await client.post("/notifications/read-all")
        assert repeated.status_code == 200
        assert repeated.json()["updated_count"] == 0

    with notification_route_dependencies.session_factory() as db:
        bob_notification = db.scalar(
            select(InternalNotification).where(
                InternalNotification.id
                == notification_route_dependencies.bob_unread_id
            )
        )
        assert bob_notification is not None
        assert bob_notification.read_at is None
