import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    RecruitmentKnowledgeChunk,
    RecruitmentKnowledgeRetrievalLog,
    Role,
    User,
    UserRole,
)
from app.schemas.recruitment_knowledge import (
    RecruitmentKnowledgeDocumentVersionCreateRequest,
    RecruitmentKnowledgeRetrievalRequest,
)
from app.services.recruitment_knowledge import (
    create_manual_knowledge_version,
    index_recruitment_knowledge_version,
    retrieve_recruitment_knowledge,
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


def _user(db: Session, *, role_key: str = "administrator", username: str = "admin") -> User:
    labels = {
        "administrator": "企业管理员",
        "recruiter": "招聘专员",
        "hiring_manager": "用人经理",
    }
    role = Role(key=role_key, display_name=labels[role_key])
    user = User(
        username=username,
        password_hash=hash_password("correct-password"),
        display_name=labels[role_key],
        role_assignments=[UserRole(role=role)],
    )
    db.add(user)
    db.flush()
    return user


def _payload(
    *,
    title: str = "招聘制度",
    visibility_scope: str = "all_internal",
) -> RecruitmentKnowledgeDocumentVersionCreateRequest:
    return RecruitmentKnowledgeDocumentVersionCreateRequest(
        title=title,
        summary="基础制度",
        category="policy",
        tags=["制度"],
        visibility_scope=visibility_scope,
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


@pytest.mark.asyncio
async def test_retrieve_recruitment_knowledge_filters_by_visibility_and_logs(
    recruitment_knowledge_index_session_factory: sessionmaker[Session],
) -> None:
    with recruitment_knowledge_index_session_factory() as db:
        admin = _user(db)
        manager = _user(db, role_key="hiring_manager", username="manager")
        _doc1, _version1, chunks1 = create_manual_knowledge_version(
            db,
            _payload(title="通用招聘制度", visibility_scope="all_internal"),
            actor=admin,
        )
        _doc2, _version2, chunks2 = create_manual_knowledge_version(
            db,
            _payload(title="招聘专员私有话术", visibility_scope="recruiter_only"),
            actor=admin,
        )
        for chunk in [*chunks1, *chunks2]:
            chunk.status = "completed"
            chunk.embedding_model = "test-embedding"
            chunk.embedding_dimension = 3
            chunk.embedding_version = "v1"
            chunk.embedding = [1.0, 0.0, 0.0]
        db.commit()
        manager_id = manager.id

    with recruitment_knowledge_index_session_factory() as db:
        manager = db.get(User, manager_id)
        assert manager is not None
        response = await retrieve_recruitment_knowledge(
            db,
            RecruitmentKnowledgeRetrievalRequest(
                scenario="candidate_qa",
                query="招聘专员负责什么？",
                limit=5,
            ),
            actor=manager,
            embedding_client=StubEmbeddingClient(),
        )

        assert response.returned_count == 1
        assert response.filtered_count == 1
        assert response.citations[0].document_title == "通用招聘制度"

        log = db.scalars(select(RecruitmentKnowledgeRetrievalLog)).one()
        assert log.returned_count == 1
        assert log.filtered_count == 1
        assert log.query_summary == "招聘专员负责什么?"
