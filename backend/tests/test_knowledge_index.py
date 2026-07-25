import asyncio
import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    CandidateProfile,
    Job,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeEmbeddingChunk,
    ScreeningBatch,
    User,
)
from app.services.embedding_client import EmbeddingUpstreamError
from app.services.knowledge_index import build_profile_chunks, index_candidate_profile
from app.services.security import hash_password


class StubEmbeddingClient:
    def __init__(
        self,
        *,
        model: str = "stub-embedding",
        version: str = "v1",
        error: Exception | None = None,
    ) -> None:
        self.model = model
        self.dimension = 3
        self.version = version
        self.batch_size = 2
        self.error = error
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.error is not None:
            raise self.error
        return [
            [float(index + 1), float(len(text)), 0.5]
            for index, text in enumerate(texts)
        ]


class CoordinatedEmbeddingClient(StubEmbeddingClient):
    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__()
        self.started = started
        self.release = release

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        self.started.set()
        await self.release.wait()
        return [[1.0, 0.0, 0.0] for _ in texts]


class MarkerEmbeddingClient(StubEmbeddingClient):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[9.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def knowledge_dependencies() -> Generator[tuple[sessionmaker[Session], uuid.UUID], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        user = User(
            username="knowledge-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="知识库招聘专员",
        )
        db.add(user)
        db.flush()
        job = Job(
            owner_id=user.id,
            title="平台工程师",
            department="研发中心",
            original_jd="负责平台工程建设。",
        )
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=user.id,
            confirmed_at=datetime.now(UTC),
        )
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="人才知识库测试",
            status="completed",
        )
        db.add(batch)
        db.flush()
        document = ResumeDocument(
            batch_id=batch.id,
            original_filename="synthetic.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            sha256="a" * 64,
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
            education=[
                {
                    "institution": "示例大学",
                    "degree": "本科",
                    "field_of_study": "计算机科学",
                    "evidence": [{"segment_key": "SEG-0001", "quote": "示例大学"}],
                }
            ],
            work_experiences=[
                {
                    "company": "示例科技",
                    "title": "后端工程师",
                    "summary": "负责微服务平台，联系电话 13812345678，邮箱 hr@example.com",
                    "evidence": [{"segment_key": "SEG-0002", "quote": "负责微服务平台"}],
                }
            ],
            projects=[],
            skills=[
                {
                    "name": "Python",
                    "level": "熟练",
                    "evidence": [{"segment_key": "SEG-0002", "quote": "Python"}],
                }
            ],
            certifications=[],
            languages=[],
        )
        db.add(profile)
        db.commit()
        profile_id = profile.id
    yield testing_session, profile_id
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_profile_chunks_are_semantic_and_exclude_contact_details(
    knowledge_dependencies: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    session_factory, profile_id = knowledge_dependencies
    with session_factory() as db:
        profile = db.get(CandidateProfile, profile_id)
        assert profile is not None
        chunks = build_profile_chunks(profile)

    assert [chunk.chunk_type for chunk in chunks] == [
        "summary",
        "education",
        "work_experience",
        "skill",
    ]
    combined = "\n".join(chunk.chunk_text for chunk in chunks)
    assert "13812345678" not in combined
    assert "hr@example.com" not in combined
    assert "[PHONE]" in combined
    assert "[EMAIL]" in combined
    assert chunks[2].source_segment_keys == ["SEG-0002"]


@pytest.mark.asyncio
async def test_profile_index_is_batched_idempotent_and_versioned(
    knowledge_dependencies: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    session_factory, profile_id = knowledge_dependencies
    client = StubEmbeddingClient()

    first = await index_candidate_profile(
        profile_id,
        session_factory=session_factory,
        embedding_client=client,
    )
    second = await index_candidate_profile(
        profile_id,
        session_factory=session_factory,
        embedding_client=client,
    )

    assert first["status"] == "completed"
    assert first["chunk_count"] == 4
    assert second == {
        "status": "completed",
        "candidate_profile_id": str(profile_id),
        "chunk_count": 4,
        "skipped": True,
    }
    assert [len(call) for call in client.calls] == [2, 2]
    with session_factory() as db:
        chunks = list(
            db.scalars(
                select(ResumeEmbeddingChunk).where(
                    ResumeEmbeddingChunk.candidate_profile_id == profile_id
                )
            )
        )
        assert len(chunks) == 4
        assert {chunk.status for chunk in chunks} == {"completed"}
        assert all(chunk.embedding is not None for chunk in chunks)
        assert all(chunk.attempt_count == 1 for chunk in chunks)

    next_version_client = StubEmbeddingClient(version="v2")
    versioned = await index_candidate_profile(
        profile_id,
        session_factory=session_factory,
        embedding_client=next_version_client,
    )
    assert versioned["status"] == "completed"
    with session_factory() as db:
        assert db.scalar(select(func.count(ResumeEmbeddingChunk.id))) == 8


@pytest.mark.asyncio
async def test_profile_index_failure_isolated_and_retryable(
    knowledge_dependencies: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    session_factory, profile_id = knowledge_dependencies
    failed_client = StubEmbeddingClient(error=EmbeddingUpstreamError("服务不可用"))

    failed = await index_candidate_profile(
        profile_id,
        task_id="failed-task",
        session_factory=session_factory,
        embedding_client=failed_client,
    )

    assert failed["status"] == "failed"
    assert failed["code"] == "embedding_upstream_failed"
    with session_factory() as db:
        chunks = list(db.scalars(select(ResumeEmbeddingChunk)))
        assert {chunk.status for chunk in chunks} == {"failed"}
        assert all(chunk.task_id == "failed-task" for chunk in chunks)

    retry_client = StubEmbeddingClient()
    retried = await index_candidate_profile(
        profile_id,
        task_id="retry-task",
        force=True,
        session_factory=session_factory,
        embedding_client=retry_client,
    )
    assert retried["status"] == "completed"
    with session_factory() as db:
        chunks = list(db.scalars(select(ResumeEmbeddingChunk)))
        assert {chunk.status for chunk in chunks} == {"completed"}
        assert all(chunk.task_id == "retry-task" for chunk in chunks)
        assert all(chunk.attempt_count == 2 for chunk in chunks)


@pytest.mark.asyncio
async def test_force_rebuild_supersedes_running_task_without_stale_writeback(
    knowledge_dependencies: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    session_factory, profile_id = knowledge_dependencies
    started = asyncio.Event()
    release = asyncio.Event()
    old_client = CoordinatedEmbeddingClient(started, release)
    old_task = asyncio.create_task(
        index_candidate_profile(
            profile_id,
            task_id="old-task",
            session_factory=session_factory,
            embedding_client=old_client,
        )
    )
    await started.wait()

    rebuilt = await index_candidate_profile(
        profile_id,
        task_id="new-task",
        force=True,
        session_factory=session_factory,
        embedding_client=MarkerEmbeddingClient(),
    )
    release.set()
    superseded = await old_task

    assert rebuilt["status"] == "completed"
    assert superseded == {
        "status": "superseded",
        "candidate_profile_id": str(profile_id),
        "chunk_count": 0,
    }
    with session_factory() as db:
        chunks = list(db.scalars(select(ResumeEmbeddingChunk)))
        assert {chunk.task_id for chunk in chunks} == {"new-task"}
        assert {chunk.status for chunk in chunks} == {"completed"}
        assert all(list(chunk.embedding or []) == [9.0, 0.0, 0.0] for chunk in chunks)
