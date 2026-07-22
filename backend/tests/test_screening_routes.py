import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
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
    CandidateProfile,
    DimensionScore,
    EvidenceCitation,
    Job,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeTextSegment,
    ScoringDimension,
    ScreeningBatch,
    ScreeningResult,
    User,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass(frozen=True)
class ScreeningRouteDependencies:
    job_id: uuid.UUID
    batch_id: uuid.UUID
    document_id: uuid.UUID
    session_factory: sessionmaker[Session]
    enqueued_document_ids: list[uuid.UUID]


@pytest.fixture
def screening_route_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[ScreeningRouteDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        user = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
        )
        db.add(user)
        db.flush()
        job = Job(owner_id=user.id, title="工程师", department="研发", original_jd="JD")
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_by_id=user.id,
        )
        dimension = ScoringDimension(
            name="工程能力",
            description="工程实践",
            weight_percent=100,
            sort_order=0,
        )
        criteria.scoring_dimensions = [dimension]
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="结果测试",
            status="completed",
        )
        db.add(batch)
        db.flush()
        document = ResumeDocument(
            batch_id=batch.id,
            original_filename="resume.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
            segment_count=1,
        )
        segment = ResumeTextSegment(
            segment_key="SEG-0001",
            source_type="pdf_page",
            source_index=1,
            page_number=1,
            raw_text="Python 工程经验",
            normalized_text="Python 工程经验",
            redacted_text="Python 工程经验",
            sort_order=0,
        )
        document.text_segments = [segment]
        db.add(document)
        db.flush()
        profile = CandidateProfile(
            document_id=document.id,
            version_number=1,
            source="ai",
            model_name="stub-model",
            prompt_version="resume-match-v1",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[
                {
                    "name": "Python",
                    "level": "熟练",
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": "Python"}
                    ],
                }
            ],
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
            interview_questions=["请介绍工程实践。"],
            model_name="stub-model",
            prompt_version="resume-match-v1",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        score = DimensionScore(
            scoring_dimension_id=dimension.id,
            dimension_name=dimension.name,
            score=88,
            weight_percent=100,
            weighted_score=Decimal("88.00"),
            rationale="具有工程经验。",
            missing_items=[],
            sort_order=0,
        )
        result.dimension_scores = [score]
        result.evidence_citations = [
            EvidenceCitation(
                dimension_score=score,
                segment=segment,
                subject_type="dimension",
                subject_key=str(dimension.id),
                segment_key="SEG-0001",
                quote="Python 工程经验",
                source_type="pdf_page",
                page_number=1,
                sort_order=0,
            )
        ]
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

    enqueued_document_ids: list[uuid.UUID] = []

    def enqueue(document_id: uuid.UUID) -> str:
        enqueued_document_ids.append(document_id)
        return "analysis-task-1"

    monkeypatch.setattr("app.api.routes.batches.enqueue_resume_analysis", enqueue)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_session_store
    yield ScreeningRouteDependencies(
        job_id=job.id,
        batch_id=batch.id,
        document_id=document.id,
        session_factory=testing_session,
        enqueued_document_ids=enqueued_document_ids,
    )
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": "recruiter", "password": "correct-password"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_analysis_detail_requires_authentication_and_returns_evidence(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    path = (
        f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}"
        f"/documents/{dependency.document_id}/analysis"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get(path)
        await login(client)
        response = await client.get(path)

    assert anonymous.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["ai_group"] == "passed"
    assert body["total_score"] == 88.0
    assert body["candidate_profile"]["skills"][0]["name"] == "Python"
    assert body["dimension_scores"][0]["evidence"][0]["segment_key"] == "SEG-0001"
    assert body["evidence"][0]["page_number"] == 1


@pytest.mark.asyncio
async def test_analysis_retry_queues_completed_document_and_blocks_processing_result(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    path = (
        f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}"
        f"/documents/{dependency.document_id}/analysis-retry"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        queued = await client.post(path)
        with dependency.session_factory() as db:
            batch = db.get(ScreeningBatch, dependency.batch_id)
            assert batch is not None
            db.add(
                ScreeningResult(
                    document_id=dependency.document_id,
                    criteria_version_id=batch.criteria_version_id,
                    analysis_version=2,
                    status="processing",
                    pass_threshold=60,
                    hard_requirement_results=[],
                    strengths=[],
                    gaps=[],
                    missing_items=[],
                    interview_questions=[],
                    model_name="stub-model",
                    prompt_version="resume-match-v1",
                    started_at=datetime.now(UTC),
                )
            )
            db.commit()
        blocked = await client.post(path)

    assert queued.status_code == 202
    assert queued.json() == {"status": "queued", "task_id": "analysis-task-1"}
    assert dependency.enqueued_document_ids == [dependency.document_id]
    assert blocked.status_code == 409
    assert "正在进行" in blocked.text
