import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import talent_recommendations as recommendation_routes
from app.database import Base, get_db
from app.main import app
from app.models import (
    ApplicationResumeDocument,
    AuditLog,
    Candidate,
    CandidateProfile,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    Role,
    ScoringDimension,
    ScreeningBatch,
    TalentPoolGroup,
    TalentPoolMembership,
    TalentRecommendationRun,
    TalentRecommendationRunEvent,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore
from app.services.talent_recommendation import attach_task_id


@dataclass(frozen=True)
class RecommendationRouteDependencies:
    session_factory: sessionmaker[Session]
    job_id: uuid.UUID
    no_criteria_job_id: uuid.UUID
    archived_job_id: uuid.UUID
    group_id: uuid.UUID
    archived_group_id: uuid.UUID
    criteria_id: uuid.UUID
    dispatched: list[tuple[uuid.UUID, bool, str]]
    revoked: list[str]


@pytest.fixture
def recommendation_route_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[RecommendationRouteDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
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

        def user(username: str, role_key: str, display_name: str) -> User:
            return User(
                username=username,
                password_hash=hash_password(f"{username}-password"),
                display_name=display_name,
                role_assignments=[UserRole(role=roles[role_key])],
            )

        administrator = user("recommendation-admin", "administrator", "企业管理员")
        recruiter = user("recommendation-owner", "recruiter", "职位招聘专员")
        other_recruiter = user("recommendation-other", "recruiter", "其他招聘专员")
        hiring_manager = user("recommendation-manager", "hiring_manager", "用人经理")
        other_manager = user("recommendation-other-manager", "hiring_manager", "其他用人经理")
        approver = user("recommendation-approver", "approver", "审批人")
        db.add_all(
            [
                *roles.values(),
                administrator,
                recruiter,
                other_recruiter,
                hiring_manager,
                other_manager,
                approver,
            ]
        )
        db.flush()

        job = Job(
            owner=recruiter,
            hiring_manager=hiring_manager,
            title="人才推荐目标职位",
            department="研发",
            original_jd="负责企业招聘平台研发。",
        )
        no_criteria_job = Job(
            owner=recruiter,
            title="尚无筛选标准职位",
            department="研发",
            original_jd="等待确认标准。",
        )
        source_job = Job(
            owner=recruiter,
            title="人才来源职位",
            department="研发",
            original_jd="用于沉淀人才。",
        )
        archived_job = Job(
            owner=recruiter,
            title="归档职位",
            department="研发",
            original_jd="已经归档。",
            status="archived",
            archived_at=datetime.now(UTC),
        )
        criteria = JobCriteriaVersion(
            job=job,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_by_id=recruiter.id,
            confirmed_at=datetime.now(UTC),
            scoring_dimensions=[
                ScoringDimension(
                    name="技术能力",
                    description="岗位核心技术匹配",
                    weight_percent=100,
                    sort_order=0,
                )
            ],
        )
        source_criteria = JobCriteriaVersion(
            job=source_job,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_by_id=recruiter.id,
            confirmed_at=datetime.now(UTC),
            scoring_dimensions=[
                ScoringDimension(
                    name="综合能力",
                    description="人才来源职位评分",
                    weight_percent=100,
                    sort_order=0,
                )
            ],
        )
        group = TalentPoolGroup(name="推荐人才", created_by=recruiter)
        archived_group = TalentPoolGroup(
            name="归档人才",
            created_by=recruiter,
            archived_at=datetime.now(UTC),
            archived_by_id=recruiter.id,
        )
        candidate = Candidate(full_name="推荐候选人")
        db.add_all(
            [
                job,
                no_criteria_job,
                source_job,
                archived_job,
                criteria,
                source_criteria,
                group,
                archived_group,
                candidate,
            ]
        )
        db.flush()
        application = JobApplication(candidate=candidate, job=source_job)
        batch = ScreeningBatch(
            job=source_job,
            criteria_version=source_criteria,
            name="人才库来源",
            status="completed",
        )
        document = ResumeDocument(
            batch=batch,
            candidate=candidate,
            application=application,
            original_filename="talent.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            sha256="c" * 64,
            status="completed",
        )
        profile = CandidateProfile(
            document=document,
            version_number=1,
            source="ai",
            model_name="profile-test",
            prompt_version="profile-v1",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[],
            certifications=[],
            languages=[],
        )
        membership = TalentPoolMembership(
            group=group,
            candidate=candidate,
            source_application=application,
            reason="长期关注",
            updated_by=recruiter,
        )
        applied_candidate = Candidate(full_name="已经应聘目标职位的人才")
        source_application = JobApplication(candidate=applied_candidate, job=source_job)
        target_application = JobApplication(candidate=applied_candidate, job=job)
        applied_document = ResumeDocument(
            batch=batch,
            candidate=applied_candidate,
            application=source_application,
            original_filename="already-applied.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            sha256="d" * 64,
            status="completed",
        )
        applied_profile = CandidateProfile(
            document=applied_document,
            version_number=1,
            source="ai",
            model_name="profile-test",
            prompt_version="profile-v1",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[],
            certifications=[],
            languages=[],
        )
        applied_membership = TalentPoolMembership(
            group=group,
            candidate=applied_candidate,
            source_application=source_application,
            reason="已经进入目标职位",
            updated_by=recruiter,
        )
        db.add_all(
            [
                application,
                batch,
                document,
                profile,
                membership,
                applied_candidate,
                source_application,
                target_application,
                applied_document,
                applied_profile,
                applied_membership,
            ]
        )
        db.flush()
        db.add_all(
            [
                ApplicationResumeDocument(
                    application=application,
                    document=document,
                ),
                ApplicationResumeDocument(
                    application=source_application,
                    document=applied_document,
                ),
            ]
        )
        application.primary_document = document
        source_application.primary_document = applied_document
        db.commit()
        dependencies = RecommendationRouteDependencies(
            session_factory=testing_session,
            job_id=job.id,
            no_criteria_job_id=no_criteria_job.id,
            archived_job_id=archived_job.id,
            group_id=group.id,
            archived_group_id=archived_group.id,
            criteria_id=criteria.id,
            dispatched=[],
            revoked=[],
        )

    def fake_enqueue(run_id: uuid.UUID, *, retry_failed_only: bool = False) -> str:
        task_id = f"recommendation-task-{len(dependencies.dispatched) + 1}"
        dependencies.dispatched.append((run_id, retry_failed_only, task_id))
        return task_id

    def fake_revoke(task_id: str) -> None:
        dependencies.revoked.append(task_id)

    monkeypatch.setattr(
        recommendation_routes,
        "enqueue_talent_recommendation",
        fake_enqueue,
    )
    monkeypatch.setattr(recommendation_routes, "revoke_task", fake_revoke)

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
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": f"{username}-password"},
    )
    assert response.status_code == 200


def create_payload(
    dependency: RecommendationRouteDependencies,
    *,
    key: uuid.UUID | None = None,
    mode: str = "raw",
    group_id: uuid.UUID | None = None,
) -> dict[str, object]:
    return {
        "group_ids": [str(group_id or dependency.group_id)],
        "ai_input_mode": mode,
        "idempotency_key": str(key or uuid.uuid4()),
    }


@pytest.mark.asyncio
async def test_create_run_is_idempotent_and_reuses_active_run(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    first_key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency, key=first_key),
        )
        repeated = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency, key=first_key),
        )
        conflicting_replay = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency, key=first_key, mode="redacted"),
        )
        reused = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency, mode="redacted"),
        )

    assert created.status_code == 202, created.text
    body = created.json()
    assert body["replayed"] is False
    assert body["reused_active_run"] is False
    assert body["run"]["status"] == "queued"
    assert body["run"]["scope_candidate_count"] == 1
    assert body["run"]["resource_version"] == 2
    assert body["run"]["allowed_actions"] == ["cancel"]
    assert repeated.status_code == 202
    assert repeated.json()["replayed"] is True
    assert repeated.json()["run"]["id"] == body["run"]["id"]
    assert conflicting_replay.status_code == 409
    assert reused.status_code == 202
    assert reused.json()["reused_active_run"] is True
    assert reused.json()["run"]["id"] == body["run"]["id"]
    assert len(dependency.dispatched) == 1

    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, uuid.UUID(body["run"]["id"]))
        assert run is not None
        assert run.celery_task_id == "recommendation-task-1"
        assert len(run.group_snapshots) == 1
        assert len(run.candidate_snapshots) == 1
        assert run.candidate_snapshots[0].candidate_id == run.candidate_snapshots[0].candidate.id
        assert run.candidate_snapshots[0].document_id == run.candidate_snapshots[0].document.id
        assert run.scope_candidate_count == len(run.candidate_snapshots)
        assert run.criteria_snapshot["version_number"] == 1
        assert (
            db.scalar(
                select(func.count(TalentRecommendationRunEvent.id)).where(
                    TalentRecommendationRunEvent.run_id == run.id
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "talent_recommendation.created"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_task_binding_refreshes_a_stale_session_before_locking(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
    assert created.status_code == 202, created.text
    run_id = uuid.UUID(created.json()["run"]["id"])

    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, run_id)
        assert run is not None
        run.celery_task_id = None
        db.commit()

    with dependency.session_factory() as stale_db:
        stale_run = stale_db.get(TalentRecommendationRun, run_id)
        assert stale_run is not None
        assert stale_run.celery_task_id is None

        with dependency.session_factory() as winner_db:
            assert attach_task_id(
                winner_db,
                job_id=dependency.job_id,
                run_id=run_id,
                task_id="winner-task",
            )
            winner_db.commit()

        assert not attach_task_id(
            stale_db,
            job_id=dependency.job_id,
            run_id=run_id,
            task_id="loser-task",
        )
        stale_db.commit()

    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, run_id)
        assert run is not None
        assert run.celery_task_id == "winner-task"


@pytest.mark.asyncio
async def test_create_run_validates_job_criteria_and_groups(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        no_criteria = await client.post(
            f"/jobs/{dependency.no_criteria_job_id}/recommendations",
            json=create_payload(dependency),
        )
        archived_job = await client.post(
            f"/jobs/{dependency.archived_job_id}/recommendations",
            json=create_payload(dependency),
        )
        archived_group = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency, group_id=dependency.archived_group_id),
        )
        missing_group = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency, group_id=uuid.uuid4()),
        )

    assert no_criteria.status_code == 409
    assert archived_job.status_code == 409
    assert archived_group.status_code == 409
    assert missing_group.status_code == 404
    assert dependency.dispatched == []


@pytest.mark.asyncio
async def test_recommendation_permissions_and_stable_listing(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthenticated = await client.get(f"/jobs/{dependency.job_id}/recommendations")
        await login(client, "recommendation-owner")
        created = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        first_run = created.json()["run"]
        cancelled = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{first_run['id']}/cancel",
            json={
                "expected_version": first_run["resource_version"],
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert cancelled.status_code == 200
        second = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = second.json()["run"]["id"]
        owner_list = await client.get(
            f"/jobs/{dependency.job_id}/recommendations",
            params={"status": "queued", "limit": 1, "offset": 0},
        )
        first_page = await client.get(
            f"/jobs/{dependency.job_id}/recommendations",
            params={"limit": 1, "offset": 0},
        )
        second_page = await client.get(
            f"/jobs/{dependency.job_id}/recommendations",
            params={"limit": 1, "offset": 1},
        )
        await login(client, "recommendation-manager")
        manager_list = await client.get(f"/jobs/{dependency.job_id}/recommendations")
        manager_detail = await client.get(f"/jobs/{dependency.job_id}/recommendations/{run_id}")
        manager_create = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        await login(client, "recommendation-other")
        other_recruiter = await client.get(f"/jobs/{dependency.job_id}/recommendations")
        await login(client, "recommendation-approver")
        approver = await client.get(f"/jobs/{dependency.job_id}/recommendations")

    assert unauthenticated.status_code == 401
    assert owner_list.status_code == 200
    assert owner_list.json()["total"] == 1
    assert first_page.json()["total"] == 2
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]
    assert manager_list.status_code == 200
    assert manager_list.json()["items"][0]["allowed_actions"] == []
    assert manager_detail.status_code == 200
    assert manager_detail.json()["results"] == []
    assert manager_create.status_code == 403
    assert other_recruiter.status_code == 404
    assert approver.status_code == 404


@pytest.mark.asyncio
async def test_cancel_is_versioned_idempotent_and_best_effort_revokes_task(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    cancel_key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run = created.json()["run"]
        stale_cancel = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run['id']}/cancel",
            json={"expected_version": 1, "idempotency_key": str(uuid.uuid4())},
        )
        cancelled = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run['id']}/cancel",
            json={
                "expected_version": run["resource_version"],
                "idempotency_key": str(cancel_key),
            },
        )
        repeated = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run['id']}/cancel",
            json={
                "expected_version": run["resource_version"],
                "idempotency_key": str(cancel_key),
            },
        )
        terminal_cancel = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run['id']}/cancel",
            json={"expected_version": 3, "idempotency_key": str(uuid.uuid4())},
        )

    assert stale_cancel.status_code == 409
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["allowed_actions"] == []
    assert repeated.status_code == 200
    assert terminal_cancel.status_code == 409
    assert dependency.revoked == ["recommendation-task-1"]

    with dependency.session_factory() as db:
        assert (
            db.scalar(
                select(func.count(TalentRecommendationRunEvent.id)).where(
                    TalentRecommendationRunEvent.run_id == uuid.UUID(run["id"])
                )
            )
            == 3
        )


@pytest.mark.asyncio
async def test_partial_run_retries_only_failed_items_idempotently(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    retry_key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created.json()["run"]["id"])
        with dependency.session_factory() as db:
            run = db.get(TalentRecommendationRun, run_id)
            assert run is not None
            run.status = "partial"
            run.retrieved_count = 1
            run.rescored_count = 1
            run.failed_count = 1
            run.completed_at = datetime.now(UTC)
            run.resource_version += 1
            db.commit()
            retry_version = run.resource_version

        retried = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/retry-failures",
            json={
                "expected_version": retry_version,
                "idempotency_key": str(retry_key),
            },
        )
        repeated = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/retry-failures",
            json={
                "expected_version": retry_version,
                "idempotency_key": str(retry_key),
            },
        )

    assert retried.status_code == 202, retried.text
    assert retried.json()["status"] == "partial"
    assert retried.json()["allowed_actions"] == ["retry_failed_items"]
    assert repeated.status_code == 202
    assert len(dependency.dispatched) == 2
    assert dependency.dispatched[1][1] is True


@pytest.mark.asyncio
async def test_new_confirmed_criteria_marks_existing_runs_stale(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = created.json()["run"]["id"]
        draft = await client.post(
            f"/jobs/{dependency.job_id}/criteria/versions",
            json={"source_version_id": str(dependency.criteria_id)},
        )
        assert draft.status_code == 201, draft.text
        confirmed = await client.post(
            f"/jobs/{dependency.job_id}/criteria/versions/{draft.json()['id']}/confirm"
        )
        detail = await client.get(f"/jobs/{dependency.job_id}/recommendations/{run_id}")

    assert confirmed.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["criteria_stale"] is True
    assert detail.json()["criteria_stale_at"] is not None
    assert detail.json()["allowed_actions"] == ["cancel"]


@pytest.mark.asyncio
async def test_dispatch_failure_is_persisted_and_reported(
    recommendation_route_dependencies: RecommendationRouteDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = recommendation_route_dependencies

    def fail_enqueue(run_id: uuid.UUID, *, retry_failed_only: bool = False) -> str:
        raise RuntimeError(f"broker unavailable: {run_id}:{retry_failed_only}")

    monkeypatch.setattr(
        recommendation_routes,
        "enqueue_talent_recommendation",
        fail_enqueue,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        failed = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )

    assert failed.status_code == 503
    with dependency.session_factory() as db:
        run = db.scalar(
            select(TalentRecommendationRun).order_by(TalentRecommendationRun.created_at.desc())
        )
        assert run is not None
        assert run.status == "failed"
        assert run.failure_code == "recommendation_dispatch_failed"
        assert run.completed_at is not None
