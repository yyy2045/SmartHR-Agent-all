import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AiCallLog, AiTask, Role, User, UserRole
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class AiObservabilityRouteDependencies:
    session_factory: sessionmaker[Session]
    recruiter_task_id: uuid.UUID
    admin_only_task_id: uuid.UUID
    recruiter_call_id: uuid.UUID
    admin_only_call_id: uuid.UUID


@pytest.fixture
def ai_observability_route_dependencies() -> Generator[
    AiObservabilityRouteDependencies, None, None
]:
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
        db.flush()

        now = datetime.now(UTC)
        recruiter_task = AiTask(
            celery_task_id="celery-recruiter",
            task_name="resume.analyze",
            scenario="resume_analysis",
            status="succeeded",
            attempt_count=1,
            max_retries=2,
            created_by_id=recruiter.id,
            resource_type="resume_document",
            resource_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            started_at=now - timedelta(seconds=3),
            completed_at=now - timedelta(seconds=2),
            duration_ms=1000,
            created_at=now - timedelta(minutes=3),
        )
        admin_only_task = AiTask(
            celery_task_id="celery-system",
            task_name="knowledge.index_profile",
            scenario="knowledge_indexing",
            status="failed",
            attempt_count=2,
            max_retries=3,
            failure_code="embedding_failed",
            failure_message="向量化服务超时",
            created_at=now - timedelta(minutes=2),
            completed_at=now - timedelta(minutes=1),
        )
        recruiter_call = AiCallLog(
            scenario="resume_analysis",
            status="succeeded",
            model_name="qwen-plus",
            prompt_version="resume-match-v2",
            retry_count=1,
            duration_ms=800,
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
            invoked_by_id=recruiter.id,
            resource_type="resume_document",
            resource_id=recruiter_task.resource_id,
            document_id=recruiter_task.document_id,
            created_at=now - timedelta(minutes=3),
        )
        admin_only_call = AiCallLog(
            scenario="jd_generation",
            status="failed",
            model_name="qwen-plus",
            prompt_version="jd-structure-v1",
            duration_ms=500,
            input_tokens=50,
            output_tokens=0,
            total_tokens=50,
            failure_code="ai_timeout",
            failure_message="模型请求超时",
            created_at=now - timedelta(minutes=1),
        )
        db.add_all([recruiter_task, admin_only_task, recruiter_call, admin_only_call])
        db.commit()
        dependencies = AiObservabilityRouteDependencies(
            session_factory=testing_session,
            recruiter_task_id=recruiter_task.id,
            admin_only_task_id=admin_only_task.id,
            recruiter_call_id=recruiter_call.id,
            admin_only_call_id=admin_only_call.id,
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
async def test_recruiter_sees_only_own_ai_observability_records(
    ai_observability_route_dependencies: AiObservabilityRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")

        summary = await client.get("/ai-observability/summary")
        assert summary.status_code == 200
        assert summary.json()["task_total"] == 1
        assert summary.json()["call_total"] == 1
        assert summary.json()["total_tokens"] == 150

        tasks = await client.get("/ai-observability/tasks")
        assert tasks.status_code == 200
        task_body = tasks.json()
        assert task_body["total"] == 1
        assert task_body["items"][0]["id"] == str(
            ai_observability_route_dependencies.recruiter_task_id
        )
        assert "向量化服务超时" not in str(task_body)

        calls = await client.get("/ai-observability/calls")
        assert calls.status_code == 200
        call_body = calls.json()
        assert call_body["total"] == 1
        assert call_body["items"][0]["id"] == str(
            ai_observability_route_dependencies.recruiter_call_id
        )
        assert "模型请求超时" not in str(call_body)


@pytest.mark.asyncio
async def test_administrator_sees_all_ai_records_and_filters(
    ai_observability_route_dependencies: AiObservabilityRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "administrator")

        summary = await client.get("/ai-observability/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["task_total"] == 2
        assert body["call_total"] == 2
        assert body["failed_task_count"] == 1
        assert body["failed_call_count"] == 1
        assert body["total_tokens"] == 200

        failed_tasks = await client.get("/ai-observability/tasks", params={"status": "failed"})
        assert failed_tasks.status_code == 200
        assert failed_tasks.json()["items"][0]["id"] == str(
            ai_observability_route_dependencies.admin_only_task_id
        )

        jd_calls = await client.get("/ai-observability/calls", params={"scenario": "jd_generation"})
        assert jd_calls.status_code == 200
        assert jd_calls.json()["items"][0]["id"] == str(
            ai_observability_route_dependencies.admin_only_call_id
        )


@pytest.mark.asyncio
async def test_ai_observability_requires_login(
    ai_observability_route_dependencies: AiObservabilityRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ai-observability/summary")
        assert response.status_code == 401
