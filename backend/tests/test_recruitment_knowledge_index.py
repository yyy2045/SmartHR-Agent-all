import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import RecruitmentKnowledgeChunk, Role, User, UserRole
from app.schemas.recruitment_knowledge import RecruitmentKnowledgeDocumentVersionCreateRequest
from app.services.recruitment_knowledge import (
    create_manual_knowledge_version,
    index_recruitment_knowledge_version,
)
from app.services.security import hash_password


class StubEmbeddingClient:
    model = "test-embedding"
    dimension = 3
    version = "v1"
    batch_size = 2

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1), 0.0, 0.0] for index, _ in enumerate(texts)]


@pytest.fixture
def recruitment_knowledge_index_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _user(db: Session) -> User:
    role = Role(key="administrator", display_name="企业管理员")
    user = User(
        username="admin",
        password_hash=hash_password("correct-password"),
        display_name="管理员",
        role_assignments=[UserRole(role=role)],
    )
    db.add(user)
    db.flush()
    return user


def _payload() -> RecruitmentKnowledgeDocumentVersionCreateRequest:
    return RecruitmentKnowledgeDocumentVersionCreateRequest(
        title="招聘制度",
        summary="基础制度",
        category="policy",
        tags=["制度"],
        visibility_scope="all_internal",
        change_note="初始化制度",
        raw_text="# 流程\n招聘专员负责筛选。\n\n# Offer\nOffer 发送前需要审批。",
        idempotency_key=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_index_recruitment_knowledge_version_embeds_chunks(
    recruitment_knowledge_index_session_factory: sessionmaker[Session],
) -> None:
    with recruitment_knowledge_index_session_factory() as db:
        user = _user(db)
        _document, version, chunks = create_manual_knowledge_version(db, _payload(), actor=user)
        db.commit()
        version_id = version.id
        assert {chunk.status for chunk in chunks} == {"pending"}

    result = await index_recruitment_knowledge_version(
        version_id,
        task_id="knowledge-task-1",
        session_factory=recruitment_knowledge_index_session_factory,
        embedding_client=StubEmbeddingClient(),
    )

    assert result["status"] == "completed"
    with recruitment_knowledge_index_session_factory() as db:
        stored_chunks = list(
            db.scalars(
                select(RecruitmentKnowledgeChunk).order_by(
                    RecruitmentKnowledgeChunk.chunk_index
                )
            )
        )
        assert stored_chunks
        assert {chunk.status for chunk in stored_chunks} == {"completed"}
        assert all(chunk.embedding is not None for chunk in stored_chunks)
        assert all(chunk.task_id == "knowledge-task-1" for chunk in stored_chunks)

