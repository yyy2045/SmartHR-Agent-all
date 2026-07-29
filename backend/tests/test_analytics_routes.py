import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    Candidate,
    CandidateInterviewSchedule,
    CandidateProcess,
    InterviewPlanVersion,
    InterviewReport,
    InterviewReportVersion,
    Job,
    JobApplication,
    JobCriteriaVersion,
    Offer,
    OfferApproval,
    OfferPortalLink,
    OfferResponse,
    OfferVersion,
    Onboarding,
    OnboardingEvent,
    RecruiterDecision,
    RecruitmentRequest,
    RecruitmentRequestVersion,
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
class AnalyticsDependencies:
    active_job_id: uuid.UUID
    archived_job_id: uuid.UUID
    invisible_job_id: uuid.UUID


def _user(username: str, role: Role) -> User:
    return User(
        username=username,
        password_hash=hash_password(f"{username}-password"),
        display_name=username,
        role_assignments=[UserRole(role=role)],
    )


def _application(
    db: Session,
    job: Job,
    candidate: Candidate,
    *,
    created_at: datetime,
    stage: str | None,
) -> JobApplication:
    application = JobApplication(
        candidate=candidate,
        job=job,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(application)
    db.flush()
    if stage is not None:
        db.add(
            CandidateProcess(
                application_id=application.id,
                current_stage=stage,
                stage_entered_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return application


def _screened_application(
    db: Session,
    application: JobApplication,
    candidate: Candidate,
    batch: ScreeningBatch,
    criteria: JobCriteriaVersion,
    recruiter: User,
    *,
    completed_at: datetime,
    shortlisted: bool,
) -> ScreeningResult:
    document = ResumeDocument(
        batch=batch,
        candidate=candidate,
        application=application,
        original_filename=f"{candidate.full_name}.pdf",
        file_extension=".pdf",
        content_type="application/pdf",
        detected_type="pdf",
        size_bytes=100,
        status="completed",
        parsed_at=completed_at,
        redacted_at=completed_at,
        created_at=application.created_at,
        updated_at=completed_at,
    )
    result = ScreeningResult(
        document=document,
        criteria_version=criteria,
        analysis_version=1,
        status="completed",
        ai_group="passed",
        total_score=Decimal("85"),
        pass_threshold=60,
        model_name="test-model",
        prompt_version="v1",
        started_at=completed_at - timedelta(minutes=1),
        completed_at=completed_at,
        created_at=completed_at,
    )
    if shortlisted:
        result.recruiter_decisions.append(
            RecruiterDecision(
                operator_id=recruiter.id,
                sequence_number=1,
                previous_decision="unprocessed",
                decision="shortlisted",
                created_at=completed_at + timedelta(hours=1),
            )
        )
    db.add(result)
    db.flush()
    return result


def _complete_hiring_chain(
    db: Session,
    application: JobApplication,
    plan: InterviewPlanVersion,
    recruiter: User,
    *,
    base_time: datetime,
) -> None:
    db.add(
        CandidateInterviewSchedule(
            application=application,
            plan_version=plan,
            status="scheduled",
            created_by_id=recruiter.id,
            created_at=base_time,
            updated_at=base_time,
        )
    )
    report = InterviewReport(
        application=application,
        status="confirmed",
        current_version_number=1,
        created_by_id=recruiter.id,
        confirmed_by_id=recruiter.id,
        confirmed_at=base_time + timedelta(days=1),
        created_at=base_time,
        updated_at=base_time + timedelta(days=1),
    )
    report.versions.append(
        InterviewReportVersion(
            version_number=1,
            idempotency_key=uuid.uuid4(),
            generation_mode="manual",
            conclusion="hire",
            executive_summary="建议录用",
            created_by_id=recruiter.id,
            created_by_username=recruiter.username,
            created_by_display_name=recruiter.display_name,
            created_at=base_time,
        )
    )
    db.add(report)
    db.flush()

    offer = Offer(
        application=application,
        status="accepted",
        created_by_id=recruiter.id,
        created_at=base_time + timedelta(days=2),
        updated_at=base_time + timedelta(days=4),
    )
    version = OfferVersion(
        version_number=1,
        idempotency_key=uuid.uuid4(),
        submission_idempotency_key=uuid.uuid4(),
        submitted_at=base_time + timedelta(days=2),
        source_interview_report_version_id=report.current_version.id,
        currency="CNY",
        monthly_salary=Decimal("30000"),
        annual_salary_months=Decimal("13"),
        probation_months=0,
        probation_monthly_salary=None,
        bonus_description="",
        expected_start_date=date(2026, 8, 1),
        valid_until=date(2026, 7, 20),
        notes="",
        created_by_id=recruiter.id,
        created_by_username=recruiter.username,
        created_by_display_name=recruiter.display_name,
        created_at=base_time + timedelta(days=2),
    )
    version.approval = OfferApproval(
        idempotency_key=uuid.uuid4(),
        approver_username="approver",
        approver_display_name="approver",
        decision="approved",
        decided_at=base_time + timedelta(days=3),
    )
    offer.versions.append(version)
    db.add(offer)
    db.flush()
    link = OfferPortalLink(
        offer_id=offer.id,
        version_id=version.id,
        idempotency_key=uuid.uuid4(),
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        verification_phone_digest="a" * 64,
        expires_at=base_time + timedelta(days=20),
        created_by_id=recruiter.id,
        created_by_username=recruiter.username,
        created_by_display_name=recruiter.display_name,
        created_at=base_time + timedelta(days=3),
    )
    db.add(link)
    db.flush()
    response = OfferResponse(
        offer_id=offer.id,
        version_id=version.id,
        portal_link_id=link.id,
        idempotency_key=uuid.uuid4(),
        decision="accepted",
        verification_completed_at=base_time + timedelta(days=4),
        responded_at=base_time + timedelta(days=4),
    )
    db.add(response)
    db.flush()
    onboarding = Onboarding(
        application_id=application.id,
        offer_id=offer.id,
        offer_response_id=response.id,
        status="onboarded",
        confirmed_start_date=date(2026, 7, 15),
        actual_start_date=date(2026, 7, 15),
        created_at=base_time + timedelta(days=4),
        updated_at=base_time + timedelta(days=5),
    )
    onboarding.events.append(
        OnboardingEvent(
            sequence_number=1,
            idempotency_key=uuid.uuid4(),
            action="onboarded",
            from_status="pending_start",
            to_status="onboarded",
            date_after=date(2026, 7, 15),
            actor_type="recruiter",
            actor_user_id=recruiter.id,
            actor_username=recruiter.username,
            actor_display_name=recruiter.display_name,
            created_at=base_time + timedelta(days=5),
        )
    )
    db.add(onboarding)


@pytest.fixture
def analytics_dependencies() -> Generator[AnalyticsDependencies, None, None]:
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
            for key in ("administrator", "recruiter", "hiring_manager", "approver")
        }
        administrator = _user("administrator", roles["administrator"])
        recruiter = _user("recruiter", roles["recruiter"])
        other_recruiter = _user("other-recruiter", roles["recruiter"])
        manager = _user("manager", roles["hiring_manager"])
        approver = _user("approver", roles["approver"])
        db.add_all(
            [
                *roles.values(),
                administrator,
                recruiter,
                other_recruiter,
                manager,
                approver,
            ]
        )
        db.flush()

        request = RecruitmentRequest(
            idempotency_key=uuid.uuid4(),
            requester_id=manager.id,
            recruiter_id=recruiter.id,
            created_by_id=manager.id,
            status="converted",
        )
        request.versions.append(
            RecruitmentRequestVersion(
                version_number=1,
                created_by_id=manager.id,
                created_by_username=manager.username,
                created_by_display_name=manager.display_name,
                job_title="后端工程师",
                headcount=3,
                reason="扩编",
                priority="normal",
                target_start_date=date(2026, 8, 1),
                salary_min=20000,
                salary_max=40000,
            )
        )
        db.add(request)
        db.flush()
        active_job = Job(
            owner_id=recruiter.id,
            hiring_manager_id=manager.id,
            recruitment_request_id=request.id,
            title="后端工程师",
            department="研发",
            original_jd="后端开发",
            status="active",
        )
        archived_job = Job(
            owner_id=recruiter.id,
            title="历史职位",
            department="研发",
            original_jd="历史职位",
            status="archived",
            archived_at=datetime(2026, 7, 20, tzinfo=UTC),
        )
        invisible_job = Job(
            owner_id=other_recruiter.id,
            title="不可见职位",
            department="其他",
            original_jd="其他职位",
            status="active",
        )
        db.add_all([active_job, archived_job, invisible_job])
        db.flush()

        resources = {}
        for job in (active_job, archived_job, invisible_job):
            criteria = JobCriteriaVersion(
                job=job,
                version_number=1,
                status="confirmed",
                pass_threshold=60,
            )
            batch = ScreeningBatch(
                job=job,
                criteria_version=criteria,
                name="分析数据",
                status="completed",
            )
            plan = InterviewPlanVersion(job=job, version_number=1, status="confirmed")
            db.add_all([criteria, batch, plan])
            resources[job.id] = (criteria, batch, plan)
        db.flush()

        shared_candidate = Candidate(full_name="共享候选人", phone="13800000001")
        hired_candidate = Candidate(full_name="录用候选人", phone="13800000002")
        invisible_candidate = Candidate(full_name="不可见候选人", phone="13800000003")
        db.add_all([shared_candidate, hired_candidate, invisible_candidate])
        db.flush()
        july_first = datetime(2026, 7, 1, 1, tzinfo=UTC)
        complete_application = _application(
            db,
            active_job,
            hired_candidate,
            created_at=july_first,
            stage="onboarding_completed",
        )
        _application(
            db,
            active_job,
            shared_candidate,
            created_at=july_first + timedelta(days=1),
            stage=None,
        )
        screened_application = _application(
            db,
            archived_job,
            shared_candidate,
            created_at=july_first + timedelta(days=2),
            stage="pending",
        )
        _application(
            db,
            invisible_job,
            invisible_candidate,
            created_at=july_first,
            stage="unprocessed",
        )
        db.flush()

        active_criteria, active_batch, active_plan = resources[active_job.id]
        archived_criteria, archived_batch, _ = resources[archived_job.id]
        _screened_application(
            db,
            complete_application,
            hired_candidate,
            active_batch,
            active_criteria,
            recruiter,
            completed_at=july_first + timedelta(days=1),
            shortlisted=True,
        )
        _screened_application(
            db,
            screened_application,
            shared_candidate,
            archived_batch,
            archived_criteria,
            recruiter,
            completed_at=july_first + timedelta(days=3),
            shortlisted=False,
        )
        _complete_hiring_chain(
            db,
            complete_application,
            active_plan,
            recruiter,
            base_time=july_first + timedelta(days=4),
        )
        db.commit()
        dependencies = AnalyticsDependencies(
            active_job_id=active_job.id,
            archived_job_id=archived_job.id,
            invisible_job_id=invisible_job.id,
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
    yield dependencies
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def _login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": f"{username}-password"},
    )
    assert response.status_code == 200


def _range() -> dict[str, str]:
    return {"start_date": "2026-07-01", "end_date": "2026-07-30"}


@pytest.mark.asyncio
async def test_recruiter_overview_includes_archived_jobs_and_deduplicates_people(
    analytics_dependencies: AnalyticsDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        response = await client.get("/analytics/overview", params=_range())
        assert response.status_code == 200
        body = response.json()
        assert body["selected_job_count"] == 2
        assert body["active_job_count"] == 1
        assert body["application_count"] == 3
        assert body["unique_candidate_count"] == 2
        assert body["approved_headcount"] == 3
        assert body["hired_count"] == 1
        assert body["linked_hired_count"] == 1
        assert body["hiring_completion_rate"]["percentage"] == 33.3
        assert body["meta"]["timezone"] == "Asia/Shanghai"


@pytest.mark.asyncio
async def test_role_scope_and_job_filter_do_not_leak_invisible_jobs(
    analytics_dependencies: AnalyticsDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "manager")
        manager = (await client.get("/analytics/overview", params=_range())).json()
        assert manager["selected_job_count"] == 1
        assert manager["application_count"] == 2

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "approver")
        approver = (await client.get("/analytics/overview", params=_range())).json()
        assert approver["selected_job_count"] == 3
        assert approver["application_count"] == 4

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        response = await client.get(
            "/analytics/overview",
            params={**_range(), "job_id": str(analytics_dependencies.invisible_job_id)},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "职位不存在"


@pytest.mark.asyncio
async def test_funnel_uses_historical_reach_and_current_distribution_is_exclusive(
    analytics_dependencies: AnalyticsDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        funnel = (await client.get("/analytics/funnel", params=_range())).json()
        assert [item["count"] for item in funnel["stages"]] == [3, 2, 1, 1, 1, 1, 1, 1]
        assert funnel["stages"][-1]["cohort_percentage"] == 33.3

        distribution = (
            await client.get("/analytics/current-distribution", params=_range())
        ).json()
        counts = {item["key"]: item["count"] for item in distribution["stages"]}
        assert distribution["total"] == 3
        assert counts["unprocessed"] == 1
        assert counts["pending"] == 1
        assert counts["onboarding_completed"] == 1
        assert sum(counts.values()) == 3


@pytest.mark.asyncio
async def test_trend_uses_shanghai_dates_and_requires_week_for_long_ranges(
    analytics_dependencies: AnalyticsDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        response = await client.get("/analytics/trend", params=_range())
        assert response.status_code == 200
        body = response.json()
        assert body["interval"] == "day"
        assert len(body["points"]) == 30
        assert sum(item["applications_created"] for item in body["points"]) == 3
        assert sum(item["offers_accepted"] for item in body["points"]) == 1
        assert sum(item["onboardings_completed"] for item in body["points"]) == 1

        long_range = {"start_date": "2026-01-01", "end_date": "2026-07-30"}
        weekly = await client.get("/analytics/trend", params=long_range)
        assert weekly.status_code == 200
        assert weekly.json()["interval"] == "week"
        rejected_daily = await client.get(
            "/analytics/trend",
            params={**long_range, "interval": "day"},
        )
        assert rejected_daily.status_code == 422
        assert rejected_daily.json()["detail"] == "超过 30 天的趋势必须按周聚合"


@pytest.mark.asyncio
async def test_analytics_rejects_invalid_ranges_and_requires_authentication(
    analytics_dependencies: AnalyticsDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/analytics/overview", params=_range())).status_code == 401
        await _login(client, "recruiter")
        reversed_range = await client.get(
            "/analytics/overview",
            params={"start_date": "2026-07-30", "end_date": "2026-07-01"},
        )
        assert reversed_range.status_code == 422
        too_long = await client.get(
            "/analytics/overview",
            params={"start_date": "2025-07-29", "end_date": "2026-07-30"},
        )
        assert too_long.status_code == 422
