import json
from collections.abc import Generator

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AiEvaluationResult, AiEvaluationSample
from app.services import ai_client as ai_client_module
from app.services.ai_client import OpenAICompatibleClient
from app.services.ai_evaluation import (
    OfflineEvaluationOptions,
    ensure_default_resume_evaluation_dataset,
    run_offline_resume_evaluation,
)


@pytest.fixture
def live_evaluation_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _activate_samples(
    db: Session,
    *,
    count: int,
) -> list[AiEvaluationSample]:
    dataset = ensure_default_resume_evaluation_dataset(db)
    candidates = [
        sample
        for sample in dataset.samples
        if sample.expected_recommendation == "recommend"
    ][:count]
    assert len(candidates) == count
    for sample in dataset.samples:
        sample.is_active = sample in candidates
    db.commit()
    return candidates


def _draft_from_request(request: httpx.Request) -> dict[str, object]:
    body = json.loads(request.content)
    payload = json.loads(body["messages"][1]["content"])
    segment = payload["segments"][0]
    hard_requirement = payload["criteria"]["hard_requirements"][0]
    dimension = payload["criteria"]["scoring_dimensions"][0]
    evidence = {"segment_key": segment["segment_key"], "quote": segment["text"]}
    return {
        "candidate_profile": {
            "education": [],
            "work_experiences": [],
            "projects": [],
            "skills": [],
            "certifications": [],
            "languages": [],
        },
        "hard_requirements": [
            {
                "requirement_id": hard_requirement["requirement_id"],
                "status": "passed",
                "rationale": "模型判断满足硬性要求。",
                "evidence": [evidence],
            }
        ],
        "dimension_scores": [
            {
                "dimension_id": dimension["dimension_id"],
                "score": 90,
                "rationale": "模型判断匹配度较高。",
                "missing_items": [],
                "evidence": [evidence],
            }
        ],
        "strengths": ["关键岗位能力匹配"],
        "gaps": [],
        "missing_items": [],
        "interview_questions": [],
    }


def _make_client(
    handler: httpx.MockTransport,
) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="https://model.example/v1",
        api_key="test-api-key",
        model="live-test-model",
        timeout_seconds=10,
        max_concurrency=2,
        transport=handler,
    )


@pytest.mark.asyncio
async def test_live_evaluation_calls_model_and_persists_real_metrics(
    live_evaluation_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(_draft_from_request(request))}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        )

    monkeypatch.setattr(
        ai_client_module,
        "get_ai_client",
        lambda: _make_client(httpx.MockTransport(handler)),
    )
    with live_evaluation_session_factory() as db:
        samples = _activate_samples(db, count=1)
        run = await run_offline_resume_evaluation(
            db,
            options=OfflineEvaluationOptions(provider="live"),
        )
        result = db.scalar(select(AiEvaluationResult).where(AiEvaluationResult.run_id == run.id))

    assert result is not None
    assert len(calls) == 1
    assert run.provider == "live"
    assert run.model_name == "live-test-model"
    assert run.status == "succeeded"
    assert run.passed_samples == 1
    assert run.metrics_summary["pass_rate"] == 1.0
    assert run.metrics_summary["error_count"] == 0
    assert result.status == "passed"
    assert result.recommendation_matched is True
    assert result.actual_output["recommendation"] == "recommend"
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.total_tokens == 18
    assert json.loads(calls[0].content)["messages"][1]["content"]
    assert samples[0].case_key in json.loads(calls[0].content)["messages"][1]["content"]


@pytest.mark.asyncio
async def test_live_invalid_model_output_is_error_and_run_continues(
    live_evaluation_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    with live_evaluation_session_factory() as db:
        samples = _activate_samples(db, count=2)
        invalid_case_key = samples[0].case_key

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        candidate_code = payload["candidate_code"]
        attempts.append(candidate_code)
        if candidate_code == invalid_case_key:
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not-json"}}]},
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(_draft_from_request(request))}}],
                "usage": {"prompt_tokens": 13, "completion_tokens": 8, "total_tokens": 21},
            },
        )

    monkeypatch.setattr(
        ai_client_module,
        "get_ai_client",
        lambda: _make_client(httpx.MockTransport(handler)),
    )
    with live_evaluation_session_factory() as db:
        _activate_samples(db, count=2)
        run = await run_offline_resume_evaluation(
            db,
            options=OfflineEvaluationOptions(provider="live"),
        )
        results = db.scalars(
            select(AiEvaluationResult)
            .where(AiEvaluationResult.run_id == run.id)
            .order_by(AiEvaluationResult.created_at)
        ).all()

    assert len(attempts) == 4  # invalid sample retries twice, then the next sample succeeds
    assert run.status == "failed"
    assert run.completed_samples == 2
    assert run.passed_samples == 1
    assert run.failed_samples == 0
    assert run.metrics_summary["error_count"] == 1
    assert run.metrics_summary["error_counts"]["format_error"] == 1
    assert results[0].status == "error"
    assert results[0].failure_code == "ai_response_validation_error"
    assert results[1].status == "passed"


@pytest.mark.asyncio
async def test_default_provider_stays_local_and_does_not_create_ai_client(
    live_evaluation_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called() -> object:
        raise AssertionError("local_deterministic 不应创建 AI 客户端")

    monkeypatch.setattr(ai_client_module, "get_ai_client", fail_if_called)
    with live_evaluation_session_factory() as db:
        _activate_samples(db, count=1)
        run = await run_offline_resume_evaluation(db)

    assert run.provider == "local_deterministic"
    assert run.status == "succeeded"
    assert run.passed_samples == 1


@pytest.mark.asyncio
async def test_live_without_model_configuration_records_error_and_finishes(
    live_evaluation_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("未配置模型时不应发起网络请求")

    client = OpenAICompatibleClient(
        base_url="https://api.example.com/v1",
        api_key="",
        model="",
        timeout_seconds=10,
        max_concurrency=2,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(ai_client_module, "get_ai_client", lambda: client)
    with live_evaluation_session_factory() as db:
        _activate_samples(db, count=1)
        run = await run_offline_resume_evaluation(
            db,
            options=OfflineEvaluationOptions(provider="live"),
        )
        result = db.scalar(select(AiEvaluationResult).where(AiEvaluationResult.run_id == run.id))

    assert network_calls == 0
    assert run.status == "failed"
    assert run.completed_samples == 1
    assert run.passed_samples == 0
    assert run.failed_samples == 0
    assert run.metrics_summary["error_count"] == 1
    assert result is not None
    assert result.status == "error"
    assert result.failure_code == "ai_configuration_error"
