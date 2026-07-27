import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

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
    Candidate,
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    CandidateProcess,
    CandidateProcessEvent,
    CandidateProfile,
    InterviewEvaluation,
    InterviewPlanVersion,
    InterviewRound,
    Job,
    JobApplication,
    JobCriteriaVersion,
    RecruiterDecision,
    ResumeDocument,
    ResumeRedaction,
    ResumeTextSegment,
    Role,
    ScreeningBatch,
    ScreeningResult,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass(frozen=True)
class CandidateProcessDependencies:
    job_id: uuid.UUID
    batch_id: uuid.UUID
    document_id: uuid.UUID
    application_id: uuid.UUID
    result_id: uuid.UUID
    session_factory: sessionmaker[Session]


@pytest.fixture
def candidate_process_dependencies() -> Generator[CandidateProcessDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        roles = {
            "administrator": Role(key="administrator", display_name="企业管理员"),
            "recruiter": Role(key="recruiter", display_name="招聘专员"),
            "hiring_manager": Role(key="hiring_manager", display_name="用人经理"),
        }
        user = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        manager = User(
            username="manager",
            password_hash=hash_password("manager-password"),
            display_name="用人经理",
            role_assignments=[UserRole(role=roles["hiring_manager"])],
        )
        other_manager = User(
            username="other-manager",
            password_hash=hash_password("other-manager-password"),
            display_name="其他用人经理",
            role_assignments=[UserRole(role=roles["hiring_manager"])],
        )
        administrator = User(
            username="administrator",
            password_hash=hash_password("administrator-password"),
            display_name="企业管理员",
            role_assignments=[UserRole(role=roles["administrator"])],
        )
        db.add_all([*roles.values(), user, manager, other_manager, administrator])
        db.flush()
        job = Job(
            owner_id=user.id,
            hiring_manager_id=manager.id,
            title="后端工程师",
            department="研发",
            original_jd="JD",
        )
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_by_id=user.id,
        )
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="七月批次",
            status="completed",
            ai_input_mode="raw",
        )
        db.add(batch)
        db.flush()
        candidate = Candidate(phone="13800138000")
        application = JobApplication(candidate=candidate, job_id=job.id)
        document = ResumeDocument(
            batch_id=batch.id,
            candidate=candidate,
            application=application,
            original_filename="candidate.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
            segment_count=1,
        )
        db.add(document)
        db.flush()
        document.text_segments = [
            ResumeTextSegment(
                segment_key="page-1",
                source_type="pdf_page",
                source_index=0,
                page_number=1,
                raw_text="2023.09-2027.06 电话：13800138000",
                normalized_text="2023.09-2027.06 电话：13800138000",
                redacted_text="[PHONE] 电话：[PHONE]",
                sort_order=0,
                redactions=[
                    ResumeRedaction(
                        entity_type="phone",
                        original_text="2023.09-2027.06",
                        replacement_text="[PHONE]",
                        start_offset=0,
                        end_offset=15,
                    ),
                    ResumeRedaction(
                        entity_type="phone",
                        original_text="13800138000",
                        replacement_text="[PHONE]",
                        start_offset=19,
                        end_offset=30,
                    )
                ],
            )
        ]
        profile = CandidateProfile(
            document_id=document.id,
            version_number=1,
            source="ai",
            model_name="stub-model",
            prompt_version="resume-match-v2",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[{"name": "Python", "level": "熟练", "evidence": []}],
            certifications=[],
            languages=[],
        )
        result = ScreeningResult(
            document_id=document.id,
            candidate_profile=profile,
            criteria_version_id=criteria.id,
            analysis_version=1,
            status="completed",
            ai_group="passed",
            total_score=Decimal("88.00"),
            pass_threshold=60,
            hard_requirement_results=[],
            strengths=["Python"],
            gaps=[],
            missing_items=[],
            interview_questions=[],
            model_name="stub-model",
            prompt_version="resume-match-v2",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(result)
        db.commit()

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
    yield CandidateProcessDependencies(
        job_id=job.id,
        batch_id=batch.id,
        document_id=document.id,
        application_id=application.id,
        result_id=result.id,
        session_factory=testing_session,
    )
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(
    client: httpx.AsyncClient,
    username: str = "recruiter",
    password: str = "correct-password",
) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_deep_job_permissions_and_contact_field_scope(
    candidate_process_dependencies: CandidateProcessDependencies,
) -> None:
    dependency = candidate_process_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager", "manager-password")
        board = await manager.get(f"/jobs/{dependency.job_id}/candidate-processes")
        batches = await manager.get(f"/jobs/{dependency.job_id}/batches")
        analysis = await manager.get(
            f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}/documents/"
            f"{dependency.document_id}/analysis"
        )
        raw_detail = await manager.get(
            f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}/documents/"
            f"{dependency.document_id}"
        )
        raw_file = await manager.get(
            f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}/documents/"
            f"{dependency.document_id}/file"
        )
        stage_change = await manager.post(
            f"/jobs/{dependency.job_id}/candidate-processes/"
            f"{dependency.document_id}/stage",
            json={"expected_stage": "unprocessed", "target_stage": "pending"},
        )

    assert board.status_code == 200
    assert board.json()[0]["phone"] is None
    assert batches.status_code == 200
    assert analysis.status_code == 200
    assert raw_detail.status_code == 403
    assert raw_file.status_code == 403
    assert stage_change.status_code == 403

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await login(other, "other-manager", "other-manager-password")
        assert (
            await other.get(f"/jobs/{dependency.job_id}/candidate-processes")
        ).status_code == 404

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as admin:
        await login(admin, "administrator", "administrator-password")
        board = await admin.get(f"/jobs/{dependency.job_id}/candidate-processes")

    assert board.status_code == 200
    assert board.json()[0]["phone"] == "13800138000"


@pytest.mark.asyncio
async def test_board_requires_authentication_and_lists_latest_candidate(
    candidate_process_dependencies: CandidateProcessDependencies,
) -> None:
    dependency = candidate_process_dependencies
    path = f"/jobs/{dependency.job_id}/candidate-processes"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get(path)
        await login(client)
        response = await client.get(path, params={"query": "python", "min_score": 80})

    assert anonymous.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["document_id"] == str(dependency.document_id)
    assert body[0]["phone"] == "13800138000"
    assert body[0]["current_stage"] == "unprocessed"
    assert body[0]["skills"] == ["Python"]
    assert body[0]["batch_name"] == "七月批次"
    assert body[0]["interview_evaluation"] is None


@pytest.mark.asyncio
async def test_board_exposes_compact_interview_evaluation_progress(
    candidate_process_dependencies: CandidateProcessDependencies,
) -> None:
    dependency = candidate_process_dependencies
    with dependency.session_factory() as db:
        user_id = db.scalar(select(User.id).where(User.username == "recruiter"))
        assert user_id is not None
        plan = InterviewPlanVersion(
            job_id=dependency.job_id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=user_id,
            confirmed_at=datetime.now(UTC),
            rounds=[
                InterviewRound(
                    name="技术一面",
                    round_type="technical",
                    duration_minutes=60,
                    pass_threshold=70,
                    focus="系统设计",
                    sort_order=0,
                ),
                InterviewRound(
                    name="HR 面",
                    round_type="hr",
                    duration_minutes=30,
                    pass_threshold=60,
                    focus="发展意愿",
                    sort_order=1,
                ),
                InterviewRound(
                    name="终面",
                    round_type="final",
                    duration_minutes=45,
                    pass_threshold=70,
                    focus="综合判断",
                    sort_order=2,
                ),
            ],
        )
        db.add(plan)
        db.flush()
        schedule = CandidateInterviewSchedule(
            application_id=dependency.application_id,
            plan_version_id=plan.id,
            status="partially_cancelled",
            created_by_id=user_id,
            rounds=[
                CandidateInterviewRound(
                    plan_round_id=plan.rounds[0].id,
                    sort_order=0,
                    scheduled_start_at=datetime.now(UTC),
                    interview_method="onsite",
                    location="3A 会议室",
                    status="scheduled",
                    updated_by_id=user_id,
                    evaluation=InterviewEvaluation(
                        status="submitted",
                        overall_recommendation="recommend",
                        total_score=80,
                        passed=True,
                        submitted_by_id=user_id,
                        submitted_at=datetime.now(UTC),
                    ),
                ),
                CandidateInterviewRound(
                    plan_round_id=plan.rounds[1].id,
                    sort_order=1,
                    scheduled_start_at=datetime.now(UTC),
                    interview_method="phone",
                    status="scheduled",
                    updated_by_id=user_id,
                    evaluation=InterviewEvaluation(status="draft"),
                ),
                CandidateInterviewRound(
                    plan_round_id=plan.rounds[2].id,
                    sort_order=2,
                    scheduled_start_at=datetime.now(UTC),
                    interview_method="online",
                    meeting_url="https://meeting.example.com/final",
                    status="cancelled",
                    updated_by_id=user_id,
                    cancelled_at=datetime.now(UTC),
                ),
            ],
        )
        db.add(schedule)
        db.commit()
        draft_round_id = schedule.rounds[1].id

    path = f"/jobs/{dependency.job_id}/candidate-processes"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.get(path)

    assert response.status_code == 200
    progress = response.json()[0]["interview_evaluation"]
    assert progress == {
        "status": "in_progress",
        "total_rounds": 2,
        "submitted_count": 1,
        "draft_count": 1,
        "pending_count": 0,
        "cancelled_count": 1,
        "action_round_id": str(draft_round_id),
        "action_round_name": "HR 面",
        "action_evaluation_status": "draft",
    }


@pytest.mark.asyncio
async def test_stage_changes_are_concurrency_safe_and_record_timeline(
    candidate_process_dependencies: CandidateProcessDependencies,
) -> None:
    dependency = candidate_process_dependencies
    path = (
        f"/jobs/{dependency.job_id}/candidate-processes/"
        f"{dependency.document_id}/stage"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        shortlisted = await client.post(
            path,
            json={"expected_stage": "unprocessed", "target_stage": "shortlisted"},
        )
        stale = await client.post(
            path,
            json={"expected_stage": "unprocessed", "target_stage": "pending"},
        )
        to_contact = await client.post(
            path,
            json={"expected_stage": "shortlisted", "target_stage": "to_contact"},
        )
        blocked_decision = await client.post(
            f"/jobs/{dependency.job_id}/screening-results/{dependency.result_id}/decisions",
            json={"decision": "pending"},
        )
        timeline = await client.get(
            f"/jobs/{dependency.job_id}/candidate-processes/"
            f"{dependency.document_id}/timeline"
        )

    assert shortlisted.status_code == 200
    assert stale.status_code == 409
    assert to_contact.status_code == 200
    assert blocked_decision.status_code == 409
    assert [item["to_stage"] for item in timeline.json()] == ["shortlisted", "to_contact"]
    with dependency.session_factory() as db:
        process = db.scalar(
            select(CandidateProcess).where(
                CandidateProcess.application_id == dependency.application_id
            )
        )
        assert process is not None
        assert process.current_stage == "to_contact"
        assert db.scalar(select(func.count(CandidateProcessEvent.id))) == 2
        assert db.scalar(select(func.count(RecruiterDecision.id))) == 1
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "candidate_process.stage_changed"
                )
            )
            == 2
        )


@pytest.mark.asyncio
async def test_backward_and_rejection_require_reason_and_terminal_stage_is_locked(
    candidate_process_dependencies: CandidateProcessDependencies,
) -> None:
    dependency = candidate_process_dependencies
    path = (
        f"/jobs/{dependency.job_id}/candidate-processes/"
        f"{dependency.document_id}/stage"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        for expected, target in (
            ("unprocessed", "shortlisted"),
            ("shortlisted", "to_contact"),
            ("to_contact", "contacted"),
        ):
            response = await client.post(
                path,
                json={"expected_stage": expected, "target_stage": target},
            )
            assert response.status_code == 200
        missing_backward_reason = await client.post(
            path,
            json={"expected_stage": "contacted", "target_stage": "to_contact"},
        )
        backward = await client.post(
            path,
            json={
                "expected_stage": "contacted",
                "target_stage": "to_contact",
                "reason": "需要再次确认到岗时间",
            },
        )
        missing_rejection_reason = await client.post(
            path,
            json={"expected_stage": "to_contact", "target_stage": "rejected"},
        )
        rejected = await client.post(
            path,
            json={
                "expected_stage": "to_contact",
                "target_stage": "rejected",
                "reason": "候选人明确不再考虑",
            },
        )
        terminal = await client.post(
            path,
            json={"expected_stage": "rejected", "target_stage": "pending"},
        )

    assert missing_backward_reason.status_code == 422
    assert backward.status_code == 200
    assert missing_rejection_reason.status_code == 422
    assert rejected.status_code == 200
    assert terminal.status_code == 409


def test_deleting_application_cascades_candidate_process(
    candidate_process_dependencies: CandidateProcessDependencies,
) -> None:
    dependency = candidate_process_dependencies
    with dependency.session_factory() as db:
        process = CandidateProcess(
            application_id=dependency.application_id,
            current_stage="to_contact",
            updated_by_id=db.scalar(select(User.id).where(User.username == "recruiter")),
        )
        process.events = [
            CandidateProcessEvent(
                sequence_number=1,
                from_stage="shortlisted",
                to_stage="to_contact",
                operator_id=process.updated_by_id,
            )
        ]
        db.add(process)
        db.commit()
        application = db.get(JobApplication, dependency.application_id)
        assert application is not None
        db.delete(application)
        db.commit()
        assert db.scalar(select(func.count(CandidateProcess.id))) == 0
        assert db.scalar(select(func.count(CandidateProcessEvent.id))) == 0
