import asyncio
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    ApplicationResumeDocument,
    AuditLog,
    Candidate,
    CandidateProfile,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeEmbeddingChunk,
    Role,
    ScoringDimension,
    ScreeningBatch,
    TalentPoolGroup,
    TalentPoolMembership,
    TalentRecommendationResult,
    TalentRecommendationRun,
    TalentRecommendationRunCandidate,
    TalentRecommendationRunEvent,
    TalentRecommendationRunGroup,
    User,
    UserRole,
)
from app.services.embedding_client import EmbeddingUpstreamError
from app.services.security import hash_password
from app.services.talent_recommendation_retrieval import (
    MatchedChunk,
    VectorSearchMatch,
    build_retrieval_query,
    retrieve_talent_recommendations,
)


class StubEmbeddingClient:
    model = "test-embedding"
    dimension = 2
    version = "v1"
    batch_size = 16

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.error is not None:
            raise self.error
        return [[1.0, 0.0] for _ in texts]


@dataclass(frozen=True)
class RetrievalDependencies:
    session_factory: sessionmaker[Session]
    run_id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    profile_id: uuid.UUID
    document_id: uuid.UUID
    group_ids: tuple[uuid.UUID, uuid.UUID]
    excluded_candidate_id: uuid.UUID


@pytest.fixture
def retrieval_dependencies() -> Generator[RetrievalDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        recruiter_role = Role(key="recruiter", display_name="招聘专员")
        recruiter = User(
            username="retrieval-recruiter",
            password_hash=hash_password("temporary-password"),
            display_name="向量召回招聘专员",
            role_assignments=[UserRole(role=recruiter_role)],
        )
        target_job = Job(
            owner=recruiter,
            title="向量召回目标职位",
            department="研发",
            original_jd="负责企业招聘平台。",
        )
        source_job = Job(
            owner=recruiter,
            title="人才来源职位",
            department="研发",
            original_jd="用于沉淀人才。",
        )
        target_criteria = JobCriteriaVersion(
            job=target_job,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_by_id=recruiter.id,
            confirmed_at=datetime.now(UTC),
            scoring_dimensions=[
                ScoringDimension(
                    name="Python 工程能力",
                    description="能够建设稳定后端服务",
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
                    description="来源职位评分",
                    weight_percent=100,
                    sort_order=0,
                )
            ],
        )
        group_a = TalentPoolGroup(name="后端人才", created_by=recruiter)
        group_b = TalentPoolGroup(name="平台人才", created_by=recruiter)
        candidate = Candidate(full_name="向量候选人")
        excluded_candidate = Candidate(full_name="已有应聘候选人")
        db.add_all(
            [
                recruiter_role,
                recruiter,
                target_job,
                source_job,
                target_criteria,
                source_criteria,
                group_a,
                group_b,
                candidate,
                excluded_candidate,
            ]
        )
        db.flush()
        source_application = JobApplication(candidate=candidate, job=source_job)
        excluded_source_application = JobApplication(
            candidate=excluded_candidate,
            job=source_job,
        )
        excluded_target_application = JobApplication(
            candidate=excluded_candidate,
            job=target_job,
        )
        batch = ScreeningBatch(
            job=source_job,
            criteria_version=source_criteria,
            name="人才来源批次",
            status="completed",
        )
        document = ResumeDocument(
            batch=batch,
            candidate=candidate,
            application=source_application,
            original_filename="candidate.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            sha256="a" * 64,
            status="completed",
        )
        excluded_document = ResumeDocument(
            batch=batch,
            candidate=excluded_candidate,
            application=excluded_source_application,
            original_filename="excluded.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            sha256="b" * 64,
            status="completed",
        )
        db.add_all(
            [
                source_application,
                excluded_source_application,
                excluded_target_application,
                batch,
                document,
                excluded_document,
            ]
        )
        db.flush()
        db.add_all(
            [
                ApplicationResumeDocument(
                    application=source_application,
                    document=document,
                ),
                ApplicationResumeDocument(
                    application=excluded_source_application,
                    document=excluded_document,
                ),
            ]
        )
        source_application.primary_document = document
        excluded_source_application.primary_document = excluded_document
        profile = CandidateProfile(
            document=document,
            version_number=1,
            source="ai",
            model_name="profile-test",
            prompt_version="profile-v1",
            education=[],
            work_experiences=[
                {
                    "company": "示例科技",
                    "title": "后端工程师",
                    "summary": "使用 Python 建设招聘平台",
                }
            ],
            projects=[],
            skills=[{"name": "Python", "level": "熟练"}],
            certifications=[],
            languages=[],
        )
        excluded_profile = CandidateProfile(
            document=excluded_document,
            version_number=1,
            source="ai",
            model_name="profile-test",
            prompt_version="profile-v1",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[{"name": "Python"}],
            certifications=[],
            languages=[],
        )
        memberships = [
            TalentPoolMembership(
                group=group_a,
                candidate=candidate,
                source_application=source_application,
                reason="后端人才",
                updated_by=recruiter,
            ),
            TalentPoolMembership(
                group=group_b,
                candidate=candidate,
                source_application=source_application,
                reason="平台人才",
                updated_by=recruiter,
            ),
            TalentPoolMembership(
                group=group_a,
                candidate=excluded_candidate,
                source_application=excluded_source_application,
                reason="已有目标应聘",
                updated_by=recruiter,
            ),
        ]
        db.add_all([profile, excluded_profile, *memberships])
        db.flush()
        chunk = ResumeEmbeddingChunk(
            document=document,
            candidate_profile=profile,
            profile_version=1,
            chunk_type="summary",
            chunk_index=0,
            chunk_text="候选人结构化摘要\n技能：Python",
            source_segment_keys=["SEG-0001"],
            content_hash="c" * 64,
            embedding_model="test-embedding",
            embedding_dimension=2,
            embedding_version="v1",
            embedding=[1.0, 0.0],
            status="completed",
            attempt_count=1,
            embedded_at=datetime.now(UTC),
        )
        criteria_snapshot = {
            "version_number": 1,
            "pass_threshold": 60,
            "hard_requirements": [],
            "scoring_dimensions": [
                {
                    "name": "Python 工程能力",
                    "description": "能够建设稳定后端服务",
                    "weight_percent": 100,
                    "sort_order": 0,
                }
            ],
        }
        run = TalentRecommendationRun(
            job=target_job,
            criteria_version=target_criteria,
            created_by=recruiter,
            created_by_username_snapshot=recruiter.username,
            created_by_display_name_snapshot=recruiter.display_name,
            idempotency_key=uuid.uuid4(),
            status="queued",
            ai_input_mode="raw",
            criteria_snapshot=criteria_snapshot,
            embedding_model_snapshot="test-embedding",
            ai_model_snapshot="test-ai",
            prompt_version_snapshot="test-prompt",
            celery_task_id="retrieval-task-1",
            scope_candidate_count=1,
            excluded_count=1,
            group_snapshots=[
                TalentRecommendationRunGroup(
                    group=group_a,
                    group_name_snapshot=group_a.name,
                    group_version_snapshot=group_a.version,
                ),
                TalentRecommendationRunGroup(
                    group=group_b,
                    group_name_snapshot=group_b.name,
                    group_version_snapshot=group_b.version,
                ),
            ],
            candidate_snapshots=[
                TalentRecommendationRunCandidate(
                    candidate=candidate,
                    candidate_code_snapshot=candidate.candidate_code,
                    candidate_name_snapshot=candidate.full_name,
                    document=document,
                    document_sha256_snapshot=document.sha256,
                    document_updated_at_snapshot=document.updated_at,
                    candidate_profile=profile,
                    profile_version_snapshot=profile.version_number,
                    embedding_model_snapshot="test-embedding",
                    embedding_version_snapshot="v1",
                    embedding_dimension_snapshot=2,
                    matched_group_ids=[str(group_a.id), str(group_b.id)],
                )
            ],
        )
        db.add_all([chunk, run])
        db.commit()
        dependencies = RetrievalDependencies(
            session_factory=testing_session,
            run_id=run.id,
            job_id=target_job.id,
            candidate_id=candidate.id,
            profile_id=profile.id,
            document_id=document.id,
            group_ids=(group_a.id, group_b.id),
            excluded_candidate_id=excluded_candidate.id,
        )
    yield dependencies
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_build_retrieval_query_uses_confirmed_criteria_content() -> None:
    text = build_retrieval_query(
        {
            "hard_requirements": [
                {
                    "title": "工作年限",
                    "expected_value": "3 年",
                    "description": "Python 后端经验",
                }
            ],
            "scoring_dimensions": [
                {
                    "name": "系统设计",
                    "description": "可扩展架构",
                    "weight_percent": 60,
                }
            ],
        }
    )
    assert "工作年限" in text
    assert "Python 后端经验" in text
    assert "系统设计" in text
    assert "权重 60%" in text


def test_retrieval_saves_top_candidate_and_moves_run_to_rescoring(
    retrieval_dependencies: RetrievalDependencies,
) -> None:
    dependency = retrieval_dependencies
    client = StubEmbeddingClient()
    received_choices = []

    def vector_search(_db, *, choices, query_vector, client, limit):
        received_choices.extend(choices)
        assert query_vector == [1.0, 0.0]
        assert client.model == "test-embedding"
        assert limit == 50
        return [
            VectorSearchMatch(
                profile_id=dependency.profile_id,
                similarity_score=0.875,
                chunks=(
                    MatchedChunk(
                        chunk_type="summary",
                        chunk_index=0,
                        quote="技能：Python",
                        source_segment_keys=("SEG-0001",),
                        similarity_score=0.875,
                    ),
                ),
            )
        ]

    result = asyncio.run(
        retrieve_talent_recommendations(
            dependency.run_id,
            task_id="retrieval-task-1",
            session_factory=dependency.session_factory,
            embedding_client=client,
            vector_search=vector_search,
        )
    )

    assert result == {
        "status": "rescoring",
        "run_id": str(dependency.run_id),
        "retrieved_count": 1,
        "excluded_count": 1,
    }
    assert len(received_choices) == 1
    assert received_choices[0].candidate_id == dependency.candidate_id
    assert set(received_choices[0].group_ids) == set(dependency.group_ids)
    assert client.calls and "Python 工程能力" in client.calls[0][0]

    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        assert run is not None
        assert run.status == "rescoring"
        assert run.retrieved_count == 1
        assert run.excluded_count == 1
        assert run.completed_at is None
        recommendation = db.scalar(
            select(TalentRecommendationResult).where(
                TalentRecommendationResult.run_id == dependency.run_id
            )
        )
        assert recommendation is not None
        assert recommendation.candidate_id == dependency.candidate_id
        assert recommendation.resolved_candidate_id == dependency.candidate_id
        assert recommendation.document_id == dependency.document_id
        assert recommendation.vector_rank == 1
        assert float(recommendation.similarity_score) == 0.875
        assert set(recommendation.matched_group_ids) == {
            str(group_id) for group_id in dependency.group_ids
        }
        assert recommendation.matched_chunks[0]["quote"] == "技能：Python"
        event_types = list(
            db.scalars(
                select(TalentRecommendationRunEvent.event_type)
                .where(TalentRecommendationRunEvent.run_id == dependency.run_id)
                .order_by(TalentRecommendationRunEvent.sequence_number)
            )
        )
        assert event_types == ["retrieval_started", "retrieval_completed"]
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.target_id == dependency.run_id
                )
            )
            == 2
        )


def test_retrieval_builds_missing_index_before_search(
    retrieval_dependencies: RetrievalDependencies,
) -> None:
    dependency = retrieval_dependencies
    client = StubEmbeddingClient()
    indexed: list[uuid.UUID] = []
    with dependency.session_factory() as db:
        chunk = db.scalar(
            select(ResumeEmbeddingChunk).where(
                ResumeEmbeddingChunk.candidate_profile_id == dependency.profile_id
            )
        )
        assert chunk is not None
        chunk.status = "failed"
        chunk.embedding = None
        chunk.failure_code = "old_failure"
        db.commit()

    async def index_profile(profile_id, **kwargs):
        indexed.append(profile_id)
        with dependency.session_factory() as db:
            chunk = db.scalar(
                select(ResumeEmbeddingChunk).where(
                    ResumeEmbeddingChunk.candidate_profile_id == profile_id
                )
            )
            assert chunk is not None
            chunk.status = "completed"
            chunk.embedding = [1.0, 0.0]
            chunk.failure_code = None
            chunk.embedded_at = datetime.now(UTC)
            db.commit()
        return {"status": "completed", "chunk_count": 1}

    def vector_search(_db, *, choices, **_kwargs):
        return [
            VectorSearchMatch(
                profile_id=choices[0].profile_id,
                similarity_score=0.75,
                chunks=(),
            )
        ]

    result = asyncio.run(
        retrieve_talent_recommendations(
            dependency.run_id,
            task_id="retrieval-task-1",
            session_factory=dependency.session_factory,
            embedding_client=client,
            index_profile=index_profile,
            vector_search=vector_search,
        )
    )
    assert result["status"] == "rescoring"
    assert indexed == [dependency.profile_id]


def test_retrieval_uses_locked_document_after_primary_resume_changes(
    retrieval_dependencies: RetrievalDependencies,
) -> None:
    dependency = retrieval_dependencies
    with dependency.session_factory() as db:
        application = db.scalar(
            select(JobApplication).where(
                JobApplication.candidate_id == dependency.candidate_id
            )
        )
        source_document = db.get(ResumeDocument, dependency.document_id)
        assert application is not None and source_document is not None
        replacement = ResumeDocument(
            batch_id=source_document.batch_id,
            candidate_id=dependency.candidate_id,
            application_id=application.id,
            original_filename="replacement.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            sha256="f" * 64,
            status="completed",
        )
        db.add(replacement)
        db.flush()
        db.add(
            ApplicationResumeDocument(
                application_id=application.id,
                document_id=replacement.id,
            )
        )
        application.primary_document_id = replacement.id
        db.commit()

    result = asyncio.run(
        retrieve_talent_recommendations(
            dependency.run_id,
            task_id="retrieval-task-1",
            session_factory=dependency.session_factory,
            embedding_client=StubEmbeddingClient(),
            vector_search=lambda _db, *, choices, **_kwargs: [
                VectorSearchMatch(
                    profile_id=choices[0].profile_id,
                    similarity_score=0.7,
                    chunks=(),
                )
            ],
        )
    )
    assert result["status"] == "rescoring"
    with dependency.session_factory() as db:
        recommendation = db.scalar(
            select(TalentRecommendationResult).where(
                TalentRecommendationResult.run_id == dependency.run_id
            )
        )
        assert recommendation is not None
        assert recommendation.document_id == dependency.document_id
        assert recommendation.document_stale is True
        assert recommendation.stale_at is not None


def test_retrieval_failure_is_persisted_and_redelivery_is_superseded(
    retrieval_dependencies: RetrievalDependencies,
) -> None:
    dependency = retrieval_dependencies
    superseded_client = StubEmbeddingClient()
    superseded = asyncio.run(
        retrieve_talent_recommendations(
            dependency.run_id,
            task_id="different-task",
            session_factory=dependency.session_factory,
            embedding_client=superseded_client,
        )
    )
    assert superseded == {"status": "superseded", "run_id": str(dependency.run_id)}
    assert superseded_client.calls == []

    failed_client = StubEmbeddingClient(error=EmbeddingUpstreamError("服务不可用"))
    failed = asyncio.run(
        retrieve_talent_recommendations(
            dependency.run_id,
            task_id="retrieval-task-1",
            session_factory=dependency.session_factory,
            embedding_client=failed_client,
        )
    )
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "embedding_upstream_failed"
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.completed_at is not None
        assert run.failure_code == "embedding_upstream_failed"


def test_empty_retrieval_completes_without_entering_ai_rescoring(
    retrieval_dependencies: RetrievalDependencies,
) -> None:
    dependency = retrieval_dependencies
    result = asyncio.run(
        retrieve_talent_recommendations(
            dependency.run_id,
            task_id="retrieval-task-1",
            session_factory=dependency.session_factory,
            embedding_client=StubEmbeddingClient(),
            vector_search=lambda *_args, **_kwargs: [],
        )
    )
    assert result["status"] == "completed"
    assert result["retrieved_count"] == 0
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.completed_at is not None
        assert run.retrieved_count == 0
