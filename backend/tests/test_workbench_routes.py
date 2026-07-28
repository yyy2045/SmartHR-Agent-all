import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.workbench as workbench_service
from app.database import Base, get_db
from app.main import app
from app.models import (
    Candidate,
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    CandidateProcess,
    InterviewEvaluation,
    InterviewPlanVersion,
    InterviewRound,
    Job,
    JobApplication,
    JobCriteriaVersion,
    Offer,
    OfferPortalLink,
    OfferResponse,
    OfferVersion,
    Onboarding,
    RecruitmentRequest,
    RecruitmentRequestVersion,
    ResumeDocument,
    Role,
    ScreeningBatch,
    ScreeningResult,
    User,
    UserRole,
)
from app.models.knowledge import ResumeEmbeddingChunk
from app.models.resume import CandidateProfile
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass(frozen=True)
class WorkbenchDependencies:
    session_factory: sessionmaker[Session]
    job_id: uuid.UUID
    other_job_id: uuid.UUID
    manual_application_id: uuid.UUID
    failed_document_id: uuid.UUID


def _make_user(username: str, role: Role, *, temporary: bool = False) -> User:
    return User(
        username=username,
        password_hash=hash_password(f"{username}-password"),
        display_name=username,
        must_change_password=temporary,
        role_assignments=[UserRole(role=role)],
    )


def _new_application(db: Session, job: Job, name: str) -> JobApplication:
    candidate = Candidate(full_name=name, phone=f"1380000{len(name):04d}")
    application = JobApplication(candidate=candidate, job=job)
    db.add(application)
    db.flush()
    return application


def _new_offer(
    application: JobApplication,
    recruiter: User,
    *,
    status: str,
    valid_until: date,
) -> Offer:
    offer = Offer(application=application, status=status, created_by_id=recruiter.id)
    offer.versions.append(
        OfferVersion(
            version_number=1,
            idempotency_key=uuid.uuid4(),
            currency="CNY",
            monthly_salary=Decimal("30000"),
            annual_salary_months=Decimal("13"),
            probation_months=0,
            probation_monthly_salary=None,
            bonus_description="",
            expected_start_date=date.today() + timedelta(days=7),
            valid_until=valid_until,
            notes="",
            created_by_id=recruiter.id,
            created_by_username=recruiter.username,
            created_by_display_name=recruiter.display_name,
        )
    )
    return offer


@pytest.fixture
def workbench_dependencies() -> Generator[WorkbenchDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)

    with testing_session() as db:
        roles = {
            key: Role(key=key, display_name=label)
            for key, label in {
                "administrator": "企业管理员",
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
                "approver": "审批人",
            }.items()
        }
        administrator = _make_user("administrator", roles["administrator"])
        recruiter = _make_user("recruiter", roles["recruiter"])
        manager = _make_user("manager", roles["hiring_manager"])
        approver = _make_user("approver", roles["approver"])
        temporary = _make_user("temporary", roles["recruiter"], temporary=True)
        db.add_all([*roles.values(), administrator, recruiter, manager, approver, temporary])
        db.flush()

        job = Job(
            owner_id=recruiter.id,
            hiring_manager_id=manager.id,
            title="后端工程师",
            department="研发",
            original_jd="负责后端开发",
        )
        other_job = Job(
            owner_id=temporary.id,
            hiring_manager_id=None,
            title="其他职位",
            department="研发",
            original_jd="不可见职位",
        )
        db.add_all([job, other_job])
        db.flush()

        for request_status in ("draft", "pending_approval"):
            request = RecruitmentRequest(
                idempotency_key=uuid.uuid4(),
                requester_id=manager.id,
                recruiter_id=recruiter.id,
                created_by_id=manager.id,
                status=request_status,
            )
            request.versions.append(
                RecruitmentRequestVersion(
                    version_number=1,
                    created_by_id=manager.id,
                    created_by_username=manager.username,
                    created_by_display_name=manager.display_name,
                    job_title=f"{request_status} 需求",
                    headcount=2,
                    reason="团队扩充",
                    priority="normal",
                    target_start_date=date.today() + timedelta(days=30),
                    salary_min=20000,
                    salary_max=30000,
                    notes="",
                )
            )
            db.add(request)

        criteria = JobCriteriaVersion(
            job=job,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_by_id=recruiter.id,
            confirmed_at=now,
        )
        batch = ScreeningBatch(job=job, criteria_version=criteria, name="工作台测试批次")
        db.add(batch)
        db.flush()

        manual_application = _new_application(db, job, "待初筛候选人")
        manual_document = ResumeDocument(
            batch=batch,
            application=manual_application,
            candidate=manual_application.candidate,
            original_filename="manual.pdf",
            status="completed",
        )
        manual_document.screening_results.append(
            ScreeningResult(
                criteria_version=criteria,
                analysis_version=1,
                status="completed",
                ai_group="passed",
                total_score=80,
                pass_threshold=60,
                model_name="test-model",
                prompt_version="v1",
                started_at=now - timedelta(hours=2),
                completed_at=now - timedelta(hours=1),
            )
        )
        db.add(manual_document)

        schedule_application = _new_application(db, job, "待安排候选人")
        schedule_application.process = CandidateProcess(
            current_stage="to_interview",
            stage_entered_at=now - timedelta(days=1),
            updated_by_id=recruiter.id,
        )

        plan = InterviewPlanVersion(
            job=job,
            version_number=1,
            status="confirmed",
            confirmed_by_id=recruiter.id,
            confirmed_at=now,
        )
        plan_round = InterviewRound(
            name="技术面",
            round_type="technical",
            duration_minutes=60,
            pass_threshold=60,
            focus="技术能力",
            sort_order=0,
        )
        plan.rounds.append(plan_round)
        db.add(plan)
        db.flush()

        evaluation_application = _new_application(db, job, "待评价候选人")
        evaluation_application.process = CandidateProcess(
            current_stage="to_interview",
            stage_entered_at=now - timedelta(days=2),
            updated_by_id=recruiter.id,
        )
        evaluation_schedule = CandidateInterviewSchedule(
            application=evaluation_application,
            plan_version=plan,
            status="scheduled",
            created_by_id=recruiter.id,
        )
        evaluation_schedule.rounds.append(
            CandidateInterviewRound(
                plan_round=plan_round,
                sort_order=0,
                scheduled_start_at=now - timedelta(hours=2),
                interview_method="online",
                status="scheduled",
                updated_by_id=recruiter.id,
            )
        )
        db.add(evaluation_schedule)

        report_application = _new_application(db, job, "待报告候选人")
        report_application.process = CandidateProcess(
            current_stage="completed",
            stage_entered_at=now - timedelta(hours=1),
            updated_by_id=recruiter.id,
        )
        report_schedule = CandidateInterviewSchedule(
            application=report_application,
            plan_version=plan,
            status="scheduled",
            created_by_id=recruiter.id,
        )
        report_round = CandidateInterviewRound(
            plan_round=plan_round,
            sort_order=0,
            scheduled_start_at=now - timedelta(days=1),
            interview_method="online",
            status="scheduled",
            updated_by_id=recruiter.id,
        )
        report_round.evaluation = InterviewEvaluation(
            status="submitted",
            overall_recommendation="recommend",
            overall_comment="通过",
            total_score=80,
            passed=True,
            submitted_by_id=recruiter.id,
            submitted_at=now - timedelta(hours=12),
        )
        report_schedule.rounds.append(report_round)
        db.add(report_schedule)

        manager_offer = _new_offer(
            _new_application(db, job, "经理确认候选人"),
            recruiter,
            status="pending_manager_confirmation",
            valid_until=date.today() + timedelta(days=10),
        )
        db.add(manager_offer)
        approval_offer = _new_offer(
            _new_application(db, job, "审批候选人"),
            recruiter,
            status="pending_approval",
            valid_until=date.today() + timedelta(days=1),
        )
        db.add(approval_offer)
        link_offer = _new_offer(
            _new_application(db, job, "待链接候选人"),
            recruiter,
            status="approved",
            valid_until=date.today() + timedelta(days=1),
        )
        db.add(link_offer)
        expired_offer = _new_offer(
            _new_application(db, job, "已过期候选人"),
            recruiter,
            status="approved",
            valid_until=date.today() - timedelta(days=1),
        )
        db.add(expired_offer)

        for candidate_name, onboarding_status, confirmed_date in (
            ("待日期候选人", "candidate_proposed_date", None),
            ("待候选人确认日期", "pending_confirmation", None),
            ("待入职结果候选人", "pending_start", date.today()),
        ):
            application = _new_application(db, job, candidate_name)
            offer = _new_offer(
                application,
                recruiter,
                status="accepted",
                valid_until=date.today() + timedelta(days=1),
            )
            db.add(offer)
            db.flush()
            link = OfferPortalLink(
                offer_id=offer.id,
                version_id=offer.current_version.id,
                idempotency_key=uuid.uuid4(),
                token_hash=uuid.uuid4().hex,
                verification_phone_digest=uuid.uuid4().hex,
                expires_at=now + timedelta(days=30),
                created_by_id=recruiter.id,
                created_by_username=recruiter.username,
                created_by_display_name=recruiter.display_name,
            )
            db.add(link)
            db.flush()
            response = OfferResponse(
                offer_id=offer.id,
                version_id=offer.current_version.id,
                portal_link_id=link.id,
                idempotency_key=uuid.uuid4(),
                decision="accepted",
                verification_completed_at=now,
                responded_at=now,
            )
            db.add(response)
            db.flush()
            db.add(
                Onboarding(
                    application_id=application.id,
                    offer_id=offer.id,
                    offer_response_id=response.id,
                    status=onboarding_status,
                    candidate_proposed_date=(
                        date.today() + timedelta(days=8)
                        if onboarding_status == "candidate_proposed_date"
                        else None
                    ),
                    confirmed_start_date=confirmed_date,
                )
            )

        failed_document = ResumeDocument(
            batch=batch,
            original_filename="parse-failed.pdf",
            status="failed",
            failure_code="parse_failed",
            failure_message="解析失败",
        )
        ai_failed_document = ResumeDocument(
            batch=batch,
            original_filename="ai-failed.pdf",
            status="completed",
        )
        ai_failed_document.screening_results.append(
            ScreeningResult(
                criteria_version=criteria,
                analysis_version=1,
                status="failed",
                pass_threshold=60,
                model_name="test-model",
                prompt_version="v1",
                failure_code="ai_failed",
                failure_message="AI 失败",
                started_at=now - timedelta(hours=1),
                completed_at=now,
            )
        )
        embedding_document = ResumeDocument(
            batch=batch,
            original_filename="embedding-failed.pdf",
            status="completed",
        )
        profile = CandidateProfile(
            version_number=1,
            source="ai",
            model_name="test-model",
            prompt_version="v1",
        )
        embedding_document.candidate_profiles.append(profile)
        embedding_document.embedding_chunks.append(
            ResumeEmbeddingChunk(
                candidate_profile=profile,
                profile_version=1,
                chunk_type="summary",
                chunk_index=0,
                chunk_text="Python 后端工程师",
                content_hash="a" * 64,
                embedding_model="test-embedding",
                embedding_dimension=3,
                embedding_version="v1",
                status="failed",
                failure_code="embedding_failed",
                failure_message="向量失败",
            )
        )
        db.add_all([failed_document, ai_failed_document, embedding_document])
        db.commit()
        dependencies = WorkbenchDependencies(
            session_factory=testing_session,
            job_id=job.id,
            other_job_id=other_job.id,
            manual_application_id=manual_application.id,
            failed_document_id=failed_document.id,
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


@pytest.mark.asyncio
async def test_recruiter_workbench_aggregates_current_business_facts(
    workbench_dependencies: WorkbenchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        response = await client.get("/workbench/items", params={"page_size": 100})
        assert response.status_code == 200
        body = response.json()
        item_types = {item["item_type"] for item in body["items"]}
        assert {
            "manual_screening",
            "interview_scheduling",
            "interview_evaluation",
            "interview_report",
            "offer_link",
            "onboarding_date",
            "onboarding_outcome",
            "system_failure",
        } <= item_types
        assert body["partial"] is False
        assert body["failed_sources"] == []
        offer_links = [item for item in body["items"] if item["item_type"] == "offer_link"]
        assert len(offer_links) == 1
        offer_link = offer_links[0]
        assert offer_link["priority"] == "urgent"
        assert offer_link["section"] == "action_required"
        assert any(item["section"] == "waiting_external" for item in body["items"])

        summary = (await client.get("/workbench/summary")).json()
        assert summary["total_count"] == sum(item["count"] for item in body["items"])
        assert summary["action_required_count"] > 0
        assert summary["partial"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("username", "expected", "excluded"),
    [
        (
            "manager",
            {"recruitment_request_revision", "offer_manager_confirmation"},
            {"recruitment_request_approval", "offer_approval", "manual_screening"},
        ),
        (
            "approver",
            {"recruitment_request_approval", "offer_approval"},
            {"recruitment_request_revision", "offer_manager_confirmation", "manual_screening"},
        ),
    ],
)
async def test_workbench_applies_role_scope(
    workbench_dependencies: WorkbenchDependencies,
    username: str,
    expected: set[str],
    excluded: set[str],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, username)
        response = await client.get("/workbench/items", params={"page_size": 100})
        assert response.status_code == 200
        item_types = {item["item_type"] for item in response.json()["items"]}
        assert expected <= item_types
        assert not (excluded & item_types)
        if username == "approver":
            approval = next(
                item
                for item in response.json()["items"]
                if item["item_type"] == "offer_approval"
            )
            assert approval["priority"] == "urgent"


@pytest.mark.asyncio
async def test_administrator_sees_account_task_and_filters_are_stable(
    workbench_dependencies: WorkbenchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "administrator")
        first_page = await client.get(
            "/workbench/items",
            params={"section": "action_required", "page": 1, "page_size": 2},
        )
        second_page = await client.get(
            "/workbench/items",
            params={"section": "action_required", "page": 2, "page_size": 2},
        )
        assert first_page.status_code == 200
        assert second_page.status_code == 200
        first_keys = {item["stable_key"] for item in first_page.json()["items"]}
        second_keys = {item["stable_key"] for item in second_page.json()["items"]}
        assert first_keys.isdisjoint(second_keys)

        account_items = await client.get(
            "/workbench/items",
            params={"item_type": "temporary_password_account"},
        )
        assert account_items.status_code == 200
        assert account_items.json()["total"] == 1
        assert account_items.json()["items"][0]["title"] == "临时密码账号：temporary"


@pytest.mark.asyncio
async def test_workbench_hides_out_of_scope_job_filter(
    workbench_dependencies: WorkbenchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        response = await client.get(
            "/workbench/items",
            params={"job_id": str(workbench_dependencies.other_job_id)},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "职位不存在"}


@pytest.mark.asyncio
async def test_source_state_completion_removes_derived_items(
    workbench_dependencies: WorkbenchDependencies,
) -> None:
    with workbench_dependencies.session_factory() as db:
        application = db.get(JobApplication, workbench_dependencies.manual_application_id)
        assert application is not None
        application.process = CandidateProcess(
            current_stage="shortlisted",
            updated_by_id=db.scalar(select(User.id).where(User.username == "recruiter")),
        )
        document = db.get(ResumeDocument, workbench_dependencies.failed_document_id)
        assert document is not None
        document.status = "completed"
        document.failure_code = None
        document.failure_message = None
        db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        manual = await client.get(
            "/workbench/items", params={"item_type": "manual_screening"}
        )
        assert manual.json()["total"] == 0
        failures = await client.get(
            "/workbench/items", params={"item_type": "system_failure", "page_size": 100}
        )
        assert all("简历解析失败" not in item["title"] for item in failures.json()["items"])


@pytest.mark.asyncio
async def test_single_source_failure_returns_partial_without_fake_zero(
    workbench_dependencies: WorkbenchDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_interviews(*args, **kwargs):
        raise RuntimeError("interview query failed")

    monkeypatch.setattr(
        workbench_service,
        "WORKBENCH_COLLECTORS",
        tuple(
            (source, fail_interviews if source == "interviews" else collector)
            for source, collector in workbench_service.WORKBENCH_COLLECTORS
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        response = await client.get("/workbench/summary")
        assert response.status_code == 200
        assert response.json()["partial"] is True
        assert response.json()["failed_sources"] == ["interviews"]
        assert response.json()["total_count"] > 0


def test_collection_query_count_is_bounded(
    workbench_dependencies: WorkbenchDependencies,
) -> None:
    statement_count = 0

    def count_statement(*args, **kwargs) -> None:
        nonlocal statement_count
        statement_count += 1

    with workbench_dependencies.session_factory() as db:
        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", count_statement)
        try:
            recruiter = db.scalar(select(User).where(User.username == "recruiter"))
            assert recruiter is not None
            collection = workbench_service.collect_workbench(db, recruiter)
        finally:
            event.remove(engine, "before_cursor_execute", count_statement)

    assert collection.items
    assert statement_count <= 40


@pytest.mark.asyncio
async def test_workbench_requires_login(
    workbench_dependencies: WorkbenchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/workbench/summary")).status_code == 401
        assert (await client.get("/workbench/items")).status_code == 401
