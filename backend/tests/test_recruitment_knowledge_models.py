import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    RecruitmentKnowledgeBase,
    RecruitmentKnowledgeChunk,
    RecruitmentKnowledgeDocument,
    RecruitmentKnowledgeDocumentVersion,
    RecruitmentKnowledgeRetrievalLog,
    Role,
    User,
    UserRole,
)
from app.services.security import hash_password


@pytest.fixture
def recruitment_knowledge_session_factory() -> Generator[sessionmaker[Session], None, None]:
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


def _base(user: User) -> RecruitmentKnowledgeBase:
    return RecruitmentKnowledgeBase(
        name="默认招聘知识库",
        description="公司招聘制度、面试标准和 Offer 规则",
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
    )


def _document(
    knowledge_base: RecruitmentKnowledgeBase,
    user: User,
) -> RecruitmentKnowledgeDocument:
    return RecruitmentKnowledgeDocument(
        knowledge_base=knowledge_base,
        title="后端工程师面试评分标准",
        summary="用于统一后端岗位面试评分口径",
        category="interview",
        tags=["后端", "面试", "评分"],
        visibility_scope="recruiter_manager",
        current_version_number=1,
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
    )


def _version(
    document: RecruitmentKnowledgeDocument,
    user: User,
    *,
    version_number: int = 1,
    status: str = "published",
    idempotency_key: uuid.UUID | None = None,
) -> RecruitmentKnowledgeDocumentVersion:
    return RecruitmentKnowledgeDocumentVersion(
        document=document,
        version_number=version_number,
        status=status,
        idempotency_key=idempotency_key or uuid.uuid4(),
        source_type="manual",
        content_hash="a" * 64,
        change_note="初始化后端面试评分标准",
        raw_text="候选人需要展示工程质量、接口设计、数据库建模和问题排查能力。",
        parser_name="plain_text",
        parser_version="v1",
        chunk_count=1,
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
        published_by_id=user.id if status == "published" else None,
        published_by_username=user.username if status == "published" else None,
        published_by_display_name=user.display_name if status == "published" else None,
        published_at=datetime.now(UTC) if status == "published" else None,
    )


def _chunk(
    knowledge_base: RecruitmentKnowledgeBase,
    document: RecruitmentKnowledgeDocument,
    version: RecruitmentKnowledgeDocumentVersion,
) -> RecruitmentKnowledgeChunk:
    return RecruitmentKnowledgeChunk(
        id=uuid.uuid4(),
        knowledge_base=knowledge_base,
        document=document,
        document_version=version,
        chunk_index=0,
        chunk_text="接口设计需要说明资源边界、错误码和幂等策略。",
        heading_path=["后端工程师面试评分标准", "接口设计"],
        source_locator="第 1 段",
        content_hash="b" * 64,
        embedding_model="test-embedding",
        embedding_dimension=3,
        embedding_version="v1",
        status="completed",
        embedded_at=datetime.now(UTC),
    )


def test_recruitment_knowledge_models_track_versions_chunks_and_retrieval_logs(
    recruitment_knowledge_session_factory: sessionmaker[Session],
) -> None:
    with recruitment_knowledge_session_factory() as db:
        user = _user(db)
        knowledge_base = _base(user)
        document = _document(knowledge_base, user)
        version = _version(document, user)
        chunk = _chunk(knowledge_base, document, version)
        retrieval_log = RecruitmentKnowledgeRetrievalLog(
            scenario="candidate_qa",
            query_hash="c" * 64,
            query_summary="候选人后端接口设计能力追问",
            invoked_by_id=user.id,
            resource_type="job_application",
            resource_id=uuid.uuid4(),
            embedding_model="test-embedding",
            embedding_dimension=3,
            embedding_version="v1",
            limit_count=5,
            returned_count=1,
            filtered_count=2,
            retrieved_chunk_ids=[str(chunk.id)],
            details={"visibility_scopes": ["recruiter_manager"]},
        )
        db.add_all([knowledge_base, document, version, chunk, retrieval_log])
        db.commit()

        stored = db.scalars(select(RecruitmentKnowledgeDocument)).one()
        assert stored.current_version is not None
        assert stored.current_version.raw_text.startswith("候选人需要展示")
        assert stored.chunks[0].heading_path == ["后端工程师面试评分标准", "接口设计"]

        stored_log = db.scalars(select(RecruitmentKnowledgeRetrievalLog)).one()
        assert stored_log.query_summary == "候选人后端接口设计能力追问"
        assert stored_log.retrieved_chunk_ids == [str(chunk.id)]


@pytest.mark.parametrize(
    "document_changes",
    [
        {"category": "resume"},
        {"visibility_scope": "public"},
        {"status": "deleted"},
        {"title": "   "},
        {"summary": "x" * 1001},
        {"current_version_number": 0},
        {"resource_version": 0},
    ],
)
def test_recruitment_knowledge_document_constraints_reject_invalid_values(
    recruitment_knowledge_session_factory: sessionmaker[Session],
    document_changes: dict[str, object],
) -> None:
    with recruitment_knowledge_session_factory() as db:
        user = _user(db)
        knowledge_base = _base(user)
        document = _document(knowledge_base, user)
        for key, value in document_changes.items():
            setattr(document, key, value)
        db.add_all([knowledge_base, document])
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "version_changes",
    [
        {"version_number": 0},
        {"status": "active"},
        {"source_type": "url"},
        {"change_note": ""},
        {"raw_text": "   "},
        {"chunk_count": -1},
        {"status": "draft", "published_at": datetime.now(UTC)},
    ],
)
def test_recruitment_knowledge_version_constraints_reject_invalid_values(
    recruitment_knowledge_session_factory: sessionmaker[Session],
    version_changes: dict[str, object],
) -> None:
    with recruitment_knowledge_session_factory() as db:
        user = _user(db)
        knowledge_base = _base(user)
        document = _document(knowledge_base, user)
        version = _version(document, user, status="draft")
        for key, value in version_changes.items():
            setattr(version, key, value)
        db.add_all([knowledge_base, document, version])
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "chunk_changes",
    [
        {"chunk_index": -1},
        {"chunk_text": ""},
        {"status": "done"},
        {"attempt_count": -1},
        {"embedding_dimension": 0},
    ],
)
def test_recruitment_knowledge_chunk_constraints_reject_invalid_values(
    recruitment_knowledge_session_factory: sessionmaker[Session],
    chunk_changes: dict[str, object],
) -> None:
    with recruitment_knowledge_session_factory() as db:
        user = _user(db)
        knowledge_base = _base(user)
        document = _document(knowledge_base, user)
        version = _version(document, user)
        chunk = _chunk(knowledge_base, document, version)
        for key, value in chunk_changes.items():
            setattr(chunk, key, value)
        db.add_all([knowledge_base, document, version, chunk])
        with pytest.raises(IntegrityError):
            db.commit()


def test_recruitment_knowledge_versions_are_immutable(
    recruitment_knowledge_session_factory: sessionmaker[Session],
) -> None:
    with recruitment_knowledge_session_factory() as db:
        user = _user(db)
        knowledge_base = _base(user)
        document = _document(knowledge_base, user)
        version = _version(document, user)
        db.add_all([knowledge_base, document, version])
        db.commit()

        version.status = "retired"
        db.commit()

        version.raw_text = "尝试覆盖历史版本正文"
        with pytest.raises(ValueError, match="历史版本正文不可修改"):
            db.commit()
        db.rollback()

        db.delete(version)
        with pytest.raises(ValueError, match="历史版本不可删除"):
            db.commit()


def test_recruitment_knowledge_version_and_chunk_uniqueness_are_scoped(
    recruitment_knowledge_session_factory: sessionmaker[Session],
) -> None:
    with recruitment_knowledge_session_factory() as db:
        user = _user(db)
        knowledge_base = _base(user)
        document = _document(knowledge_base, user)
        same_key = uuid.uuid4()
        first_version = _version(document, user, idempotency_key=same_key)
        second_version = _version(document, user, version_number=2, idempotency_key=same_key)
        db.add_all([knowledge_base, document, first_version, second_version])
        with pytest.raises(IntegrityError):
            db.commit()

    with recruitment_knowledge_session_factory() as db:
        user = _user(db)
        knowledge_base = _base(user)
        document = _document(knowledge_base, user)
        version = _version(document, user)
        first_chunk = _chunk(knowledge_base, document, version)
        second_chunk = _chunk(knowledge_base, document, version)
        db.add_all([knowledge_base, document, version, first_chunk, second_chunk])
        with pytest.raises(IntegrityError):
            db.commit()
