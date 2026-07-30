import uuid
from collections.abc import Generator

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditLog, MessageTemplate, MessageTemplateVersion, Role, User, UserRole
from app.redis_client import get_session_store
from app.services.message_template_defaults import ensure_default_message_templates
from app.services.security import hash_password
from app.services.session_store import SessionStore


@pytest.fixture
def message_template_dependencies() -> Generator[sessionmaker[Session], None, None]:
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
        roles = {
            key: Role(key=key, display_name=label)
            for key, label in {
                "administrator": "企业管理员",
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
                "approver": "审批人",
            }.items()
        }
        users = [
            User(
                username=key,
                password_hash=hash_password(f"{key}-password"),
                display_name=label,
                role_assignments=[UserRole(role=roles[key])],
            )
            for key, label in {
                "administrator": "企业管理员",
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
                "approver": "审批人",
            }.items()
        ]
        db.add_all([*roles.values(), *users])
        db.commit()
    ensure_default_message_templates(testing_session)

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
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": f"{username}-password"},
    )
    assert response.status_code == 200


def create_payload(
    *,
    name: str = "候选人面试提醒",
    key: uuid.UUID | None = None,
) -> dict[str, object]:
    return {
        "template_type": "interview_invitation",
        "name": name,
        "subject": "{{candidate_name}} 面试提醒",
        "body": "{{candidate_name}}，请参加 {{job_title}} 面试。",
        "variables": ["candidate_name", "job_title"],
        "idempotency_key": str(key or uuid.uuid4()),
    }


@pytest.mark.asyncio
async def test_template_role_permissions_and_manager_active_scope(
    message_template_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get("/message-templates")
        await login(client, "approver")
        approver = await client.get("/message-templates")
        await login(client, "hiring_manager")
        manager = await client.get("/message-templates?limit=100")
        manager_all = await client.get("/message-templates?status=all")
        manager_write = await client.post("/message-templates", json=create_payload())

    assert anonymous.status_code == 401
    assert approver.status_code == 403
    assert manager.status_code == 200
    assert manager.json()["total"] == 7
    assert all(item["allowed_actions"] == [] for item in manager.json()["items"])
    assert manager_all.status_code == 403
    assert manager_write.status_code == 403


@pytest.mark.asyncio
async def test_create_template_is_idempotent_and_rejects_duplicate_active_name(
    message_template_dependencies: sessionmaker[Session],
) -> None:
    key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        created = await client.post(
            "/message-templates",
            json=create_payload(name="Candidate Interview Notice", key=key),
        )
        replayed = await client.post(
            "/message-templates",
            json=create_payload(name="Candidate Interview Notice", key=key),
        )
        reused = await client.post(
            "/message-templates",
            json=create_payload(name="不同内容", key=key),
        )
        duplicate = await client.post(
            "/message-templates",
            json=create_payload(name="candidate interview notice"),
        )

    assert created.status_code == 201, created.text
    assert replayed.status_code == 201
    assert replayed.json()["id"] == created.json()["id"]
    assert reused.status_code == 409
    assert duplicate.status_code == 409
    with message_template_dependencies() as db:
        assert db.scalar(select(func.count(MessageTemplate.id))) == 8
        assert db.scalar(select(func.count(MessageTemplateVersion.id))) == 8


@pytest.mark.asyncio
async def test_new_version_is_immutable_idempotent_and_uses_optimistic_lock(
    message_template_dependencies: sessionmaker[Session],
) -> None:
    version_key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "administrator")
        created = await client.post("/message-templates", json=create_payload())
        template_id = created.json()["id"]
        payload = {
            "subject": "新版面试提醒",
            "body": "新版正文 {{candidate_name}}",
            "variables": ["candidate_name"],
            "expected_version": 1,
            "idempotency_key": str(version_key),
        }
        updated = await client.post(
            f"/message-templates/{template_id}/versions", json=payload
        )
        replayed = await client.post(
            f"/message-templates/{template_id}/versions", json=payload
        )
        reused = await client.post(
            f"/message-templates/{template_id}/versions",
            json={**payload, "body": "不同正文"},
        )
        stale = await client.post(
            f"/message-templates/{template_id}/versions",
            json={**payload, "idempotency_key": str(uuid.uuid4())},
        )

    assert updated.status_code == 200, updated.text
    assert updated.json()["current_version_number"] == 2
    assert updated.json()["resource_version"] == 2
    assert [item["version_number"] for item in updated.json()["versions"]] == [1, 2]
    assert replayed.status_code == 200
    assert replayed.json()["current_version_number"] == 2
    assert reused.status_code == 409
    assert stale.status_code == 409
    with message_template_dependencies() as db:
        versions = list(
            db.scalars(
                select(MessageTemplateVersion)
                .where(MessageTemplateVersion.template_id == uuid.UUID(template_id))
                .order_by(MessageTemplateVersion.version_number)
            )
        )
        assert versions[0].body == "{{candidate_name}}，请参加 {{job_title}} 面试。"
        assert versions[1].source_version_id == versions[0].id


@pytest.mark.asyncio
async def test_deactivate_activate_replay_and_manager_visibility(
    message_template_dependencies: sessionmaker[Session],
) -> None:
    deactivate_key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        created = await client.post("/message-templates", json=create_payload())
        template_id = created.json()["id"]
        deactivated = await client.post(
            f"/message-templates/{template_id}/deactivate",
            json={"expected_version": 1, "idempotency_key": str(deactivate_key)},
        )
        replayed = await client.post(
            f"/message-templates/{template_id}/deactivate",
            json={"expected_version": 1, "idempotency_key": str(deactivate_key)},
        )
        duplicate = await client.post(
            f"/message-templates/{template_id}/deactivate",
            json={"expected_version": 2, "idempotency_key": str(uuid.uuid4())},
        )
        await login(client, "hiring_manager")
        hidden = await client.get(f"/message-templates/{template_id}")
        await login(client, "recruiter")
        activated = await client.post(
            f"/message-templates/{template_id}/activate",
            json={"expected_version": 2, "idempotency_key": str(uuid.uuid4())},
        )

    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "inactive"
    assert deactivated.json()["resource_version"] == 2
    assert replayed.status_code == 200
    assert duplicate.status_code == 409
    assert hidden.status_code == 404
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert activated.json()["resource_version"] == 3


@pytest.mark.asyncio
async def test_listing_filters_and_payload_validation(
    message_template_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        filtered = await client.get(
            "/message-templates?template_type=offer_notification&query=Offer&limit=1&offset=0"
        )
        unknown_type = await client.post(
            "/message-templates",
            json={**create_payload(), "template_type": "unknown"},
        )
        duplicate_variables = await client.post(
            "/message-templates",
            json={**create_payload(), "variables": ["candidate_name", "candidate_name"]},
        )

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["template_type"] == "offer_notification"
    assert unknown_type.status_code == 422
    assert duplicate_variables.status_code == 422
    with message_template_dependencies() as db:
        actions = set(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.action.like("message_template.%")
                )
            )
        )
        assert actions == set()
