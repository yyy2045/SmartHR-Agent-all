import uuid
from collections.abc import Generator
from dataclasses import dataclass

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    AiCallLog,
    Candidate,
    CandidateAgentExchange,
    CandidateAgentReport,
    Job,
    JobApplication,
    Role,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.ai_client import AIRequestMetrics, AIUpstreamError, ToolCall, get_ai_client
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass(frozen=True)
class CandidateAgentRouteDependencies:
    session_factory: sessionmaker[Session]
    job_id: uuid.UUID
    application_id: uuid.UUID


def _answer_arguments() -> dict[str, object]:
    return {
        "answer": "候选人系统重构经验较强，但团队规模仍需核实。",
        "evidence_references": [
            {
                "source_type": "latest_screening",
                "source_label": "AI 初筛证据",
                "quote": "负责核心系统重构",
            }
        ],
        "limitations": ["团队规模未明确"],
        "suggested_follow_up_questions": ["请核实团队规模。"],
    }


def _report_arguments() -> dict[str, object]:
    return {
        "match_assessment": "候选人系统重构经验较强，但团队规模仍需核实。",
        "strengths": ["系统重构经验"],
        "risks": ["团队规模未明确"],
        "overall_recommendation": "next_round",
    }


class StubCandidateAgentClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, object]] = []

    async def chat_complete_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        operation_name: str,
    ) -> tuple[list[ToolCall], str | None, AIRequestMetrics]:
        self.calls.append({"operation_name": operation_name})
        if self.failure is not None:
            raise self.failure
        terminal_name = str(tools[-1]["function"]["name"])
        arguments = _report_arguments() if terminal_name == "submit_report" else _answer_arguments()
        return (
            [ToolCall(id="call-submit", name=terminal_name, arguments=arguments)],
            None,
            AIRequestMetrics(
                model_name="route-test-model",
                retry_count=0,
                duration_ms=50,
                input_tokens=80,
                output_tokens=40,
                total_tokens=120,
            ),
        )


@pytest.fixture
def candidate_agent_route_dependencies() -> Generator[CandidateAgentRouteDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        roles = {
            key: Role(key=key, display_name=key)
            for key in ("administrator", "recruiter", "hiring_manager")
        }
        recruiter = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        other_recruiter = User(
            username="other-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="其他招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        manager = User(
            username="manager",
            password_hash=hash_password("correct-password"),
            display_name="用人经理",
            role_assignments=[UserRole(role=roles["hiring_manager"])],
        )
        administrator = User(
            username="administrator",
            password_hash=hash_password("correct-password"),
            display_name="管理员",
            role_assignments=[UserRole(role=roles["administrator"])],
        )
        db.add_all([*roles.values(), recruiter, other_recruiter, manager, administrator])
        db.flush()
        job = Job(
            owner_id=recruiter.id,
            hiring_manager_id=manager.id,
            title="后端工程师",
            department="研发中心",
            original_jd="负责后端服务设计与研发。",
        )
        candidate = Candidate(
            full_name="候选人A",
            phone="13800138000",
            email="candidate@example.com",
        )
        application = JobApplication(candidate=candidate, job=job)
        db.add_all([job, candidate, application])
        db.commit()
        dependency = CandidateAgentRouteDependencies(
            session_factory=testing_session,
            job_id=job.id,
            application_id=application.id,
        )

    session_store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    def override_session_store() -> SessionStore:
        return session_store

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_session_store
    yield dependency
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str = "recruiter") -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


def sessions_path(dependency: CandidateAgentRouteDependencies) -> str:
    return (
        f"/jobs/{dependency.job_id}/applications/{dependency.application_id}/"
        "candidate-agent/sessions"
    )


@pytest.mark.asyncio
async def test_candidate_agent_session_and_ask_are_idempotent(
    candidate_agent_route_dependencies: CandidateAgentRouteDependencies,
) -> None:
    dependency = candidate_agent_route_dependencies
    stub = StubCandidateAgentClient()
    app.dependency_overrides[get_ai_client] = lambda: stub
    key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        created_session = await client.post(
            sessions_path(dependency),
            json={"title": "候选人风险分析"},
        )
        assert created_session.status_code == 201, created_session.text
        session_id = created_session.json()["id"]
        ask_path = f"{sessions_path(dependency)}/{session_id}/ask"
        created = await client.post(
            ask_path,
            json={"question": "这个候选人的风险是什么？", "idempotency_key": str(key)},
        )
        replayed = await client.post(
            ask_path,
            json={"question": "这个候选人的风险是什么？", "idempotency_key": str(key)},
        )
        detail = await client.get(f"{sessions_path(dependency)}/{session_id}")

    assert created.status_code == 201, created.text
    assert replayed.status_code == 201
    assert replayed.json()["id"] == created.json()["id"]
    assert len(stub.calls) == 1
    body = created.json()
    assert body["status"] == "succeeded"
    assert body["answer"] == "候选人系统重构经验较强，但团队规模仍需核实。"
    assert body["model_name"] == "route-test-model"
    assert detail.status_code == 200
    assert detail.json()["exchanges"][0]["id"] == body["id"]
    with dependency.session_factory() as db:
        assert len(list(db.scalars(select(CandidateAgentExchange)))) == 1
        call = db.scalar(
            select(AiCallLog).where(
                AiCallLog.application_id == dependency.application_id
            )
        )
        assert call is not None
        assert call.scenario == "candidate_qa"
        assert call.total_tokens == 120


@pytest.mark.asyncio
async def test_candidate_agent_ai_failure_returns_manual_fallback(
    candidate_agent_route_dependencies: CandidateAgentRouteDependencies,
) -> None:
    dependency = candidate_agent_route_dependencies
    app.dependency_overrides[get_ai_client] = lambda: StubCandidateAgentClient(
        failure=AIUpstreamError("模型服务暂时不可用")
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        created_session = await client.post(sessions_path(dependency), json={})
        session_id = created_session.json()["id"]
        response = await client.post(
            f"{sessions_path(dependency)}/{session_id}/ask",
            json={"question": "风险是什么？", "idempotency_key": str(uuid.uuid4())},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "manual_fallback"
    assert "AI 问答暂时不可用" in body["answer"]
    assert body["failure_code"] == "AIUpstreamError"
    with dependency.session_factory() as db:
        call = db.scalar(select(AiCallLog).where(AiCallLog.status == "failed"))
        assert call is not None
        assert call.failure_message == "模型服务暂时不可用"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username", "expected_status"),
    [("manager", 403), ("administrator", 201), ("other-recruiter", 404)],
)
async def test_candidate_agent_respects_role_and_data_scope(
    candidate_agent_route_dependencies: CandidateAgentRouteDependencies,
    username: str,
    expected_status: int,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, username)
        response = await client.post(sessions_path(candidate_agent_route_dependencies), json={})

    assert response.status_code == expected_status


def report_path(dependency: CandidateAgentRouteDependencies) -> str:
    return (
        f"/jobs/{dependency.job_id}/applications/{dependency.application_id}/"
        "candidate-agent/report"
    )


@pytest.mark.asyncio
async def test_candidate_agent_report_generate_and_fetch_are_idempotent(
    candidate_agent_route_dependencies: CandidateAgentRouteDependencies,
) -> None:
    dependency = candidate_agent_route_dependencies
    stub = StubCandidateAgentClient()
    app.dependency_overrides[get_ai_client] = lambda: stub
    key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        created = await client.post(
            report_path(dependency),
            json={"idempotency_key": str(key)},
        )
        replayed = await client.post(
            report_path(dependency),
            json={"idempotency_key": str(key)},
        )
        fetched = await client.get(report_path(dependency))

    assert created.status_code == 201, created.text
    assert replayed.status_code == 201
    assert replayed.json()["id"] == created.json()["id"]
    assert len(stub.calls) == 1
    body = created.json()
    assert body["status"] == "succeeded"
    assert body["match_assessment"] == "候选人系统重构经验较强，但团队规模仍需核实。"
    assert body["overall_recommendation"] == "next_round"
    assert body["model_name"] == "route-test-model"
    assert len(body["tool_trajectory"]) == 1
    assert len(body["ai_call_log_ids"]) == 1
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]
    with dependency.session_factory() as db:
        assert len(list(db.scalars(select(CandidateAgentReport)))) == 1
        call = db.scalar(
            select(AiCallLog).where(AiCallLog.scenario == "candidate_assessment")
        )
        assert call is not None
        assert call.total_tokens == 120


@pytest.mark.asyncio
async def test_candidate_agent_report_ai_failure_returns_manual_fallback(
    candidate_agent_route_dependencies: CandidateAgentRouteDependencies,
) -> None:
    dependency = candidate_agent_route_dependencies
    app.dependency_overrides[get_ai_client] = lambda: StubCandidateAgentClient(
        failure=AIUpstreamError("模型服务暂时不可用")
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.post(
            report_path(dependency),
            json={"idempotency_key": str(uuid.uuid4())},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "manual_fallback"
    assert "研判报告暂时不可用" in body["match_assessment"]
    assert body["failure_code"] == "AIUpstreamError"
    with dependency.session_factory() as db:
        call = db.scalar(select(AiCallLog).where(AiCallLog.status == "failed"))
        assert call is not None
        assert call.failure_message == "模型服务暂时不可用"
