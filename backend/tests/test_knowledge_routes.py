import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    CandidateProfile,
    Job,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeEmbeddingChunk,
    Role,
    ScreeningBatch,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass(frozen=True)
class KnowledgeRouteDependencies:
    document_id: uuid.UUID
    profile_id: uuid.UUID
    batch_id: uuid.UUID
    session_factory: sessionmaker[Session]
    enqueued_profiles: list[tuple[uuid.UUID, bool]]


@pytest.fixture
def knowledge_route_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[KnowledgeRouteDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        recruiter_role = Role(key="recruiter", display_name="招聘专员")
        owner = User(
            username="job-owner",
            password_hash=hash_password("owner-password"),
            display_name="职位负责人",
            role_assignments=[UserRole(role=recruiter_role)],
        )
        recruiter = User(
            username="shared-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="共享招聘专员",
            role_assignments=[UserRole(role=recruiter_role)],
        )
        db.add_all([recruiter_role, owner, recruiter])
        db.flush()
        job = Job(
            owner_id=owner.id,
            title="平台工程师",
            department="研发中心",
            original_jd="负责企业平台建设。",
        )
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=owner.id,
            confirmed_at=datetime.now(UTC),
        )
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="共享人才库测试",
            status="completed",
        )
        db.add(batch)
        db.flush()
        document = ResumeDocument(
            batch_id=batch.id,
            original_filename="shared-candidate.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
        )
        db.add(document)
        db.flush()
        profile = CandidateProfile(
            document_id=document.id,
            version_number=1,
            source="ai",
            model_name="analysis-model",
            prompt_version="resume-match-v2",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[{"name": "Python", "level": "熟练", "evidence": []}],
            certifications=[],
            languages=[],
        )
        db.add(profile)
        db.commit()
        document_id = document.id
        profile_id = profile.id
        batch_id = batch.id

    session_store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    def override_session_store() -> SessionStore:
        return session_store

    enqueued_profiles: list[tuple[uuid.UUID, bool]] = []

    def enqueue(profile_id: uuid.UUID, *, force: bool = False) -> str:
        enqueued_profiles.append((profile_id, force))
        return "knowledge-task-1"

    monkeypatch.setattr("app.api.routes.knowledge.enqueue_knowledge_index", enqueue)
    monkeypatch.setattr(settings, "embedding_model", "test-embedding")
    monkeypatch.setattr(settings, "embedding_dimension", 3)
    monkeypatch.setattr(settings, "embedding_version", "test-v1")
    monkeypatch.setattr(settings, "embedding_enabled", False)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_session_store
    yield KnowledgeRouteDependencies(
        document_id=document_id,
        profile_id=profile_id,
        batch_id=batch_id,
        session_factory=testing_session,
        enqueued_profiles=enqueued_profiles,
    )
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login_shared_recruiter(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": "shared-recruiter", "password": "correct-password"},
    )
    assert response.status_code == 200


def add_chunk(
    dependency: KnowledgeRouteDependencies,
    *,
    chunk_index: int,
    status: str,
) -> None:
    with dependency.session_factory() as db:
        db.add(
            ResumeEmbeddingChunk(
                document_id=dependency.document_id,
                candidate_profile_id=dependency.profile_id,
                profile_version=1,
                chunk_type="skill",
                chunk_index=chunk_index,
                chunk_text=f"技能：测试 {chunk_index}",
                source_segment_keys=[],
                content_hash=f"{chunk_index:064x}",
                embedding_model="test-embedding",
                embedding_dimension=3,
                embedding_version="test-v1",
                status=status,
                attempt_count=1,
            )
        )
        db.commit()


@pytest.mark.asyncio
async def test_knowledge_status_requires_login_and_is_shared_across_recruiters(
    knowledge_route_dependencies: KnowledgeRouteDependencies,
) -> None:
    dependency = knowledge_route_dependencies
    path = f"/knowledge/documents/{dependency.document_id}/index"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get(path)
        await login_shared_recruiter(client)
        shared = await client.get(path)

    assert unauthorized.status_code == 401
    assert shared.status_code == 200
    assert shared.json() == {
        "document_id": str(dependency.document_id),
        "candidate_profile_id": str(dependency.profile_id),
        "profile_version": 1,
        "status": "not_indexed",
        "embedding_enabled": False,
        "embedding_model": "test-embedding",
        "embedding_dimension": 3,
        "embedding_version": "test-v1",
        "chunk_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "chunks": [],
    }


@pytest.mark.asyncio
async def test_knowledge_status_aggregates_completed_failed_and_partial_states(
    knowledge_route_dependencies: KnowledgeRouteDependencies,
) -> None:
    dependency = knowledge_route_dependencies
    path = f"/knowledge/documents/{dependency.document_id}/index"
    add_chunk(dependency, chunk_index=0, status="completed")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login_shared_recruiter(client)
        completed = await client.get(path)
        add_chunk(dependency, chunk_index=1, status="failed")
        partial = await client.get(path)
        with dependency.session_factory() as db:
            for chunk in db.scalars(select(ResumeEmbeddingChunk)):
                chunk.status = "failed"
            db.commit()
        failed = await client.get(path)

    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_count"] == 1
    assert partial.status_code == 200
    assert partial.json()["status"] == "partial_failure"
    assert partial.json()["completed_count"] == 1
    assert partial.json()["failed_count"] == 1
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["failed_count"] == 2


@pytest.mark.asyncio
async def test_rebuild_requires_embedding_and_records_successful_request(
    knowledge_route_dependencies: KnowledgeRouteDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = knowledge_route_dependencies
    path = f"/knowledge/documents/{dependency.document_id}/index/rebuild"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login_shared_recruiter(client)
        disabled = await client.post(path)
        monkeypatch.setattr(settings, "embedding_enabled", True)
        queued = await client.post(path)

    assert disabled.status_code == 409
    assert "尚未启用" in disabled.text
    assert queued.status_code == 202
    assert queued.json() == {
        "status": "queued",
        "document_id": str(dependency.document_id),
        "candidate_profile_id": str(dependency.profile_id),
        "profile_version": 1,
        "task_id": "knowledge-task-1",
    }
    assert dependency.enqueued_profiles == [(dependency.profile_id, True)]
    with dependency.session_factory() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "knowledge.index_rebuild_requested"
            )
        )
    assert audit is not None
    assert audit.actor_username == "shared-recruiter"
    assert audit.target_id == dependency.profile_id
    assert audit.result == "success"
    assert audit.details == {
        "profile_version": 1,
        "embedding_model": "test-embedding",
        "embedding_version": "test-v1",
    }


def test_deleting_batch_cascades_resume_embedding_chunks(
    knowledge_route_dependencies: KnowledgeRouteDependencies,
) -> None:
    dependency = knowledge_route_dependencies
    add_chunk(dependency, chunk_index=0, status="completed")

    with dependency.session_factory() as db:
        batch = db.get(ScreeningBatch, dependency.batch_id)
        assert batch is not None
        db.delete(batch)
        db.commit()
        assert db.scalar(select(func.count(ResumeEmbeddingChunk.id))) == 0
