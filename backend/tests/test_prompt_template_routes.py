import uuid
from collections.abc import Generator
from dataclasses import dataclass

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Role, User, UserRole
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class PromptRouteDependencies:
    session_factory: sessionmaker[Session]


@pytest.fixture
def prompt_route_dependencies() -> Generator[PromptRouteDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        admin_role = Role(key="administrator", display_name="企业管理员")
        recruiter_role = Role(key="recruiter", display_name="招聘专员")
        administrator = User(
            username="administrator",
            password_hash=hash_password("correct-password"),
            display_name="管理员",
            role_assignments=[UserRole(role=admin_role)],
        )
        recruiter = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
            role_assignments=[UserRole(role=recruiter_role)],
        )
        db.add_all([admin_role, recruiter_role, administrator, recruiter])
        db.commit()

    store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3_600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: store
    yield PromptRouteDependencies(testing_session)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def _login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


def _create_payload(idempotency_key: str | None = None) -> dict[str, object]:
    return {
        "scenario": "resume_analysis",
        "name": "简历评分 Prompt",
        "description": "根据职位标准和简历生成结构化评分",
        "change_note": "初始化模板",
        "system_prompt": "你是企业招聘的人岗匹配助手。",
        "user_prompt_template": "职位标准：{{criteria}}\n简历：{{resume}}",
        "variables": ["criteria", "resume"],
        "output_schema": {"type": "object"},
        "model_parameters": {"temperature": 0},
        "idempotency_key": idempotency_key or str(uuid.uuid4()),
    }


@pytest.mark.asyncio
async def test_administrator_creates_versions_and_publishes_prompt_template(
    prompt_route_dependencies: PromptRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "administrator")

        created = await client.post("/prompt-templates", json=_create_payload())
        assert created.status_code == 201
        created_body = created.json()
        template_id = created_body["id"]
        first_version_id = created_body["versions"][0]["id"]
        assert created_body["current_version_number"] is None
        assert created_body["versions"][0]["status"] == "draft"

        published = await client.post(
            f"/prompt-templates/{template_id}/publish",
            json={
                "version_id": first_version_id,
                "expected_version": created_body["resource_version"],
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert published.status_code == 200
        published_body = published.json()
        assert published_body["current_version_number"] == 1
        assert published_body["versions"][0]["status"] == "published"

        new_version = await client.post(
            f"/prompt-templates/{template_id}/versions",
            json={
                "source_version_id": first_version_id,
                "change_note": "增加证据引用要求",
                "system_prompt": "你是企业招聘的人岗匹配助手，必须引用证据。",
                "user_prompt_template": "职位标准：{{criteria}}\n简历：{{resume}}",
                "variables": ["criteria", "resume"],
                "output_schema": {"type": "object", "required": ["summary"]},
                "model_parameters": {"temperature": 0},
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert new_version.status_code == 200
        version_body = new_version.json()
        second_version_id = version_body["versions"][1]["id"]
        assert version_body["versions"][1]["version_number"] == 2
        assert version_body["versions"][1]["status"] == "draft"

        republished = await client.post(
            f"/prompt-templates/{template_id}/publish",
            json={
                "version_id": second_version_id,
                "expected_version": version_body["resource_version"],
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert republished.status_code == 200
        final_body = republished.json()
        assert final_body["current_version_number"] == 2
        statuses = {item["version_number"]: item["status"] for item in final_body["versions"]}
        assert statuses == {1: "retired", 2: "published"}

        listing = await client.get("/prompt-templates")
        assert listing.status_code == 200
        assert listing.json()["items"][0]["id"] == template_id


@pytest.mark.asyncio
async def test_prompt_template_write_is_admin_only_and_conflict_safe(
    prompt_route_dependencies: PromptRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        forbidden = await client.post("/prompt-templates", json=_create_payload())
        assert forbidden.status_code == 403

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as admin:
        await _login(admin, "administrator")
        first = await admin.post("/prompt-templates", json=_create_payload())
        assert first.status_code == 201
        duplicate = await admin.post("/prompt-templates", json=_create_payload())
        assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_prompt_template_publish_uses_resource_version(
    prompt_route_dependencies: PromptRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "administrator")
        created = await client.post("/prompt-templates", json=_create_payload())
        body = created.json()

        conflict = await client.post(
            f"/prompt-templates/{body['id']}/publish",
            json={
                "version_id": body["versions"][0]["id"],
                "expected_version": body["resource_version"] + 1,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert conflict.status_code == 409
