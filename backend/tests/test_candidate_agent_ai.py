import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AiCallLog, User
from app.schemas.candidate_agent import CandidateAgentAnswerDraft
from app.services.ai_client import AIRequestMetrics, AIUpstreamError
from app.services.candidate_agent_ai import generate_candidate_agent_answer
from app.services.security import hash_password


@pytest.fixture
def candidate_agent_ai_session() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


class FakeCandidateAgentClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.payloads: list[dict[str, object]] = []

    async def answer_candidate_question_with_metrics(
        self,
        payload: dict[str, object],
        *,
        prompt_template: object | None = None,
    ) -> tuple[CandidateAgentAnswerDraft, AIRequestMetrics]:
        self.payloads.append(payload)
        if self.fail:
            raise AIUpstreamError("模拟 AI 服务失败")
        return (
            CandidateAgentAnswerDraft(
                answer="候选人有核心系统经验，但团队规模信息不足。",
                evidence_references=[
                    {
                        "source_type": "latest_screening",
                        "source_label": "AI 初筛证据",
                        "quote": "负责核心系统重构",
                    }
                ],
                limitations=["团队规模未明确"],
                suggested_follow_up_questions=["请补充团队规模和职责边界。"],
            ),
            AIRequestMetrics(
                model_name="test-model",
                retry_count=1,
                duration_ms=123,
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
            ),
        )


def _actor(db: Session) -> User:
    user = User(
        username="recruiter",
        password_hash=hash_password("correct-password"),
        display_name="招聘专员",
    )
    db.add(user)
    db.flush()
    return user


@pytest.mark.asyncio
async def test_candidate_agent_ai_records_success_call_log(
    candidate_agent_ai_session: sessionmaker[Session],
) -> None:
    with candidate_agent_ai_session() as db:
        actor = _actor(db)
        job_id = uuid.uuid4()
        application_id = uuid.uuid4()
        fake_client = FakeCandidateAgentClient()

        result = await generate_candidate_agent_answer(
            db,
            question="这个候选人的风险是什么？",
            context={"job": {"title": "后端工程师"}},
            actor=actor,
            job_id=job_id,
            application_id=application_id,
            ai_client=fake_client,
        )

        call = db.get(AiCallLog, result.ai_call_log.id)
        assert call is not None
        assert call.scenario == "candidate_qa"
        assert call.status == "succeeded"
        assert call.resource_type == "job_application"
        assert call.resource_id == application_id
        assert call.job_id == job_id
        assert call.application_id == application_id
        assert call.invoked_by_id == actor.id
        assert call.model_name == "test-model"
        assert call.total_tokens == 150
        assert result.prompt_version == "candidate-qa-v1"
        assert fake_client.payloads[0]["decision_boundary"]["ai_must_not"]


@pytest.mark.asyncio
async def test_candidate_agent_ai_records_failed_call_log(
    candidate_agent_ai_session: sessionmaker[Session],
) -> None:
    with candidate_agent_ai_session() as db:
        actor = _actor(db)
        application_id = uuid.uuid4()

        with pytest.raises(AIUpstreamError):
            await generate_candidate_agent_answer(
                db,
                question="这个候选人的风险是什么？",
                context={"job": {"title": "后端工程师"}},
                actor=actor,
                job_id=uuid.uuid4(),
                application_id=application_id,
                ai_client=FakeCandidateAgentClient(fail=True),
            )

        call = db.scalar(select(AiCallLog).where(AiCallLog.application_id == application_id))
        assert call is not None
        assert call.status == "failed"
        assert call.scenario == "candidate_qa"
        assert call.failure_code == "AIUpstreamError"
        assert "模拟 AI 服务失败" in (call.failure_message or "")
