import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    Candidate,
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    EvidenceCitation,
    InterviewDimensionRating,
    InterviewEvaluation,
    InterviewPlanVersion,
    InterviewQuestion,
    InterviewQuestionResponse,
    InterviewReport,
    InterviewReportVersion,
    InterviewRound,
    InterviewScoreDimension,
    Job,
    JobApplication,
    JobCriteriaVersion,
    RecruiterDecision,
    ResumeDocument,
    Role,
    ScreeningBatch,
    ScreeningResult,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class InterviewReportDependencies:
    session_factory: sessionmaker[Session]
    job_id: uuid.UUID
    application_id: uuid.UUID
    latest_screening_id: uuid.UUID
    submitted_evaluation_id: uuid.UUID


@pytest.fixture
def interview_report_dependencies() -> Generator[InterviewReportDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    now = datetime.now(UTC).replace(microsecond=0)
    with testing_session() as db:
        roles = {
            key: Role(key=key, display_name=display_name)
            for key, display_name in {
                "administrator": "管理员",
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
            }.items()
        }
        recruiter = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="测试招聘专员",
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
            title="高级后端工程师",
            department="研发中心",
            original_jd="负责核心服务设计与开发。",
        )
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            pass_threshold=70,
        )
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="面试报告候选人批次",
            status="completed",
        )
        db.add(batch)
        db.flush()
        candidate = Candidate(full_name="候选人A")
        application = JobApplication(candidate=candidate, job_id=job.id)
        document = ResumeDocument(
            batch_id=batch.id,
            candidate=candidate,
            application=application,
            original_filename="候选人A.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            size_bytes=1_024,
            status="completed",
        )
        db.add(document)
        db.flush()

        old_screening = ScreeningResult(
            document_id=document.id,
            criteria_version_id=criteria.id,
            analysis_version=1,
            status="completed",
            ai_group="low_match",
            total_score=65,
            pass_threshold=70,
            strengths=["基础扎实"],
            gaps=["架构经验不足"],
            missing_items=[],
            model_name="test-model",
            prompt_version="v1",
            started_at=now - timedelta(hours=4),
            completed_at=now - timedelta(hours=3),
        )
        latest_screening = ScreeningResult(
            document_id=document.id,
            criteria_version_id=criteria.id,
            analysis_version=2,
            status="completed",
            ai_group="passed",
            total_score=86,
            pass_threshold=70,
            strengths=["系统设计证据充分"],
            gaps=["带团队经验仍需核实"],
            missing_items=["团队规模"],
            model_name="test-model",
            prompt_version="v2",
            started_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1),
            evidence_citations=[
                EvidenceCitation(
                    subject_type="profile",
                    subject_key="work_experience",
                    segment_key="S0001",
                    quote="负责核心交易系统重构",
                    source_type="raw",
                    sort_order=0,
                )
            ],
        )
        processing_screening = ScreeningResult(
            document_id=document.id,
            criteria_version_id=criteria.id,
            analysis_version=3,
            status="processing",
            pass_threshold=70,
            model_name="test-model",
            prompt_version="v3",
            started_at=now,
        )
        completed_without_timestamp = ScreeningResult(
            document_id=document.id,
            criteria_version_id=criteria.id,
            analysis_version=4,
            status="completed",
            ai_group="low_match",
            total_score=60,
            pass_threshold=70,
            model_name="test-model",
            prompt_version="v4",
            started_at=now,
            completed_at=None,
        )
        db.add_all(
            [
                old_screening,
                latest_screening,
                processing_screening,
                completed_without_timestamp,
            ]
        )
        db.flush()
        db.add(
            RecruiterDecision(
                screening_result_id=latest_screening.id,
                operator_id=recruiter.id,
                sequence_number=1,
                previous_decision="unprocessed",
                decision="shortlisted",
                reason="人工复核通过",
            )
        )

        question = InterviewQuestion(
            question_text="请介绍一次系统重构",
            evaluation_guide="关注取舍和结果",
            sort_order=0,
        )
        dimension = InterviewScoreDimension(
            name="系统设计",
            description="架构设计与权衡能力",
            weight_percent=100,
            sort_order=0,
        )
        technical_round = InterviewRound(
            name="技术一面",
            round_type="technical",
            duration_minutes=60,
            pass_threshold=70,
            focus="系统设计",
            sort_order=0,
            questions=[question],
            scoring_dimensions=[dimension],
        )
        business_round = InterviewRound(
            name="业务二面",
            round_type="business",
            duration_minutes=60,
            pass_threshold=70,
            focus="业务理解",
            sort_order=1,
        )
        hr_round = InterviewRound(
            name="HR 面",
            round_type="hr",
            duration_minutes=30,
            pass_threshold=60,
            focus="发展意愿",
            sort_order=2,
        )
        plan = InterviewPlanVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=recruiter.id,
            confirmed_at=now,
            rounds=[technical_round, business_round, hr_round],
        )
        db.add(plan)
        db.flush()
        schedule = CandidateInterviewSchedule(
            application_id=application.id,
            plan_version_id=plan.id,
            status="partially_cancelled",
            created_by_id=recruiter.id,
            rounds=[
                CandidateInterviewRound(
                    plan_round_id=technical_round.id,
                    sort_order=0,
                    scheduled_start_at=now - timedelta(days=2),
                    interview_method="online",
                    meeting_url="https://meeting.example.com/technical",
                    status="scheduled",
                    updated_by_id=recruiter.id,
                ),
                CandidateInterviewRound(
                    plan_round_id=business_round.id,
                    sort_order=1,
                    scheduled_start_at=now + timedelta(days=1),
                    interview_method="online",
                    meeting_url="https://meeting.example.com/business",
                    status="scheduled",
                    updated_by_id=recruiter.id,
                ),
                CandidateInterviewRound(
                    plan_round_id=hr_round.id,
                    sort_order=2,
                    scheduled_start_at=now + timedelta(days=2),
                    interview_method="phone",
                    status="cancelled",
                    cancelled_at=now,
                    updated_by_id=recruiter.id,
                ),
            ],
        )
        db.add(schedule)
        db.flush()
        submitted_evaluation = InterviewEvaluation(
            candidate_round_id=schedule.rounds[0].id,
            status="submitted",
            overall_recommendation="recommend",
            overall_comment="系统设计能力达到岗位要求。",
            total_score=84,
            passed=True,
            submitted_by_id=recruiter.id,
            submitted_at=now - timedelta(days=1),
            question_responses=[
                InterviewQuestionResponse(
                    question_id=question.id,
                    answer_summary="完成单体到服务化的渐进式重构。",
                    evidence="能够解释灰度、回滚和数据一致性取舍。",
                )
            ],
            dimension_ratings=[
                InterviewDimensionRating(
                    dimension_id=dimension.id,
                    score=4,
                    evidence="方案完整且有量化结果。",
                )
            ],
        )
        draft_evaluation = InterviewEvaluation(
            candidate_round_id=schedule.rounds[1].id,
            status="draft",
            overall_comment="尚未完成",
        )
        db.add_all([submitted_evaluation, draft_evaluation])
        db.commit()
        dependency = InterviewReportDependencies(
            session_factory=testing_session,
            job_id=job.id,
            application_id=application.id,
            latest_screening_id=latest_screening.id,
            submitted_evaluation_id=submitted_evaluation.id,
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


def context_path(dependency: InterviewReportDependencies) -> str:
    return (
        f"/jobs/{dependency.job_id}/applications/{dependency.application_id}/"
        "interview-report/context"
    )


@pytest.mark.asyncio
async def test_report_context_requires_authentication(
    interview_report_dependencies: InterviewReportDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(context_path(interview_report_dependencies))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_report_context_uses_latest_completed_screening_and_submitted_evaluations(
    interview_report_dependencies: InterviewReportDependencies,
) -> None:
    dependency = interview_report_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.get(context_path(dependency))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["application_id"] == str(dependency.application_id)
    assert body["candidate_name"] == "候选人A"
    assert body["latest_screening"]["id"] == str(dependency.latest_screening_id)
    assert body["latest_screening"]["analysis_version"] == 2
    assert body["latest_screening"]["current_decision"] == "shortlisted"
    assert body["latest_screening"]["citations"][0]["quote"] == "负责核心交易系统重构"
    assert [item["evaluation_id"] for item in body["submitted_evaluations"]] == [
        str(dependency.submitted_evaluation_id)
    ]
    assert body["submitted_evaluations"][0]["question_responses"][0][
        "question_text"
    ] == "请介绍一次系统重构"
    assert body["submitted_evaluations"][0]["dimension_ratings"][0][
        "dimension_name"
    ] == "系统设计"
    assert [(item["round_name"], item["reason"]) for item in body["missing_rounds"]] == [
        ("业务二面", "not_submitted"),
        ("HR 面", "cancelled"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username", "expected_status"),
    [("manager", 200), ("administrator", 200), ("other-recruiter", 404)],
)
async def test_report_context_respects_job_data_scope(
    interview_report_dependencies: InterviewReportDependencies,
    username: str,
    expected_status: int,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, username)
        response = await client.get(context_path(interview_report_dependencies))

    assert response.status_code == expected_status


@pytest.mark.asyncio
async def test_report_context_allows_missing_screening_and_evaluations(
    interview_report_dependencies: InterviewReportDependencies,
) -> None:
    dependency = interview_report_dependencies
    with dependency.session_factory() as db:
        db.execute(delete(InterviewEvaluation))
        db.execute(delete(ScreeningResult))
        db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.get(context_path(dependency))

    assert response.status_code == 200
    body = response.json()
    assert body["latest_screening"] is None
    assert body["submitted_evaluations"] == []
    assert [item["reason"] for item in body["missing_rounds"]] == [
        "not_submitted",
        "not_submitted",
        "cancelled",
    ]


def test_report_model_enforces_application_and_version_idempotency(
    interview_report_dependencies: InterviewReportDependencies,
) -> None:
    dependency = interview_report_dependencies
    idempotency_key = uuid.uuid4()
    with dependency.session_factory() as db:
        recruiter = db.scalar(select(User).where(User.username == "recruiter"))
        assert recruiter is not None
        report = InterviewReport(
            application_id=dependency.application_id,
            status="draft",
            current_version_number=1,
            created_by_id=recruiter.id,
            versions=[
                InterviewReportVersion(
                    version_number=1,
                    idempotency_key=idempotency_key,
                    generation_mode="manual",
                    conclusion=None,
                    executive_summary="",
                    strengths=[],
                    concerns=[],
                    follow_up_actions=[],
                    evaluation_ids=[],
                    evidence_snapshot={},
                    missing_rounds=[],
                    created_by_id=recruiter.id,
                    created_by_username=recruiter.username,
                    created_by_display_name=recruiter.display_name,
                )
            ],
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        assert report.current_version.version_number == 1

        report.versions.append(
            InterviewReportVersion(
                version_number=2,
                idempotency_key=idempotency_key,
                generation_mode="manual",
                executive_summary="重复请求",
                strengths=[],
                concerns=[],
                follow_up_actions=[],
                evaluation_ids=[],
                evidence_snapshot={},
                missing_rounds=[],
                created_by_id=recruiter.id,
                created_by_username=recruiter.username,
                created_by_display_name=recruiter.display_name,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    with dependency.session_factory() as db:
        duplicate_report = InterviewReport(
            application_id=dependency.application_id,
            status="draft",
            current_version_number=1,
            created_by_id=None,
        )
        db.add(duplicate_report)
        with pytest.raises(IntegrityError):
            db.commit()
