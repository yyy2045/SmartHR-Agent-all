import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    InterviewDimensionRating,
    InterviewEvaluation,
    InterviewPlanVersion,
    InterviewQuestion,
    InterviewQuestionResponse,
    InterviewRound,
    InterviewScoreAnchor,
    InterviewScoreDimension,
    Job,
    JobCriteriaVersion,
    ResumeDocument,
    ScreeningBatch,
    User,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class EvaluationDependencies:
    session_factory: sessionmaker[Session]
    job_id: uuid.UUID
    document_id: uuid.UUID
    round_id: uuid.UUID
    cancelled_round_id: uuid.UUID
    question_ids: list[uuid.UUID]
    dimension_ids: list[uuid.UUID]


def score_anchors(name: str) -> list[InterviewScoreAnchor]:
    return [
        InterviewScoreAnchor(score_value=score, description=f"{name} {score} 分标准")
        for score in range(1, 6)
    ]


@pytest.fixture
def evaluation_dependencies() -> Generator[EvaluationDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        recruiter = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="测试招聘专员",
        )
        other_recruiter = User(
            username="other-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="其他招聘专员",
        )
        db.add_all([recruiter, other_recruiter])
        db.flush()
        job = Job(
            owner_id=recruiter.id,
            title="高级后端工程师",
            department="研发中心",
            original_jd="负责核心服务设计与开发。",
        )
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(job_id=job.id, version_number=1, status="confirmed")
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="面试候选人批次",
            status="completed",
        )
        db.add(batch)
        db.flush()
        document = ResumeDocument(
            batch_id=batch.id,
            original_filename="候选人A.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            size_bytes=1_024,
            status="completed",
        )
        technical_round = InterviewRound(
            name="技术一面",
            round_type="technical",
            duration_minutes=60,
            pass_threshold=70,
            focus="系统设计与工程能力",
            sort_order=0,
            questions=[
                InterviewQuestion(
                    question_text="请介绍一个高并发系统设计案例",
                    evaluation_guide="关注容量估算和取舍",
                    sort_order=0,
                ),
                InterviewQuestion(
                    question_text="请说明一次线上故障复盘",
                    evaluation_guide="关注定位过程和改进措施",
                    sort_order=1,
                ),
            ],
            scoring_dimensions=[
                InterviewScoreDimension(
                    name="系统设计",
                    description="架构设计与权衡能力",
                    weight_percent=60,
                    sort_order=0,
                    anchors=score_anchors("系统设计"),
                ),
                InterviewScoreDimension(
                    name="问题解决",
                    description="分析和解决复杂问题的能力",
                    weight_percent=40,
                    sort_order=1,
                    anchors=score_anchors("问题解决"),
                ),
            ],
        )
        cancelled_plan_round = InterviewRound(
            name="HR 面",
            round_type="hr",
            duration_minutes=30,
            pass_threshold=60,
            focus="发展意愿",
            sort_order=1,
            questions=[
                InterviewQuestion(
                    question_text="请说明职业规划",
                    evaluation_guide="关注稳定性",
                    sort_order=0,
                )
            ],
            scoring_dimensions=[
                InterviewScoreDimension(
                    name="发展意愿",
                    description="岗位发展匹配度",
                    weight_percent=100,
                    sort_order=0,
                    anchors=score_anchors("发展意愿"),
                )
            ],
        )
        plan = InterviewPlanVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=recruiter.id,
            confirmed_at=datetime.now(UTC),
            rounds=[technical_round, cancelled_plan_round],
        )
        db.add_all([document, plan])
        db.flush()
        start_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
        schedule = CandidateInterviewSchedule(
            document_id=document.id,
            plan_version_id=plan.id,
            status="partially_cancelled",
            created_by_id=recruiter.id,
            rounds=[
                CandidateInterviewRound(
                    plan_round_id=technical_round.id,
                    sort_order=0,
                    scheduled_start_at=start_at,
                    interview_method="onsite",
                    location="3A 会议室",
                    status="scheduled",
                    updated_by_id=recruiter.id,
                ),
                CandidateInterviewRound(
                    plan_round_id=cancelled_plan_round.id,
                    sort_order=1,
                    scheduled_start_at=start_at + timedelta(days=1),
                    interview_method="phone",
                    status="cancelled",
                    updated_by_id=recruiter.id,
                    cancelled_at=datetime.now(UTC),
                ),
            ],
        )
        db.add(schedule)
        db.commit()
        dependency = EvaluationDependencies(
            session_factory=testing_session,
            job_id=job.id,
            document_id=document.id,
            round_id=schedule.rounds[0].id,
            cancelled_round_id=schedule.rounds[1].id,
            question_ids=[item.id for item in technical_round.questions],
            dimension_ids=[item.id for item in technical_round.scoring_dimensions],
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


def evaluation_path(dependency: EvaluationDependencies, round_id: uuid.UUID | None = None) -> str:
    return (
        f"/jobs/{dependency.job_id}/candidate-processes/{dependency.document_id}/"
        f"interview-schedule/rounds/{round_id or dependency.round_id}/evaluation"
    )


def complete_payload(dependency: EvaluationDependencies) -> dict[str, object]:
    return {
        "overall_recommendation": "recommend",
        "overall_comment": "技术基础扎实，建议进入下一轮。",
        "question_responses": [
            {
                "question_id": str(dependency.question_ids[0]),
                "answer_summary": "设计了分层缓存和异步削峰方案。",
                "evidence": "能够给出十万 QPS 容量估算和缓存击穿处理细节。",
            },
            {
                "question_id": str(dependency.question_ids[1]),
                "answer_summary": "通过指标和链路追踪定位连接池耗尽。",
                "evidence": "说明了复盘后的告警阈值和压测门禁。",
            },
        ],
        "dimension_ratings": [
            {
                "dimension_id": str(dependency.dimension_ids[0]),
                "score": 4,
                "evidence": "架构分层清晰，能够解释一致性与性能取舍。",
            },
            {
                "dimension_id": str(dependency.dimension_ids[1]),
                "score": 3,
                "evidence": "定位过程完整，但风险预案深度一般。",
            },
        ],
    }


@pytest.mark.asyncio
async def test_interview_evaluation_requires_authentication(
    evaluation_dependencies: EvaluationDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(evaluation_path(evaluation_dependencies))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_evaluation_draft_submit_score_lock_and_audit(
    evaluation_dependencies: EvaluationDependencies,
) -> None:
    dependency = evaluation_dependencies
    path = evaluation_path(dependency)
    partial_payload = {
        "overall_recommendation": None,
        "overall_comment": "先记录第一部分。",
        "question_responses": [
            {
                "question_id": str(dependency.question_ids[0]),
                "answer_summary": "已回答系统设计问题。",
                "evidence": "给出了容量估算。",
            }
        ],
        "dimension_ratings": [],
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        empty = await client.get(path)
        created = await client.put(path, json=partial_payload)
        incomplete_submit = await client.post(f"{path}/submit")
        updated = await client.put(path, json=complete_payload(dependency))
        submitted = await client.post(f"{path}/submit")
        locked = await client.put(path, json=complete_payload(dependency))
        repeated_submit = await client.post(f"{path}/submit")

    assert empty.status_code == 200
    assert empty.json()["evaluation"] is None
    assert [item["question_text"] for item in empty.json()["questions"]] == [
        "请介绍一个高并发系统设计案例",
        "请说明一次线上故障复盘",
    ]
    assert created.status_code == 200
    assert created.json()["evaluation"]["status"] == "draft"
    assert incomplete_submit.status_code == 422
    assert incomplete_submit.json()["detail"] == "请选择总体建议"
    assert updated.status_code == 200
    assert len(updated.json()["evaluation"]["question_responses"]) == 2
    assert submitted.status_code == 200
    submitted_evaluation = submitted.json()["evaluation"]
    assert submitted_evaluation["status"] == "submitted"
    assert submitted_evaluation["total_score"] == 72.0
    assert submitted_evaluation["passed"] is True
    assert submitted_evaluation["submitted_by_id"] is not None
    assert submitted_evaluation["submitted_at"] is not None
    assert locked.status_code == 409
    assert repeated_submit.status_code == 409

    with dependency.session_factory() as db:
        assert db.scalar(select(func.count(InterviewEvaluation.id))) == 1
        assert db.scalar(select(func.count(InterviewQuestionResponse.id))) == 2
        assert db.scalar(select(func.count(InterviewDimensionRating.id))) == 2
        actions = list(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.target_type == "interview_evaluation"
                )
            )
        )
        submitted_log = db.scalar(
            select(AuditLog).where(AuditLog.action == "interview_evaluation.submitted")
        )

    assert actions.count("interview_evaluation.created") == 1
    assert actions.count("interview_evaluation.updated") == 1
    assert actions.count("interview_evaluation.submitted") == 1
    assert submitted_log is not None
    assert submitted_log.details["total_score"] == 72.0
    assert submitted_log.details["passed"] is True


@pytest.mark.asyncio
async def test_evaluation_rejects_wrong_references_cancelled_round_and_archived_job(
    evaluation_dependencies: EvaluationDependencies,
) -> None:
    dependency = evaluation_dependencies
    path = evaluation_path(dependency)
    invalid_payload = complete_payload(dependency)
    invalid_payload["question_responses"][0]["question_id"] = str(uuid.uuid4())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        invalid_reference = await client.put(path, json=invalid_payload)
        cancelled = await client.put(
            evaluation_path(dependency, dependency.cancelled_round_id),
            json={"question_responses": [], "dimension_ratings": []},
        )
        await client.post(f"/jobs/{dependency.job_id}/archive")
        readable = await client.get(path)
        archived_write = await client.put(path, json=complete_payload(dependency))

    assert invalid_reference.status_code == 422
    assert invalid_reference.json()["detail"] == "评价包含不属于当前面试轮次的问题"
    assert cancelled.status_code == 409
    assert readable.status_code == 200
    assert archived_write.status_code == 409


@pytest.mark.asyncio
async def test_cross_owner_evaluation_access_is_hidden(
    evaluation_dependencies: EvaluationDependencies,
) -> None:
    dependency = evaluation_dependencies
    path = evaluation_path(dependency)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "other-recruiter")
        hidden_get = await client.get(path)
        hidden_put = await client.put(path, json=complete_payload(dependency))
        hidden_submit = await client.post(f"{path}/submit")

    assert hidden_get.status_code == 404
    assert hidden_put.status_code == 404
    assert hidden_submit.status_code == 404
