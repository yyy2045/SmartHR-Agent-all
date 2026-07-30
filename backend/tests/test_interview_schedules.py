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
    Candidate,
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    InterviewPlanVersion,
    InterviewRound,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ScreeningBatch,
    User,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class InterviewScheduleDependencies:
    session_factory: sessionmaker[Session]
    job_id: uuid.UUID
    application_id: uuid.UUID
    document_id: uuid.UUID
    confirmed_plan_id: uuid.UUID
    draft_plan_id: uuid.UUID
    plan_round_ids: list[uuid.UUID]


@pytest.fixture
def interview_schedule_dependencies() -> Generator[InterviewScheduleDependencies, None, None]:
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
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
        )
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
        confirmed_plan = InterviewPlanVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=recruiter.id,
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
            ],
        )
        draft_plan = InterviewPlanVersion(
            job_id=job.id,
            version_number=2,
            status="draft",
        )
        db.add_all([document, confirmed_plan, draft_plan])
        db.commit()
        dependency = InterviewScheduleDependencies(
            session_factory=testing_session,
            job_id=job.id,
            application_id=application.id,
            document_id=document.id,
            confirmed_plan_id=confirmed_plan.id,
            draft_plan_id=draft_plan.id,
            plan_round_ids=[item.id for item in confirmed_plan.rounds],
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


def schedule_payload(dependency: InterviewScheduleDependencies) -> dict[str, object]:
    start_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    return {
        "plan_version_id": str(dependency.confirmed_plan_id),
        "rounds": [
            {
                "plan_round_id": str(dependency.plan_round_ids[0]),
                "scheduled_start_at": start_at.isoformat(),
                "interview_method": "onsite",
                "location": "上海办公室 3A 会议室",
                "meeting_url": None,
            },
            {
                "plan_round_id": str(dependency.plan_round_ids[1]),
                "scheduled_start_at": (start_at + timedelta(days=1)).isoformat(),
                "interview_method": "online",
                "location": None,
                "meeting_url": "https://meeting.example.com/hr-round",
            },
        ],
    }


@pytest.mark.asyncio
async def test_interview_schedule_requires_authentication(
    interview_schedule_dependencies: InterviewScheduleDependencies,
) -> None:
    dependency = interview_schedule_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/jobs/{dependency.job_id}/applications/"
            f"{dependency.application_id}/interview-schedule"
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_schedule_requires_confirmed_plan_and_all_rounds(
    interview_schedule_dependencies: InterviewScheduleDependencies,
) -> None:
    dependency = interview_schedule_dependencies
    path = (
        f"/jobs/{dependency.job_id}/applications/"
        f"{dependency.application_id}/interview-schedule"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        empty = await client.get(path)
        draft_payload = schedule_payload(dependency)
        draft_payload["plan_version_id"] = str(dependency.draft_plan_id)
        draft = await client.post(path, json=draft_payload)

        incomplete_payload = schedule_payload(dependency)
        incomplete_payload["rounds"] = incomplete_payload["rounds"][:1]
        incomplete = await client.post(path, json=incomplete_payload)

        invalid_method_payload = schedule_payload(dependency)
        invalid_method_payload["rounds"][1]["meeting_url"] = "not-a-url"
        invalid_method = await client.post(path, json=invalid_method_payload)

        mixed_location_payload = schedule_payload(dependency)
        mixed_location_payload["rounds"][1]["location"] = "不应保留的线下地点"
        mixed_location = await client.post(path, json=mixed_location_payload)

        created = await client.post(path, json=schedule_payload(dependency))
        repeated = await client.post(path, json=schedule_payload(dependency))
        fetched = await client.get(path)

    assert empty.status_code == 200
    assert empty.json() is None
    assert draft.status_code == 422
    assert draft.json()["detail"] == "只能使用已确认的面试方案版本"
    assert incomplete.status_code == 422
    assert incomplete.json()["detail"] == "必须完整配置所选面试方案的全部轮次"
    assert invalid_method.status_code == 422
    assert mixed_location.status_code == 422
    assert created.status_code == 201
    body = created.json()
    assert body["document_id"] == str(dependency.document_id)
    assert body["plan_version_id"] == str(dependency.confirmed_plan_id)
    assert body["plan_version_number"] == 1
    assert body["status"] == "scheduled"
    assert [item["name"] for item in body["rounds"]] == ["技术一面", "HR 面"]
    assert repeated.status_code == 409
    fetched_body = fetched.json()
    assert fetched_body["id"] == body["id"]
    assert [item["id"] for item in fetched_body["rounds"]] == [
        item["id"] for item in body["rounds"]
    ]

    with dependency.session_factory() as db:
        assert db.scalar(select(func.count(CandidateInterviewSchedule.id))) == 1
        assert db.scalar(select(func.count(CandidateInterviewRound.id))) == 2
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "interview_schedule.created"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_round_reschedule_and_cancel_require_reasons_and_are_audited(
    interview_schedule_dependencies: InterviewScheduleDependencies,
) -> None:
    dependency = interview_schedule_dependencies
    path = (
        f"/jobs/{dependency.job_id}/applications/"
        f"{dependency.application_id}/interview-schedule"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        created = await client.post(path, json=schedule_payload(dependency))
        round_ids = [item["id"] for item in created.json()["rounds"]]
        new_start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3)

        missing_reason = await client.patch(
            f"{path}/rounds/{round_ids[0]}",
            json={
                "scheduled_start_at": new_start.isoformat(),
                "interview_method": "phone",
                "location": None,
                "meeting_url": None,
                "reason": " ",
            },
        )
        rescheduled = await client.patch(
            f"{path}/rounds/{round_ids[0]}",
            json={
                "scheduled_start_at": new_start.isoformat(),
                "interview_method": "phone",
                "location": None,
                "meeting_url": None,
                "reason": "候选人临时出差",
            },
        )
        first_cancelled = await client.post(
            f"{path}/rounds/{round_ids[0]}/cancel",
            json={"reason": "候选人无法参加技术面试"},
        )
        repeated_cancel = await client.post(
            f"{path}/rounds/{round_ids[0]}/cancel",
            json={"reason": "重复取消"},
        )
        cancelled_reschedule = await client.patch(
            f"{path}/rounds/{round_ids[0]}",
            json={
                "scheduled_start_at": new_start.isoformat(),
                "interview_method": "phone",
                "location": None,
                "meeting_url": None,
                "reason": "尝试恢复",
            },
        )
        all_cancelled = await client.post(
            f"{path}/rounds/{round_ids[1]}/cancel",
            json={"reason": "候选人退出流程"},
        )

    assert missing_reason.status_code == 422
    assert rescheduled.status_code == 200
    first_round = rescheduled.json()["rounds"][0]
    assert first_round["status"] == "rescheduled"
    assert first_round["reschedule_count"] == 1
    assert first_round["last_change_reason"] == "候选人临时出差"
    assert first_round["interview_method"] == "phone"
    assert first_cancelled.status_code == 200
    assert first_cancelled.json()["status"] == "partially_cancelled"
    assert repeated_cancel.status_code == 409
    assert cancelled_reschedule.status_code == 409
    assert all_cancelled.status_code == 200
    assert all_cancelled.json()["status"] == "cancelled"

    with dependency.session_factory() as db:
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "interview_schedule.round_rescheduled"
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "interview_schedule.round_cancelled"
                )
            )
            == 2
        )


@pytest.mark.asyncio
async def test_archived_job_is_read_only_and_cross_owner_access_is_hidden(
    interview_schedule_dependencies: InterviewScheduleDependencies,
) -> None:
    dependency = interview_schedule_dependencies
    path = (
        f"/jobs/{dependency.job_id}/applications/"
        f"{dependency.application_id}/interview-schedule"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        created = await client.post(path, json=schedule_payload(dependency))
        round_id = created.json()["rounds"][0]["id"]
        await client.post("/auth/logout")
        await login(client, "other-recruiter")
        hidden_get = await client.get(path)
        hidden_update = await client.patch(
            f"{path}/rounds/{round_id}",
            json={
                "scheduled_start_at": datetime.now(UTC).isoformat(),
                "interview_method": "phone",
                "location": None,
                "meeting_url": None,
                "reason": "越权尝试",
            },
        )

        await client.post("/auth/logout")
        await login(client)
        await client.post(f"/jobs/{dependency.job_id}/archive")
        readable = await client.get(path)
        blocked_update = await client.patch(
            f"{path}/rounds/{round_id}",
            json={
                "scheduled_start_at": datetime.now(UTC).isoformat(),
                "interview_method": "phone",
                "location": None,
                "meeting_url": None,
                "reason": "归档后改期",
            },
        )
        blocked_cancel = await client.post(
            f"{path}/rounds/{round_id}/cancel",
            json={"reason": "归档后取消"},
        )

    assert hidden_get.status_code == 404
    assert hidden_update.status_code == 404
    assert readable.status_code == 200
    assert blocked_update.status_code == 409
    assert blocked_cancel.status_code == 409
