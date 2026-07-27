import uuid
from collections.abc import Generator

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditLog, Role, User, UserRole
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@pytest.fixture
def user_dependencies() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        roles = {
            key: Role(key=key, display_name=label)
            for key, label in {
                "administrator": "企业管理员",
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
                "approver": "审批人",
            }.items()
        }
        administrator = User(
            username="administrator",
            password_hash=hash_password("administrator-password"),
            display_name="企业管理员",
            role_assignments=[UserRole(role=roles["administrator"])],
        )
        recruiter = User(
            username="recruiter",
            password_hash=hash_password("recruiter-password"),
            display_name="招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        db.add_all([*roles.values(), administrator, recruiter])
        db.commit()

    session_store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    yield testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    response = await client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200
    return client.cookies["smarthr_session"]


@pytest.mark.asyncio
async def test_administrator_creates_and_lists_user(
    user_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "administrator", "administrator-password")
        created = await client.post(
            "/users",
            json={
                "username": "Manager.One",
                "display_name": "  用人经理一号  ",
                "temporary_password": "temporary-password",
                "roles": ["hiring_manager", "approver"],
            },
        )
        duplicate = await client.post(
            "/users",
            json={
                "username": "manager.one",
                "display_name": "重复账号",
                "temporary_password": "temporary-password",
                "roles": ["hiring_manager"],
            },
        )
        listed = await client.get("/users")

    assert created.status_code == 201
    assert created.json()["username"] == "manager.one"
    assert created.json()["display_name"] == "用人经理一号"
    assert created.json()["roles"] == ["approver", "hiring_manager"]
    assert created.json()["must_change_password"] is True
    assert "temporary_password" not in created.json()
    assert duplicate.status_code == 409
    assert {item["username"] for item in listed.json()} == {
        "administrator",
        "recruiter",
        "manager.one",
    }

    with user_dependencies() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "user.created"))
    assert audit is not None
    assert "password" not in str(audit.details).lower()


@pytest.mark.asyncio
async def test_non_administrator_cannot_manage_users(user_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter", "recruiter-password")
        response = await client.get("/users")

    assert response.status_code == 403
    assert response.json() == {"detail": "需要企业管理员权限"}


@pytest.mark.asyncio
async def test_role_and_status_changes_invalidate_existing_session(
    user_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as recruiter:
        old_token = await login(recruiter, "recruiter", "recruiter-password")
        me = await recruiter.get("/auth/me")
        recruiter_id = uuid.UUID(me.json()["id"])

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as admin:
        await login(admin, "administrator", "administrator-password")
        roles_changed = await admin.patch(
            f"/users/{recruiter_id}",
            json={"roles": ["recruiter", "approver"]},
        )
        deactivated = await admin.patch(
            f"/users/{recruiter_id}", json={"is_active": False}
        )

    assert roles_changed.status_code == 200
    assert roles_changed.json()["roles"] == ["approver", "recruiter"]
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as old_client:
        old_client.cookies.set("smarthr_session", old_token)
        assert (await old_client.get("/auth/me")).status_code == 401

    with user_dependencies() as db:
        user = db.get(User, recruiter_id)
    assert user is not None
    assert user.session_version == 3


@pytest.mark.asyncio
async def test_last_active_administrator_is_protected(user_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "administrator", "administrator-password")
        administrator_id = uuid.UUID((await client.get("/auth/me")).json()["id"])
        remove_role = await client.patch(
            f"/users/{administrator_id}", json={"roles": ["recruiter"]}
        )
        deactivate = await client.patch(
            f"/users/{administrator_id}", json={"is_active": False}
        )

    assert remove_role.status_code == 409
    assert deactivate.status_code == 409
    assert "最后一名有效企业管理员" in remove_role.json()["detail"]


@pytest.mark.asyncio
async def test_password_reset_requires_temporary_password_and_invalidates_session(
    user_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as recruiter:
        old_token = await login(recruiter, "recruiter", "recruiter-password")
        recruiter_id = uuid.UUID((await recruiter.get("/auth/me")).json()["id"])

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as admin:
        await login(admin, "administrator", "administrator-password")
        reset = await admin.post(
            f"/users/{recruiter_id}/reset-password",
            json={"temporary_password": "new-temporary-password"},
        )

    assert reset.status_code == 200
    assert reset.json()["must_change_password"] is True
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as old_client:
        old_client.cookies.set("smarthr_session", old_token)
        assert (await old_client.get("/auth/me")).status_code == 401
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as fresh:
        logged_in = await fresh.post(
            "/auth/login",
            json={"username": "recruiter", "password": "new-temporary-password"},
        )
        assert logged_in.status_code == 200
        assert logged_in.json()["must_change_password"] is True

    with user_dependencies() as db:
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "user.password_reset")
        )
    assert audit is not None
    assert audit.details == {"session_invalidated": True}
