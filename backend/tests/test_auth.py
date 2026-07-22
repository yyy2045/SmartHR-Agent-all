from collections.abc import Generator

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditLog, User
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@pytest.fixture
def auth_dependencies() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        db.add(
            User(
                username="recruiter",
                password_hash=hash_password("correct-password"),
                display_name="测试招聘专员",
            )
        )
        db.commit()

    redis_client = fakeredis.FakeRedis(decode_responses=True)
    session_store = SessionStore(redis_client=redis_client, ttl_seconds=3600)

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    def override_session_store() -> SessionStore:
        return session_store

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_session_store
    yield testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.mark.asyncio
async def test_login_me_and_logout(
    auth_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/auth/login",
            json={"username": "Recruiter", "password": "correct-password"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["display_name"] == "测试招聘专员"
        assert "smarthr_session" in client.cookies

        me_response = await client.get("/auth/me")
        assert me_response.status_code == 200
        assert me_response.json()["username"] == "recruiter"

        logout_response = await client.post("/auth/logout")
        assert logout_response.status_code == 204

        unauthorized_response = await client.get("/auth/me")
        assert unauthorized_response.status_code == 401
        assert unauthorized_response.json() == {"detail": "请先登录"}

    with auth_dependencies() as db:
        logs = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at)))
    assert [(item.action, item.result) for item in logs] == [
        ("auth.login", "success"),
        ("auth.logout", "success"),
    ]
    assert all(item.actor_username == "recruiter" for item in logs)


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(
    auth_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/auth/login",
            json={"username": "recruiter", "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "用户名或密码错误"}
    with auth_dependencies() as db:
        log = db.scalar(select(AuditLog).where(AuditLog.action == "auth.login"))
    assert log is not None
    assert log.result == "failure"
    assert log.actor_username == "recruiter"
    assert log.details == {"reason": "invalid_credentials"}
