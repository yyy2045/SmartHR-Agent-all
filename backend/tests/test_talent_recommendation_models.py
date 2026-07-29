import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    ApplicationResumeDocument,
    Candidate,
    CandidateDuplicateReview,
    CandidateProfile,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ScreeningBatch,
    TalentPoolGroup,
    TalentRecommendationResult,
    TalentRecommendationRun,
    TalentRecommendationRunEvent,
    TalentRecommendationRunGroup,
    User,
)
from app.services.candidate_merging import merge_duplicate_candidates
from app.services.security import hash_password


@dataclass(frozen=True)
class RecommendationDependencies:
    user: User
    job: Job
    criteria: JobCriteriaVersion
    group: TalentPoolGroup
    candidate: Candidate
    application: JobApplication
    document: ResumeDocument
    profile: CandidateProfile
    run: TalentRecommendationRun
    result: TalentRecommendationResult


@pytest.fixture
def recommendation_session() -> Session:
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

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.drop_all(connection)
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    engine.dispose()


def _run(
    dependency: RecommendationDependencies | None,
    *,
    user: User,
    job: Job,
    criteria: JobCriteriaVersion,
    idempotency_key: uuid.UUID | None = None,
) -> TalentRecommendationRun:
    return TalentRecommendationRun(
        job=job,
        criteria_version=criteria,
        created_by=user,
        created_by_username_snapshot=user.username,
        created_by_display_name_snapshot=user.display_name,
        idempotency_key=idempotency_key or uuid.uuid4(),
        status="queued",
        ai_input_mode="raw",
        criteria_snapshot={
            "version_number": criteria.version_number,
            "pass_threshold": criteria.pass_threshold,
        },
        embedding_model_snapshot="text-embedding-test",
        ai_model_snapshot="screening-model-test",
        prompt_version_snapshot="resume-match-v2",
    )


def _result(
    *,
    run: TalentRecommendationRun,
    candidate: Candidate,
    document: ResumeDocument,
    profile: CandidateProfile,
    rank: int = 1,
) -> TalentRecommendationResult:
    assert document.sha256 is not None and document.updated_at is not None
    return TalentRecommendationResult(
        run=run,
        candidate=candidate,
        resolved_candidate=candidate,
        candidate_code_snapshot=candidate.candidate_code,
        candidate_name_snapshot=candidate.full_name,
        document=document,
        document_sha256_snapshot=document.sha256,
        document_updated_at_snapshot=document.updated_at,
        candidate_profile=profile,
        profile_version_snapshot=profile.version_number,
        embedding_model_snapshot="text-embedding-test",
        embedding_version_snapshot="v1",
        embedding_dimension_snapshot=3,
        vector_rank=rank,
        similarity_score=Decimal("0.81234567"),
        matched_group_ids=[],
        matched_chunks=[{"segment_key": "SEG-0001", "quote": "Python"}],
        status="retrieved",
    )


def _dependencies(db: Session) -> RecommendationDependencies:
    user = User(
        username="recommendation-owner",
        password_hash=hash_password("correct-password"),
        display_name="推荐任务负责人",
    )
    job = Job(
        owner=user,
        title="推荐目标职位",
        department="研发",
        original_jd="负责平台研发。",
    )
    criteria = JobCriteriaVersion(
        job=job,
        version_number=1,
        status="confirmed",
        pass_threshold=60,
        confirmed_by_id=user.id,
    )
    group = TalentPoolGroup(name="平台人才", created_by=user)
    candidate = Candidate(full_name="人才候选人")
    db.add_all([user, job, criteria, group, candidate])
    db.flush()
    criteria.confirmed_by_id = user.id

    application = JobApplication(candidate=candidate, job=job)
    db.add(application)
    db.flush()
    batch = ScreeningBatch(
        job=job,
        criteria_version=criteria,
        name="人才推荐来源",
        status="completed",
    )
    document = ResumeDocument(
        batch=batch,
        candidate=candidate,
        application=application,
        original_filename="candidate.pdf",
        file_extension=".pdf",
        content_type="application/pdf",
        detected_type="pdf",
        size_bytes=100,
        sha256="a" * 64,
        status="completed",
    )
    profile = CandidateProfile(
        document=document,
        version_number=1,
        source="ai",
        model_name="profile-model",
        prompt_version="profile-v1",
        education=[],
        work_experiences=[],
        projects=[],
        skills=[],
        certifications=[],
        languages=[],
    )
    db.add_all([application, batch, document, profile])
    db.flush()
    db.add(
        ApplicationResumeDocument(
            application_id=application.id,
            document_id=document.id,
        )
    )
    db.flush()
    application.primary_document_id = document.id

    run = _run(None, user=user, job=job, criteria=criteria)
    run.group_snapshots = [
        TalentRecommendationRunGroup(
            group=group,
            group_name_snapshot=group.name,
            group_version_snapshot=group.version,
        )
    ]
    run.events = [
        TalentRecommendationRunEvent(
            sequence_number=1,
            idempotency_key=uuid.uuid4(),
            event_type="created",
            from_status=None,
            to_status="queued",
            details={"source": "test"},
            actor_user=user,
            actor_username_snapshot=user.username,
            actor_display_name_snapshot=user.display_name,
        )
    ]
    result = _result(run=run, candidate=candidate, document=document, profile=profile)
    db.add_all([run, result])
    db.commit()
    return RecommendationDependencies(
        user=user,
        job=job,
        criteria=criteria,
        group=group,
        candidate=candidate,
        application=application,
        document=document,
        profile=profile,
        run=run,
        result=result,
    )


def test_recommendation_run_locks_groups_input_and_candidate_snapshots(
    recommendation_session: Session,
) -> None:
    dependency = _dependencies(recommendation_session)

    assert dependency.run.status == "queued"
    assert dependency.run.recall_limit == 50
    assert dependency.run.rescore_limit == 20
    assert dependency.run.criteria_snapshot == {
        "version_number": 1,
        "pass_threshold": 60,
    }
    assert [item.group_name_snapshot for item in dependency.run.group_snapshots] == ["平台人才"]
    assert dependency.result.candidate_id == dependency.candidate.id
    assert dependency.result.resolved_candidate_id == dependency.candidate.id
    assert dependency.result.document_id == dependency.document.id
    assert dependency.result.profile_version_snapshot == 1
    assert dependency.result.vector_rank == 1
    assert dependency.result.status == "retrieved"
    assert [item.event_type for item in dependency.run.events] == ["created"]


def test_run_idempotency_result_candidate_and_event_keys_are_unique(
    recommendation_session: Session,
) -> None:
    dependency = _dependencies(recommendation_session)
    duplicate_run = _run(
        dependency,
        user=dependency.user,
        job=dependency.job,
        criteria=dependency.criteria,
        idempotency_key=dependency.run.idempotency_key,
    )
    recommendation_session.add(duplicate_run)
    with pytest.raises(IntegrityError):
        recommendation_session.commit()
    recommendation_session.rollback()

    duplicate_result = _result(
        run=dependency.run,
        candidate=dependency.candidate,
        document=dependency.document,
        profile=dependency.profile,
        rank=2,
    )
    recommendation_session.add(duplicate_result)
    with pytest.raises(IntegrityError):
        recommendation_session.commit()
    recommendation_session.rollback()

    duplicate_event = TalentRecommendationRunEvent(
        run_id=dependency.run.id,
        sequence_number=2,
        idempotency_key=dependency.run.events[0].idempotency_key,
        event_type="retry_requested",
        from_status="failed",
        to_status="failed",
        details={},
    )
    recommendation_session.add(duplicate_event)
    with pytest.raises(IntegrityError):
        recommendation_session.commit()


def test_invalid_run_counts_and_result_terminal_contract_are_rejected(
    recommendation_session: Session,
) -> None:
    dependency = _dependencies(recommendation_session)
    dependency.run.retrieved_count = 21
    dependency.run.rescored_count = 21
    with pytest.raises(IntegrityError):
        recommendation_session.commit()
    recommendation_session.rollback()

    dependency.result.status = "completed"
    dependency.result.completed_at = datetime.now(UTC)
    with pytest.raises(IntegrityError):
        recommendation_session.commit()


def test_input_snapshots_and_completed_ai_output_cannot_be_overwritten(
    recommendation_session: Session,
) -> None:
    dependency = _dependencies(recommendation_session)
    dependency.run.criteria_snapshot = {"version_number": 2}
    with pytest.raises(ValueError, match="推荐运行输入快照不可修改"):
        recommendation_session.flush()
    recommendation_session.rollback()

    dependency.result.matched_chunks = [{"segment_key": "SEG-CHANGED"}]
    with pytest.raises(ValueError, match="推荐结果输入快照不可修改"):
        recommendation_session.flush()
    recommendation_session.rollback()

    dependency.result.status = "rescoring"
    dependency.result.processing_attempt_count = 1
    recommendation_session.commit()
    dependency.result.status = "completed"
    dependency.result.ai_score = Decimal("88.00")
    dependency.result.ai_group = "passed"
    dependency.result.ai_dimension_scores = [{"name": "技能", "score": 88}]
    dependency.result.ai_evidence = [{"quote": "Python"}]
    dependency.result.ai_model_snapshot = "screening-model-test"
    dependency.result.prompt_version_snapshot = "resume-match-v2"
    dependency.result.completed_at = datetime.now(UTC)
    recommendation_session.commit()

    dependency.result.ai_score = Decimal("90.00")
    with pytest.raises(ValueError, match="已完成推荐结果不可覆盖"):
        recommendation_session.flush()
    recommendation_session.rollback()

    dependency.result.document_stale = True
    dependency.result.stale_at = datetime.now(UTC)
    recommendation_session.commit()
    assert dependency.result.document_stale is True


def test_run_events_are_append_only(recommendation_session: Session) -> None:
    dependency = _dependencies(recommendation_session)
    run_event = dependency.run.events[0]
    run_event.details = {"changed": True}
    with pytest.raises(ValueError, match="推荐运行事件不可修改"):
        recommendation_session.flush()
    recommendation_session.rollback()

    stored_event = recommendation_session.get(TalentRecommendationRunEvent, run_event.id)
    assert stored_event is not None
    recommendation_session.delete(stored_event)
    with pytest.raises(ValueError, match="推荐运行事件不可删除"):
        recommendation_session.flush()


def test_candidate_merge_updates_resolution_but_keeps_original_snapshot(
    recommendation_session: Session,
) -> None:
    dependency = _dependencies(recommendation_session)
    target = Candidate(full_name="保留候选人")
    review = CandidateDuplicateReview(
        candidate_a=target,
        candidate_b=dependency.candidate,
        source_document_id=dependency.document.id,
        confidence="strong",
        signals=["same_person"],
        status="pending",
    )
    recommendation_session.add_all([target, review])
    recommendation_session.commit()

    merge_duplicate_candidates(
        recommendation_session,
        review=review,
        target_candidate=target,
        source_candidate=dependency.candidate,
        actor=dependency.user,
        reason="验证推荐快照在候选人合并后仍可追溯",
    )
    recommendation_session.commit()

    recommendation_session.refresh(dependency.result)
    assert dependency.result.candidate_id == dependency.candidate.id
    assert dependency.result.candidate_code_snapshot == dependency.candidate.candidate_code
    assert dependency.result.resolved_candidate_id == target.id
    assert dependency.result.candidate_merged_at is not None
    assert dependency.document.candidate_id == target.id
    assert dependency.application.candidate_id == target.id
    audit = recommendation_session.scalar(
        select(CandidateDuplicateReview).where(CandidateDuplicateReview.id == review.id)
    )
    assert audit is not None and audit.status == "merged"
