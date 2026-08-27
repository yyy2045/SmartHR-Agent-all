import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import User
from app.schemas.candidate_agent import CandidateAgentAnswerDraft
from app.services.ai_client import AIRequestMetrics, AIUpstreamError, ToolCall
from app.services.candidate_agent_runtime import (
    CandidateAgentLoopError,
    run_candidate_agent_loop,
)


@pytest.fixture
def runtime_session_factory() -> Generator[sessionmaker[Session], None, None]:
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


class ScriptedToolClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    async def chat_complete_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        operation_name: str,
    ) -> tuple[list[ToolCall], str | None, AIRequestMetrics]:
        index = self.call_count
        self.call_count += 1
        if index >= len(self._responses):
            raise AssertionError("脚本化客户端响应耗尽")
        item = self._responses[index]
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[return-value]


def _metrics() -> AIRequestMetrics:
    return AIRequestMetrics(
        model_name="test-model",
        retry_count=0,
        duration_ms=10,
        input_tokens=10,
        output_tokens=10,
        total_tokens=20,
    )


def _valid_answer() -> dict[str, object]:
    return {
        "answer": "候选人系统重构经验较强。",
        "evidence_references": [
            {"source_type": "latest_screening", "source_label": "AI 初筛"}
        ],
    }


def _run(db: Session, client: ScriptedToolClient):
    return run_candidate_agent_loop(
        db=db,
        context={},
        goal="answer",
        question="风险是什么？",
        actor=User(id=uuid.uuid4()),  # type: ignore[call-arg]
        job_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        scenario="candidate_qa",
        prompt_snapshot=None,
        ai_client=client,
        response_type=CandidateAgentAnswerDraft,
    )


@pytest.mark.asyncio
async def test_loop_gathers_tool_then_submits(
    runtime_session_factory: sessionmaker[Session],
) -> None:
    client = ScriptedToolClient(
        [
            (
                [ToolCall(id="c1", name="get_latest_screening", arguments={})],
                None,
                _metrics(),
            ),
            (
                [ToolCall(id="c2", name="submit_answer", arguments=_valid_answer())],
                None,
                _metrics(),
            ),
        ]
    )

    with runtime_session_factory() as db:
        result = await _run(db, client)

    assert result.draft.answer == "候选人系统重构经验较强。"
    assert result.steps == 2
    assert len(result.ai_call_logs) == 2
    assert [item["name"] for item in result.tool_trajectory] == [
        "get_latest_screening",
        "submit_answer",
    ]
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_loop_raises_after_max_steps(
    runtime_session_factory: sessionmaker[Session],
) -> None:
    responses = [
        (
            [ToolCall(id=f"c{i}", name="get_latest_screening", arguments={})],
            None,
            _metrics(),
        )
        for i in range(6)
    ]
    client = ScriptedToolClient(responses)

    with runtime_session_factory() as db:
        with pytest.raises(CandidateAgentLoopError) as error:
            await _run(db, client)

    assert error.value.code == "max_steps"
    assert client.call_count == 6


@pytest.mark.asyncio
async def test_loop_reraises_ai_error(
    runtime_session_factory: sessionmaker[Session],
) -> None:
    client = ScriptedToolClient([AIUpstreamError("模型服务暂时不可用")])

    with runtime_session_factory() as db:
        with pytest.raises(AIUpstreamError):
            await _run(db, client)


@pytest.mark.asyncio
async def test_loop_repairs_invalid_submit(
    runtime_session_factory: sessionmaker[Session],
) -> None:
    client = ScriptedToolClient(
        [
            (
                [ToolCall(id="c1", name="submit_answer", arguments={"answer": ""})],
                None,
                _metrics(),
            ),
            (
                [ToolCall(id="c2", name="submit_answer", arguments=_valid_answer())],
                None,
                _metrics(),
            ),
        ]
    )

    with runtime_session_factory() as db:
        result = await _run(db, client)

    assert result.draft.answer == "候选人系统重构经验较强。"
    assert [item["status"] for item in result.tool_trajectory] == [
        "failed",
        "succeeded",
    ]
    assert result.tool_trajectory[0]["name"] == "submit_answer"
    assert client.call_count == 2
