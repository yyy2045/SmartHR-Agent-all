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
class AiEvaluationRouteDependencies:
    session_factory: sessionmaker[Session]


@pytest.fixture
def ai_evaluation_route_dependencies() -> Generator[AiEvaluationRouteDependencies, None, None]:
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
    yield AiEvaluationRouteDependencies(session_factory=testing_session)
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
async def test_admin_runs_offline_evaluation_and_updates_error_case(
    ai_evaluation_route_dependencies: AiEvaluationRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "administrator")

        dataset_response = await client.post("/ai-evaluations/datasets/default-resume")
        assert dataset_response.status_code == 201
        dataset_body = dataset_response.json()
        assert dataset_body["code"] == "resume-analysis-synthetic-v1"

        datasets_response = await client.get("/ai-evaluations/datasets")
        assert datasets_response.status_code == 200
        assert len(datasets_response.json()["items"]) == 1

        run_response = await client.post(
            "/ai-evaluations/runs/offline-resume",
            json={
                "model_name": "deterministic-evaluator",
                "prompt_version": "synthetic-test-v1",
                "forced_error_case_keys": ["BE-01"],
            },
        )
        assert run_response.status_code == 201
        run_body = run_response.json()
        assert run_body["status"] == "failed"
        assert run_body["total_samples"] == 30
        assert run_body["failed_samples"] == 1

        runs_response = await client.get("/ai-evaluations/runs", params={"status": "failed"})
        assert runs_response.status_code == 200
        assert runs_response.json()["total"] == 1

        detail_response = await client.get(f"/ai-evaluations/runs/{run_body['id']}")
        assert detail_response.status_code == 200
        detail_body = detail_response.json()
        assert detail_body["run"]["id"] == run_body["id"]
        assert len(detail_body["results"]) == 30

        error_cases_response = await client.get(
            "/ai-evaluations/error-cases",
            params={"status": "open"},
        )
        assert error_cases_response.status_code == 200
        error_cases = error_cases_response.json()["items"]
        assert len(error_cases) == 2

        update_response = await client.patch(
            f"/ai-evaluations/error-cases/{error_cases[0]['id']}",
            json={"status": "resolved", "remediation_note": "已调整 Prompt 证据要求"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["status"] == "resolved"
        assert update_response.json()["resolved_at"] is not None


@pytest.mark.asyncio
async def test_recruiter_cannot_access_ai_evaluation_admin_routes(
    ai_evaluation_route_dependencies: AiEvaluationRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")

        response = await client.get("/ai-evaluations/datasets")

    assert response.status_code == 403
