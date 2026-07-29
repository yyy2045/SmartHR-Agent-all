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
    ApplicationResumeDocument,
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
    TalentPoolGroup,
    TalentPoolMembership,
    TalentPoolMembershipEvent,
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
    target_membership_id: uuid.UUID
    conflicting_membership_id: uuid.UUID
    movable_membership_id: uuid.UUID
    target_document_id: uuid.UUID
    source_document_id: uuid.UUID
    movable_document_id: uuid.UUID


def _screening_result(document: ResumeDocument, criteria_id: uuid.UUID) -> ScreeningResult:
    if document.application_id is None:
        raise AssertionError("测试简历必须先绑定应聘记录")
    return ScreeningResult(
        application_id=document.application_id,
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
        db.add_all(
            [
                ApplicationResumeDocument(
                    application_id=target_application.id,
                    document_id=target_document.id,
                ),
                ApplicationResumeDocument(
                    application_id=conflicting_application.id,
                    document_id=source_document.id,
                ),
                ApplicationResumeDocument(
                    application_id=movable_application.id,
                    document_id=second_source_document.id,
                ),
            ]
        )
        db.flush()
        target_application.primary_document_id = target_document.id
        conflicting_application.primary_document_id = source_document.id
        movable_application.primary_document_id = second_source_document.id
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
        shared_group = TalentPoolGroup(name="共享人才组", created_by=recruiter)
        movable_group = TalentPoolGroup(name="待迁移人才组", created_by=recruiter)
        db.add_all([shared_group, movable_group])
        db.flush()

        def membership(
            group: TalentPoolGroup,
            candidate: Candidate,
            reason: str,
        ) -> TalentPoolMembership:
            return TalentPoolMembership(
                group=group,
                candidate=candidate,
                status="active",
                reason=reason,
                updated_by=recruiter,
                events=[
                    TalentPoolMembershipEvent(
                        sequence_number=1,
                        idempotency_key=uuid.uuid4(),
                        action="added",
                        from_status=None,
                        to_status="active",
                        reason=reason,
                        candidate_id_snapshot=candidate.id,
                        actor_user=recruiter,
                        actor_username=recruiter.username,
                        actor_display_name=recruiter.display_name,
                    )
                ],
            )

        target_membership = membership(shared_group, target, "目标候选人已在共享组")
        conflicting_membership = membership(shared_group, source, "来源候选人也在共享组")
        movable_membership = membership(movable_group, source, "仅来源候选人在此组")
        db.add_all([target_membership, conflicting_membership, movable_membership])
        db.commit()
        dependency = CandidateMergeDependencies(
            session_factory=testing_session,
            review_id=review.id,
            target_candidate_id=target.id,
            source_candidate_id=source.id,
            target_application_id=target_application.id,
            conflicting_application_id=conflicting_application.id,
            movable_application_id=movable_application.id,
            target_membership_id=target_membership.id,
            conflicting_membership_id=conflicting_membership.id,
            movable_membership_id=movable_membership.id,
            target_document_id=target_document.id,
            source_document_id=source_document.id,
            movable_document_id=second_source_document.id,
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
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str, password: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_recruiter_can_search_candidates_and_read_application_history(
    candidate_merge_dependencies: CandidateMergeDependencies,
) -> None:
    dependency = candidate_merge_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter", "correct-password")
        listed = await client.get("/candidates")
        searched = await client.get(
            "/candidates",
            params={"status": "all", "query": "13800138000", "limit": 1},
        )
        detail = await client.get(f"/candidates/{dependency.source_candidate_id}")

    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert {item["pending_duplicate_count"] for item in listed.json()["items"]} == {1}
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["id"] == str(dependency.source_candidate_id)
    assert detail.status_code == 200
    assert detail.json()["candidate_code"].startswith("CAND-")
    assert detail.json()["phone"] == "13800138000"
    assert detail.json()["application_count"] == 2
    assert detail.json()["resume_count"] == 2
    assert {item["job_title"] for item in detail.json()["applications"]} == {
        "后端工程师",
        "平台工程师",
    }
    assert any(
        item["current_stage"] == "contacted" for item in detail.json()["applications"]
    )
    assert {item["original_filename"] for item in detail.json()["resumes"]} == {
        "source.pdf",
        "source-second.pdf",
    }


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
        all_reviews = await client.get(
            "/candidates/duplicate-reviews", params={"status": "all"}
        )

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["candidate_a"]["phone"] is None
    assert listed.json()[0]["candidate_b"]["phone"] == "13800138000"
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "not_duplicate"
    assert repeated.status_code == 200
    assert all_reviews.status_code == 200
    assert len(all_reviews.json()) == 1
    assert all_reviews.json()[0]["status"] == "not_duplicate"
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
    dependency = candidate_merge_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "manager", "manager-password")
        listed = await client.get("/candidates")
        detail = await client.get(f"/candidates/{dependency.source_candidate_id}")
        reviews = await client.get("/candidates/duplicate-reviews")

    assert listed.status_code == 403
    assert detail.status_code == 403
    assert reviews.status_code == 403


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
        active_candidates = await client.get("/candidates")
        all_candidates = await client.get("/candidates", params={"status": "all"})
        target_detail = await client.get(f"/candidates/{dependency.target_candidate_id}")
        source_detail = await client.get(f"/candidates/{dependency.source_candidate_id}")

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
    assert active_candidates.status_code == 200
    assert active_candidates.json()["total"] == 1
    assert all_candidates.status_code == 200
    assert all_candidates.json()["total"] == 2
    assert target_detail.status_code == 200
    assert target_detail.json()["application_count"] == 3
    assert target_detail.json()["resume_count"] == 3
    assert source_detail.status_code == 200
    assert source_detail.json()["status"] == "merged"
    assert source_detail.json()["application_count"] == 0
    assert source_detail.json()["resume_count"] == 0

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
        target_application = db.get(JobApplication, dependency.target_application_id)
        assert target_application is not None
        assert target_application.primary_document_id == dependency.target_document_id
        assert {
            item.document_id for item in target_application.document_links
        } == {
            dependency.target_document_id,
            dependency.source_document_id,
        }
        assert conflict.primary_document_id == dependency.source_document_id
        assert {item.document_id for item in conflict.document_links} == {
            dependency.source_document_id
        }
        assert movable.primary_document_id == dependency.movable_document_id
        assert {item.document_id for item in movable.document_links} == {
            dependency.movable_document_id
        }
        assert db.scalar(select(func.count(ApplicationResumeDocument.document_id))) == 4
        target_membership = db.get(TalentPoolMembership, dependency.target_membership_id)
        conflicting_membership = db.get(
            TalentPoolMembership,
            dependency.conflicting_membership_id,
        )
        movable_membership = db.get(TalentPoolMembership, dependency.movable_membership_id)
        assert target_membership is not None and target_membership.status == "active"
        assert target_membership.candidate_id == dependency.target_candidate_id
        assert conflicting_membership is not None
        assert conflicting_membership.status == "removed"
        assert conflicting_membership.candidate_id == dependency.source_candidate_id
        assert movable_membership is not None and movable_membership.status == "active"
        assert movable_membership.candidate_id == dependency.target_candidate_id
        assert [item.action for item in target_membership.events] == [
            "added",
            "candidate_merged",
        ]
        assert [item.action for item in conflicting_membership.events] == [
            "added",
            "candidate_merged",
        ]
        assert [item.action for item in movable_membership.events] == [
            "added",
            "candidate_merged",
        ]
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
        merge_audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "candidate.merged")
        )
        assert merge_audit is not None
        assert merge_audit.details["linked_document_count"] == 1


@pytest.mark.asyncio
async def test_merge_uses_source_primary_when_target_has_no_primary_document(
    candidate_merge_dependencies: CandidateMergeDependencies,
) -> None:
    dependency = candidate_merge_dependencies
    with dependency.session_factory() as db:
        target_application = db.get(JobApplication, dependency.target_application_id)
        assert target_application is not None
        target_application.primary_document_id = None
        db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter", "correct-password")
        merged = await client.post(
            f"/candidates/duplicate-reviews/{dependency.review_id}/merge",
            json={
                "target_candidate_id": str(dependency.target_candidate_id),
                "reason": "验证缺失主简历时采用来源主简历",
            },
        )

    assert merged.status_code == 200, merged.text
    with dependency.session_factory() as db:
        target_application = db.get(JobApplication, dependency.target_application_id)
        assert target_application is not None
        assert target_application.primary_document_id == dependency.source_document_id
        assert {item.document_id for item in target_application.document_links} == {
            dependency.target_document_id,
            dependency.source_document_id,
        }
