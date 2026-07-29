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
    CandidateDuplicateReview,
    CandidateProcess,
    CandidateProfile,
    DimensionScore,
    EvidenceCitation,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeTextSegment,
    Role,
    ScoringDimension,
    ScreeningBatch,
    ScreeningResult,
    TalentPoolGroup,
    TalentPoolMembership,
    TalentRecommendationResult,
    TalentRecommendationRun,
    TalentRecommendationRunEvent,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.candidate_merging import merge_duplicate_candidates
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


def complete_recommendation_result(
    dependency: RecommendationRouteDependencies,
    run_id: uuid.UUID,
    *,
    candidate_name: str = "推荐候选人",
    vector_rank: int = 1,
    result_status: str = "completed",
    invalid_snapshot: bool = False,
) -> uuid.UUID:
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, run_id)
        assert run is not None
        candidate = db.scalar(select(Candidate).where(Candidate.full_name == candidate_name))
        assert candidate is not None
        document = db.scalar(
            select(ResumeDocument)
            .where(ResumeDocument.candidate_id == candidate.id)
            .order_by(ResumeDocument.created_at.desc())
            .limit(1)
        )
        assert document is not None
        profile = db.scalar(
            select(CandidateProfile)
            .where(CandidateProfile.document_id == document.id)
            .order_by(CandidateProfile.version_number.desc())
            .limit(1)
        )
        assert profile is not None
        segment = db.scalar(
            select(ResumeTextSegment).where(ResumeTextSegment.document_id == document.id)
        )
        if segment is None:
            segment = ResumeTextSegment(
                document=document,
                segment_key="seg-001",
                source_type="pdf_page",
                source_index=0,
                page_number=1,
                raw_text="具备五年 Python 与企业系统开发经验。",
                normalized_text="具备五年 Python 与企业系统开发经验。",
                redacted_text="具备五年 Python 与企业系统开发经验。",
                sort_order=0,
            )
            db.add(segment)
            db.flush()
        dimension = db.scalar(
            select(ScoringDimension)
            .where(ScoringDimension.criteria_version_id == run.criteria_version_id)
            .order_by(ScoringDimension.sort_order)
            .limit(1)
        )
        assert dimension is not None
        membership = db.scalar(
            select(TalentPoolMembership).where(
                TalentPoolMembership.candidate_id == candidate.id,
                TalentPoolMembership.group_id == dependency.group_id,
            )
        )
        assert membership is not None
        now = datetime.now(UTC)
        recommendation_result = TalentRecommendationResult(
            run_id=run.id,
            candidate_id=candidate.id,
            resolved_candidate_id=candidate.id,
            candidate_code_snapshot=candidate.candidate_code,
            candidate_name_snapshot=candidate.full_name,
            document_id=document.id,
            document_sha256_snapshot=document.sha256,
            document_updated_at_snapshot=document.updated_at,
            candidate_profile_id=profile.id,
            profile_version_snapshot=profile.version_number,
            embedding_model_snapshot="embedding-test",
            embedding_version_snapshot="v1",
            embedding_dimension_snapshot=3,
            vector_rank=vector_rank,
            similarity_score=0.92,
            matched_group_ids=[str(dependency.group_id)],
            matched_chunks=[],
            status=result_status,
            ai_score=88 if result_status == "completed" else None,
            ai_group="passed" if result_status == "completed" else None,
            ai_dimension_scores=(
                [
                    {
                        "dimension_id": (
                            "invalid-dimension" if invalid_snapshot else str(dimension.id)
                        ),
                        "name": "技术能力",
                        "score": 88,
                        "weight_percent": 100,
                        "weighted_score": 88,
                        "rationale": "具备岗位所需经验",
                        "missing_items": [],
                        "sort_order": 0,
                    }
                ]
                if result_status == "completed"
                else []
            ),
            ai_hard_requirement_results=[],
            ai_strengths=["企业系统开发经验"],
            ai_gaps=[],
            ai_missing_items=[],
            ai_interview_questions=["请说明复杂系统的架构取舍"],
            ai_evidence=(
                [
                    {
                        "subject_type": "dimension",
                        "subject_key": str(dimension.id),
                        "segment_key": segment.segment_key,
                        "quote": "具备五年 Python 与企业系统开发经验。",
                        "source_type": segment.source_type,
                        "page_number": segment.page_number,
                        "paragraph_index": segment.paragraph_index,
                        "sort_order": 0,
                    }
                ]
                if result_status == "completed"
                else []
            ),
            ai_model_snapshot=("ai-test" if result_status == "completed" else None),
            prompt_version_snapshot=("prompt-test" if result_status == "completed" else None),
            processing_attempt_count=1,
            failure_code=("ai_timeout" if result_status == "failed" else None),
            failure_message=("AI 调用超时" if result_status == "failed" else None),
            completed_at=now,
        )
        db.add(recommendation_result)
        db.flush()
        run.status = "partial" if result_status == "failed" else "completed"
        run.retrieved_count = max(run.retrieved_count, vector_rank)
        run.rescored_count += 1
        if result_status == "completed":
            run.completed_count += 1
        else:
            run.failed_count += 1
            run.failure_code = "ai_rescoring_partial"
            run.failure_summary = "部分候选人 AI 重评失败"
        run.started_at = run.started_at or now
        run.completed_at = now
        run.resource_version += 1
        db.commit()
        return recommendation_result.id


def selection_payload(
    result_ids: list[uuid.UUID],
    *,
    confirmed_stale_result_ids: list[uuid.UUID] | None = None,
) -> dict[str, object]:
    return {
        "result_ids": [str(item) for item in result_ids],
        "confirmed_stale_result_ids": [
            str(item) for item in (confirmed_stale_result_ids or [])
        ],
        "idempotency_key": str(uuid.uuid4()),
    }


def add_bulk_completed_results(
    dependency: RecommendationRouteDependencies,
    run_id: uuid.UUID,
    *,
    count: int,
) -> list[uuid.UUID]:
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, run_id)
        source_job = db.scalar(select(Job).where(Job.title == "人才来源职位"))
        assert run is not None
        assert source_job is not None
        batch = db.scalar(select(ScreeningBatch).where(ScreeningBatch.job_id == source_job.id))
        dimension = db.scalar(
            select(ScoringDimension).where(
                ScoringDimension.criteria_version_id == run.criteria_version_id
            )
        )
        group = db.get(TalentPoolGroup, dependency.group_id)
        actor = db.scalar(select(User).where(User.username == "recommendation-owner"))
        assert all(item is not None for item in (run, source_job, batch, dimension, group, actor))
        assert batch is not None
        assert dimension is not None
        assert group is not None
        assert actor is not None
        result_ids: list[uuid.UUID] = []
        now = datetime.now(UTC)
        for index in range(count):
            candidate = Candidate(full_name=f"批量推荐候选人 {index + 1}")
            source_application = JobApplication(candidate=candidate, job=source_job)
            document = ResumeDocument(
                batch=batch,
                candidate=candidate,
                application=source_application,
                original_filename=f"bulk-{index + 1}.pdf",
                file_extension=".pdf",
                content_type="application/pdf",
                detected_type="pdf",
                size_bytes=100 + index,
                sha256=f"{index + 1:064x}",
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
            segment = ResumeTextSegment(
                document=document,
                segment_key="seg-001",
                source_type="pdf_page",
                source_index=0,
                page_number=1,
                raw_text="具备企业软件开发经验。",
                normalized_text="具备企业软件开发经验。",
                redacted_text="具备企业软件开发经验。",
                sort_order=0,
            )
            membership = TalentPoolMembership(
                group=group,
                candidate=candidate,
                source_application=source_application,
                reason="批量推荐验收",
                updated_by=actor,
            )
            db.add_all(
                [
                    candidate,
                    source_application,
                    document,
                    profile,
                    segment,
                    membership,
                ]
            )
            db.flush()
            source_application.document_links.append(
                ApplicationResumeDocument(document=document)
            )
            source_application.primary_document = document
            recommendation_result = TalentRecommendationResult(
                run_id=run.id,
                candidate_id=candidate.id,
                resolved_candidate_id=candidate.id,
                candidate_code_snapshot=candidate.candidate_code,
                candidate_name_snapshot=candidate.full_name,
                document_id=document.id,
                document_sha256_snapshot=document.sha256,
                document_updated_at_snapshot=document.updated_at,
                candidate_profile_id=profile.id,
                profile_version_snapshot=profile.version_number,
                embedding_model_snapshot="embedding-test",
                embedding_version_snapshot="v1",
                embedding_dimension_snapshot=3,
                vector_rank=index + 1,
                similarity_score=0.9 - index / 100,
                matched_group_ids=[str(group.id)],
                matched_chunks=[],
                status="completed",
                ai_score=80 + index / 10,
                ai_group="passed",
                ai_dimension_scores=[
                    {
                        "dimension_id": str(dimension.id),
                        "name": dimension.name,
                        "score": 80,
                        "weight_percent": 100,
                        "weighted_score": 80,
                        "rationale": "满足岗位要求",
                        "missing_items": [],
                        "sort_order": 0,
                    }
                ],
                ai_hard_requirement_results=[],
                ai_strengths=["企业软件经验"],
                ai_gaps=[],
                ai_missing_items=[],
                ai_interview_questions=[],
                ai_evidence=[
                    {
                        "subject_type": "dimension",
                        "subject_key": str(dimension.id),
                        "segment_key": segment.segment_key,
                        "quote": segment.normalized_text,
                        "source_type": segment.source_type,
                        "page_number": segment.page_number,
                        "paragraph_index": segment.paragraph_index,
                        "sort_order": 0,
                    }
                ],
                ai_model_snapshot="ai-test",
                prompt_version_snapshot="prompt-test",
                processing_attempt_count=1,
                completed_at=now,
            )
            db.add(recommendation_result)
            db.flush()
            result_ids.append(recommendation_result.id)
        run.status = "completed"
        run.retrieved_count = count
        run.rescored_count = count
        run.completed_count = count
        run.failed_count = 0
        run.started_at = now
        run.completed_at = now
        run.resource_version += 1
        db.commit()
        return result_ids


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
    assert body["run"]["excluded_count"] == 1
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


@pytest.mark.asyncio
async def test_select_completed_recommendation_creates_full_application_and_replays(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created_run = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created_run.json()["run"]["id"])
        result_id = complete_recommendation_result(dependency, run_id)
        detail = await client.get(f"/jobs/{dependency.job_id}/recommendations/{run_id}")
        selected = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )
        replayed = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )

    assert detail.status_code == 200
    assert detail.json()["allowed_actions"] == ["select_candidates"]
    assert selected.status_code == 200, selected.text
    body = selected.json()
    assert body["created_count"] == 1
    assert body["existing_count"] == 0
    assert body["failed_count"] == 0
    item = body["items"][0]
    assert item["status"] == "created"
    assert replayed.status_code == 200
    assert replayed.json()["created_count"] == 0
    assert replayed.json()["existing_count"] == 1
    assert replayed.json()["items"][0]["application_id"] == item["application_id"]

    application_id = uuid.UUID(item["application_id"])
    screening_result_id = uuid.UUID(item["screening_result_id"])
    with dependency.session_factory() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        assert application.source_type == "talent_recommendation"
        assert application.talent_recommendation_run_id == run_id
        assert application.talent_recommendation_result_id == result_id
        assert application.primary_document_id is not None
        assert len(application.document_links) == 1
        process = db.scalar(
            select(CandidateProcess).where(CandidateProcess.application_id == application.id)
        )
        assert process is not None
        assert process.current_stage == "unprocessed"
        assert len(process.events) == 1
        assert process.events[0].reason == "由人才推荐转为应聘"
        screening = db.get(ScreeningResult, screening_result_id)
        assert screening is not None
        assert screening.application_id == application.id
        assert screening.analysis_version == 1
        assert screening.status == "completed"
        assert screening.ai_group == "passed"
        assert screening.total_score == 88
        assert db.scalar(
            select(func.count(DimensionScore.id)).where(
                DimensionScore.screening_result_id == screening.id
            )
        ) == 1
        assert db.scalar(
            select(func.count(EvidenceCitation.id)).where(
                EvidenceCitation.screening_result_id == screening.id
            )
        ) == 1
        assert db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == "talent_recommendation.application_created",
                AuditLog.target_id == application.id,
            )
        ) == 1


@pytest.mark.asyncio
async def test_select_accepts_twenty_completed_candidates_in_one_request(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created_run = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created_run.json()["run"]["id"])
        result_ids = add_bulk_completed_results(dependency, run_id, count=20)
        selected = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload(result_ids),
        )

    assert selected.status_code == 200, selected.text
    assert selected.json()["created_count"] == 20
    assert selected.json()["existing_count"] == 0
    assert selected.json()["failed_count"] == 0
    assert len(selected.json()["items"]) == 20
    with dependency.session_factory() as db:
        assert db.scalar(
            select(func.count(JobApplication.id)).where(
                JobApplication.job_id == dependency.job_id,
                JobApplication.source_type == "talent_recommendation",
            )
        ) == 20
        assert db.scalar(
            select(func.count(ScreeningResult.id))
            .join(JobApplication, JobApplication.id == ScreeningResult.application_id)
            .where(
                JobApplication.job_id == dependency.job_id,
                JobApplication.source_type == "talent_recommendation",
            )
        ) == 20
@pytest.mark.asyncio
async def test_select_requires_confirmation_when_primary_document_changed(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created_run = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created_run.json()["run"]["id"])
        result_id = complete_recommendation_result(dependency, run_id)
        with dependency.session_factory() as db:
            candidate = db.scalar(
                select(Candidate).where(Candidate.full_name == "推荐候选人")
            )
            assert candidate is not None
            application = db.scalar(
                select(JobApplication).where(
                    JobApplication.candidate_id == candidate.id,
                    JobApplication.job_id != dependency.job_id,
                )
            )
            assert application is not None
            old_document = db.get(ResumeDocument, application.primary_document_id)
            assert old_document is not None and old_document.batch is not None
            new_document = ResumeDocument(
                batch=old_document.batch,
                candidate=candidate,
                application=application,
                original_filename="talent-latest.pdf",
                file_extension=".pdf",
                content_type="application/pdf",
                detected_type="pdf",
                size_bytes=120,
                sha256="e" * 64,
                status="completed",
            )
            db.add(new_document)
            db.flush()
            application.document_links.append(
                ApplicationResumeDocument(document=new_document)
            )
            application.primary_document = new_document
            db.commit()

        blocked = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )
        confirmed = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload(
                [result_id],
                confirmed_stale_result_ids=[result_id],
            ),
        )

    assert blocked.status_code == 200
    assert blocked.json()["items"][0]["failure_code"] == "primary_document_changed"
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["items"][0]["status"] == "created"
    with dependency.session_factory() as db:
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == "talent_recommendation.application_created")
            .order_by(AuditLog.created_at.desc())
        )
        assert audit is not None
        assert audit.details["used_locked_stale_document"] is True


@pytest.mark.asyncio
async def test_partial_selection_isolated_and_invalid_snapshot_rolls_back_item(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created_run = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created_run.json()["run"]["id"])
        valid_result_id = complete_recommendation_result(dependency, run_id)
        failed_result_id = complete_recommendation_result(
            dependency,
            run_id,
            candidate_name="已经应聘目标职位的人才",
            vector_rank=2,
            result_status="failed",
        )
        selected = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([failed_result_id, valid_result_id]),
        )

    assert selected.status_code == 200, selected.text
    assert selected.json()["created_count"] == 1
    assert selected.json()["failed_count"] == 1
    assert selected.json()["items"][0]["failure_code"] == "result_not_completed"
    assert selected.json()["items"][1]["status"] == "created"

    with dependency.session_factory() as db:
        created_candidate = db.scalar(
            select(Candidate).where(Candidate.full_name == "推荐候选人")
        )
        assert created_candidate is not None
        assert db.scalar(
            select(func.count(JobApplication.id)).where(
                JobApplication.job_id == dependency.job_id,
                JobApplication.candidate_id == created_candidate.id,
                JobApplication.status == "active",
            )
        ) == 1


@pytest.mark.asyncio
async def test_invalid_screening_snapshot_does_not_leave_partial_application(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created_run = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created_run.json()["run"]["id"])
        result_id = complete_recommendation_result(
            dependency,
            run_id,
            invalid_snapshot=True,
        )
        selected = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )

    assert selected.status_code == 200
    assert selected.json()["created_count"] == 0
    assert selected.json()["failed_count"] == 1
    assert selected.json()["items"][0]["failure_code"] == "screening_snapshot_invalid"
    with dependency.session_factory() as db:
        candidate = db.scalar(
            select(Candidate).where(Candidate.full_name == "推荐候选人")
        )
        assert candidate is not None
        assert db.scalar(
            select(func.count(JobApplication.id)).where(
                JobApplication.job_id == dependency.job_id,
                JobApplication.candidate_id == candidate.id,
            )
        ) == 0
        assert db.scalar(
            select(func.count(ScreeningResult.id)).where(
                ScreeningResult.application_id.in_(
                    select(JobApplication.id).where(
                        JobApplication.job_id == dependency.job_id,
                        JobApplication.candidate_id == candidate.id,
                    )
                )
            )
        ) == 0


@pytest.mark.asyncio
async def test_selection_rejects_inactive_membership_stale_criteria_and_archived_job(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created_run = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created_run.json()["run"]["id"])
        result_id = complete_recommendation_result(dependency, run_id)
        with dependency.session_factory() as db:
            candidate = db.scalar(
                select(Candidate).where(Candidate.full_name == "推荐候选人")
            )
            assert candidate is not None
            membership = db.scalar(
                select(TalentPoolMembership).where(
                    TalentPoolMembership.candidate_id == candidate.id,
                    TalentPoolMembership.group_id == dependency.group_id,
                )
            )
            assert membership is not None
            membership.status = "removed"
            membership.removed_at = datetime.now(UTC)
            db.commit()
        inactive = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )
        with dependency.session_factory() as db:
            membership = db.scalar(
                select(TalentPoolMembership).where(
                    TalentPoolMembership.group_id == dependency.group_id,
                    TalentPoolMembership.candidate.has(full_name="推荐候选人"),
                )
            )
            assert membership is not None
            membership.status = "active"
            membership.removed_at = None
            run = db.get(TalentRecommendationRun, run_id)
            assert run is not None
            run.criteria_stale = True
            run.criteria_stale_at = datetime.now(UTC)
            db.commit()
        stale = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )
        with dependency.session_factory() as db:
            run = db.get(TalentRecommendationRun, run_id)
            job = db.get(Job, dependency.job_id)
            assert run is not None and job is not None
            run.criteria_stale = False
            run.criteria_stale_at = None
            job.status = "archived"
            job.archived_at = datetime.now(UTC)
            db.commit()
        archived = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )

    assert inactive.status_code == 200
    assert inactive.json()["items"][0]["failure_code"] == "talent_pool_membership_inactive"
    assert stale.status_code == 409
    assert stale.json()["detail"] == "职位筛选标准已变化，请重新创建推荐任务"
    assert archived.status_code == 409
    assert archived.json()["detail"] == "已归档职位不能接收推荐候选人"


@pytest.mark.asyncio
async def test_selection_validates_payload_and_role_permissions(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created_run = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created_run.json()["run"]["id"])
        result_id = complete_recommendation_result(dependency, run_id)
        duplicate = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id, result_id]),
        )
        unrelated_confirmation = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload(
                [result_id],
                confirmed_stale_result_ids=[uuid.uuid4()],
            ),
        )
        await login(client, "recommendation-manager")
        manager = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )
        await login(client, "recommendation-other")
        other_recruiter = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )
        await login(client, "recommendation-admin")
        administrator = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )

    assert duplicate.status_code == 422
    assert unrelated_confirmation.status_code == 422
    assert manager.status_code == 403
    assert other_recruiter.status_code == 404
    assert administrator.status_code == 200
    assert administrator.json()["created_count"] == 1


@pytest.mark.asyncio
async def test_selection_resolves_merged_candidate_before_duplicate_check(
    recommendation_route_dependencies: RecommendationRouteDependencies,
) -> None:
    dependency = recommendation_route_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recommendation-owner")
        created_run = await client.post(
            f"/jobs/{dependency.job_id}/recommendations",
            json=create_payload(dependency),
        )
        run_id = uuid.UUID(created_run.json()["run"]["id"])
        result_id = complete_recommendation_result(dependency, run_id)
        with dependency.session_factory() as db:
            source = db.scalar(
                select(Candidate).where(Candidate.full_name == "推荐候选人")
            )
            actor = db.scalar(select(User).where(User.username == "recommendation-owner"))
            assert source is not None and actor is not None
            target = Candidate(full_name="合并后保留候选人")
            review = CandidateDuplicateReview(
                candidate_a=target,
                candidate_b=source,
                source_document_id=source.documents[0].id,
                confidence="strong",
                signals=["same_person"],
                status="pending",
            )
            db.add_all([target, review])
            db.commit()
            merge_duplicate_candidates(
                db,
                review=review,
                target_candidate=target,
                source_candidate=source,
                actor=actor,
                reason="验证推荐转应聘前解析候选人合并",
            )
            db.commit()
            target_id = target.id

        selected = await client.post(
            f"/jobs/{dependency.job_id}/recommendations/{run_id}/select",
            json=selection_payload([result_id]),
        )

    assert selected.status_code == 200, selected.text
    assert selected.json()["items"][0]["status"] == "created"
    with dependency.session_factory() as db:
        application = db.get(
            JobApplication,
            uuid.UUID(selected.json()["items"][0]["application_id"]),
        )
        result = db.get(TalentRecommendationResult, result_id)
        assert application is not None and result is not None
        assert application.candidate_id == target_id
        assert result.resolved_candidate_id == target_id
        assert result.candidate_id != target_id
