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
    CandidateDuplicateReview,
    CandidateInterviewSchedule,
    CandidateProcess,
    InterviewPlanVersion,
    Job,
    JobApplication,
    JobCriteriaVersion,
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


@dataclass(frozen=True)
class CandidateMergeDependencies:
    session_factory: sessionmaker[Session]
    review_id: uuid.UUID
    target_candidate_id: uuid.UUID
    source_candidate_id: uuid.UUID
    target_application_id: uuid.UUID
    conflicting_application_id: uuid.UUID
    movable_application_id: uuid.UUID


def _screening_result(document: ResumeDocument, criteria_id: uuid.UUID) -> ScreeningResult:
    return ScreeningResult(
        document=document,
        criteria_version_id=criteria_id,
        analysis_version=1,
        status="completed",
        ai_group="passed",
        total_score=Decimal("80.00"),
        pass_threshold=60,
        hard_requirement_results=[],
        strengths=[],
        gaps=[],
        missing_items=[],
        interview_questions=[],
        model_name="stub-model",
        prompt_version="resume-match-v2",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


@pytest.fixture
def candidate_merge_dependencies() -> Generator[CandidateMergeDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        roles = {
            "recruiter": Role(key="recruiter", display_name="招聘专员"),
            "hiring_manager": Role(key="hiring_manager", display_name="用人经理"),
        }
        recruiter = User(
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
        db.add_all([*roles.values(), recruiter, manager])
        db.flush()
        first_job = Job(
            owner_id=recruiter.id,
            hiring_manager_id=manager.id,
            title="后端工程师",
            department="研发",
            original_jd="JD",
        )
        second_job = Job(
            owner_id=recruiter.id,
            hiring_manager_id=manager.id,
            title="平台工程师",
            department="研发",
            original_jd="JD",
        )
        db.add_all([first_job, second_job])
        db.flush()
        first_criteria = JobCriteriaVersion(
            job_id=first_job.id, version_number=1, status="confirmed"
        )
        second_criteria = JobCriteriaVersion(
            job_id=second_job.id, version_number=1, status="confirmed"
        )
        db.add_all([first_criteria, second_criteria])
        db.flush()
        first_batch = ScreeningBatch(
            job_id=first_job.id,
            criteria_version_id=first_criteria.id,
            name="后端批次",
            status="completed",
        )
        second_batch = ScreeningBatch(
            job_id=second_job.id,
            criteria_version_id=second_criteria.id,
            name="平台批次",
            status="completed",
        )
        db.add_all([first_batch, second_batch])
        db.flush()

        target = Candidate(full_name="张三")
        source = Candidate(
            full_name="张 三",
            phone="13800138000",
            phone_normalized="13800138000",
        )
        target_application = JobApplication(candidate=target, job_id=first_job.id)
        conflicting_application = JobApplication(candidate=source, job_id=first_job.id)
        movable_application = JobApplication(candidate=source, job_id=second_job.id)
        target_document = ResumeDocument(
            batch_id=first_batch.id,
            candidate=target,
            application=target_application,
            original_filename="target.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
        )
        source_document = ResumeDocument(
            batch_id=first_batch.id,
            candidate=source,
            application=conflicting_application,
            original_filename="source.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
        )
        second_source_document = ResumeDocument(
            batch_id=second_batch.id,
            candidate=source,
            application=movable_application,
            original_filename="source-second.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
        )
        db.add_all([target_document, source_document, second_source_document])
        db.flush()
        target_application.process = CandidateProcess(current_stage="to_interview")
        conflicting_application.process = CandidateProcess(current_stage="contacted")
        plan = InterviewPlanVersion(
            job_id=first_job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=recruiter.id,
            confirmed_at=datetime.now(UTC),
        )
        db.add(plan)
        db.flush()
        target_application.interview_schedule = CandidateInterviewSchedule(
            plan_version_id=plan.id,
            status="scheduled",
            created_by_id=recruiter.id,
        )
        conflicting_application.interview_schedule = CandidateInterviewSchedule(
            plan_version_id=plan.id,
            status="scheduled",
            created_by_id=recruiter.id,
        )
        db.add_all(
            [
                _screening_result(target_document, first_criteria.id),
                _screening_result(source_document, first_criteria.id),
                _screening_result(second_source_document, second_criteria.id),
            ]
        )
        review = CandidateDuplicateReview(
            candidate_a=target,
            candidate_b=source,
            source_document_id=source_document.id,
            confidence="strong",
            signals=["phone_exact"],
        )
        existing_audit = AuditLog(
            actor_user_id=recruiter.id,
            actor_username=recruiter.username,
            action="candidate.existing_history",
            target_type="resume_document",
            target_id=source_document.id,
            job_id=first_job.id,
            batch_id=first_batch.id,
            result="success",
            details={"source": "before_merge"},
        )
        db.add_all([review, existing_audit])
        db.commit()
        dependency = CandidateMergeDependencies(
            session_factory=testing_session,
            review_id=review.id,
            target_candidate_id=target.id,
            source_candidate_id=source.id,
            target_application_id=target_application.id,
            conflicting_application_id=conflicting_application.id,
            movable_application_id=movable_application.id,
        )

    session_store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    yield dependency
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str, password: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_recruiter_can_list_and_dismiss_duplicate_review_idempotently(
    candidate_merge_dependencies: CandidateMergeDependencies,
) -> None:
    dependency = candidate_merge_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter", "correct-password")
        listed = await client.get("/candidates/duplicate-reviews")
        dismissed = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/dismiss",
            json={"reason": "联系方式属于家庭共享号码，确认不是同一人"},
        )
        repeated = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/dismiss",
            json={"reason": "重复提交不应新增记录"},
        )

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["candidate_a"]["phone"] is None
    assert listed.json()[0]["candidate_b"]["phone"] == "13800138000"
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "not_duplicate"
    assert repeated.status_code == 200
    with dependency.session_factory() as db:
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "candidate.duplicate_dismissed"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_hiring_manager_cannot_manage_duplicate_reviews(
    candidate_merge_dependencies: CandidateMergeDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "manager", "manager-password")
        response = await client.get("/candidates/duplicate-reviews")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_duplicate_resolution_rejects_invalid_target_and_illegal_transition(
    candidate_merge_dependencies: CandidateMergeDependencies,
) -> None:
    dependency = candidate_merge_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter", "correct-password")
        missing_reason = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/merge",
            json={"target_candidate_id": str(dependency.target_candidate_id), "reason": " "},
        )
        invalid_target = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/merge",
            json={"target_candidate_id": str(uuid.uuid4()), "reason": "错误目标"},
        )
        dismissed = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/dismiss",
            json={"reason": "确认不是同一人"},
        )
        merge_after_dismiss = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/merge",
            json={
                "target_candidate_id": str(dependency.target_candidate_id),
                "reason": "不允许改变已处理结论",
            },
        )

    assert missing_reason.status_code == 422
    assert invalid_target.status_code == 422
    assert dismissed.status_code == 200
    assert merge_after_dismiss.status_code == 409


@pytest.mark.asyncio
async def test_merge_preserves_documents_applications_processes_and_interviews(
    candidate_merge_dependencies: CandidateMergeDependencies,
) -> None:
    dependency = candidate_merge_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter", "correct-password")
        merged = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/merge",
            json={
                "target_candidate_id": str(dependency.target_candidate_id),
                "reason": "人工核对姓名、电话和简历经历后确认是同一人",
            },
        )
        repeated = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/merge",
            json={
                "target_candidate_id": str(dependency.target_candidate_id),
                "reason": "幂等重试",
            },
        )

    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert body["review"]["status"] == "merged"
    assert body["target_candidate"]["phone"] == "13800138000"
    assert body["target_candidate"]["application_count"] == 3
    assert body["target_candidate"]["resume_count"] == 3
    assert body["merged_candidate"]["status"] == "merged"
    assert body["moved_document_count"] == 2
    assert set(body["moved_application_ids"]) == {
        str(dependency.conflicting_application_id),
        str(dependency.movable_application_id),
    }
    assert body["merged_application_ids"] == [
        str(dependency.conflicting_application_id)
    ]
    assert repeated.status_code == 200
    assert repeated.json()["moved_application_ids"] == []

    with dependency.session_factory() as db:
        source = db.get(Candidate, dependency.source_candidate_id)
        conflict = db.get(JobApplication, dependency.conflicting_application_id)
        movable = db.get(JobApplication, dependency.movable_application_id)
        assert source is not None and source.status == "merged"
        assert source.merged_into_candidate_id == dependency.target_candidate_id
        assert conflict is not None and conflict.status == "merged"
        assert conflict.candidate_id == dependency.target_candidate_id
        assert conflict.merged_into_application_id == dependency.target_application_id
        assert movable is not None and movable.status == "active"
        assert movable.candidate_id == dependency.target_candidate_id
        assert db.scalar(select(func.count(ResumeDocument.id))) == 3
        assert (
            db.scalar(
                select(func.count(ResumeDocument.id)).where(
                    ResumeDocument.candidate_id == dependency.target_candidate_id
                )
            )
            == 3
        )
        assert db.scalar(select(func.count(ScreeningResult.id))) == 3
        assert db.scalar(select(func.count(CandidateProcess.id))) == 2
        assert db.scalar(select(func.count(CandidateInterviewSchedule.id))) == 2
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "candidate.existing_history"
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(AuditLog.action == "candidate.merged")
            )
            == 1
        )
