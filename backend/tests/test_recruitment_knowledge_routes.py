import uuid
from collections.abc import Generator
from dataclasses import dataclass

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    RecruitmentKnowledgeChunk,
    RecruitmentKnowledgeDocumentVersion,
    Role,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class RecruitmentKnowledgeRouteDependencies:
    session_factory: sessionmaker[Session]


@pytest.fixture
def recruitment_knowledge_route_dependencies(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[RecruitmentKnowledgeRouteDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        admin_role = Role(key="administrator", display_name="企业管理员")
        recruiter_role = Role(key="recruiter", display_name="招聘专员")
        manager_role = Role(key="hiring_manager", display_name="用人经理")
        administrator = User(
            username="administrator",
            password_hash=hash_password("correct-password"),
            display_name="管理员",
            role_assignments=[UserRole(role=admin_role)],
        )
        recruiter = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
            role_assignments=[UserRole(role=recruiter_role)],
        )
        manager = User(
            username="manager",
            password_hash=hash_password("correct-password"),
            display_name="用人经理",
            role_assignments=[UserRole(role=manager_role)],
        )
        db.add_all([admin_role, recruiter_role, manager_role, administrator, recruiter, manager])
        db.commit()

    store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3_600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    monkeypatch.setattr(settings, "file_storage_root", tmp_path)
    monkeypatch.setattr(settings, "embedding_enabled", False)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: store
    yield RecruitmentKnowledgeRouteDependencies(testing_session)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def _login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


def _manual_payload(idempotency_key: uuid.UUID | None = None) -> dict[str, object]:
    return {
        "title": "后端工程师面试评分标准",
        "summary": "统一后端岗位面试评价口径",
        "category": "interview",
        "tags": ["后端", "面试"],
        "visibility_scope": "recruiter_manager",
        "change_note": "初始化评分标准",
        "raw_text": "# 接口设计\n候选人需要说明资源边界、错误码和幂等策略。",
        "idempotency_key": str(idempotency_key or uuid.uuid4()),
    }


@pytest.mark.asyncio
async def test_recruiter_creates_manual_knowledge_document_idempotently(
    recruitment_knowledge_route_dependencies: RecruitmentKnowledgeRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        key = uuid.uuid4()
        created = await client.post(
            "/recruitment-knowledge/documents/manual",
            json=_manual_payload(key),
        )
        assert created.status_code == 201
        body = created.json()
        assert body["document"]["title"] == "后端工程师面试评分标准"
        assert body["document"]["current_version_number"] == 1
        assert body["version"]["status"] == "published"
        assert body["chunk_count"] == 1
        assert body["embedding_enabled"] is False
        assert body["index_task_id"] is None

        repeated = await client.post(
            "/recruitment-knowledge/documents/manual",
            json=_manual_payload(key),
        )
        assert repeated.status_code == 201
        assert repeated.json()["version"]["id"] == body["version"]["id"]

    with recruitment_knowledge_route_dependencies.session_factory() as db:
        versions = list(db.scalars(select(RecruitmentKnowledgeDocumentVersion)))
        chunks = list(db.scalars(select(RecruitmentKnowledgeChunk)))
        assert len(versions) == 1
        assert len(chunks) == 1


@pytest.mark.asyncio
async def test_hiring_manager_cannot_maintain_recruitment_knowledge(
    recruitment_knowledge_route_dependencies: RecruitmentKnowledgeRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "manager")
        response = await client.post(
            "/recruitment-knowledge/documents/manual",
            json=_manual_payload(),
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_retrieve_returns_conflict_when_embedding_is_disabled(
    recruitment_knowledge_route_dependencies: RecruitmentKnowledgeRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        response = await client.post(
            "/recruitment-knowledge/retrieve",
            json={
                "scenario": "candidate_qa",
                "query": "招聘流程是什么？",
                "limit": 3,
            },
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_upload_text_knowledge_document_records_source_metadata(
    recruitment_knowledge_route_dependencies: RecruitmentKnowledgeRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "administrator")
        response = await client.post(
            "/recruitment-knowledge/documents/upload",
            data={
                "idempotency_key": str(uuid.uuid4()),
                "title": "Offer 沟通话术",
                "category": "communication",
                "change_note": "上传沟通模板",
                "visibility_scope": "recruiter_only",
                "tags": ["Offer", "沟通"],
            },
            files={
                "file": (
                    "offer.md",
                    b"# Offer\nPlease confirm the expected onboarding date.",
                    "text/markdown",
                )
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["version"]["source_type"] == "upload"
        assert body["version"]["source_filename"] == "offer.md"
        assert body["document"]["category"] == "communication"

    with recruitment_knowledge_route_dependencies.session_factory() as db:
        version = db.scalars(select(RecruitmentKnowledgeDocumentVersion)).one()
        assert version.storage_key is not None
        assert version.parser_name == "markdown"


async def _create_document(
    client: httpx.AsyncClient,
    *,
    title: str,
    visibility_scope: str,
) -> dict[str, object]:
    payload = _manual_payload()
    payload["title"] = title
    payload["visibility_scope"] = visibility_scope
    response = await client.post("/recruitment-knowledge/documents/manual", json=payload)
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_list_knowledge_documents_respects_visibility_scopes(
    recruitment_knowledge_route_dependencies: RecruitmentKnowledgeRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        await _create_document(client, title="管理员专享制度", visibility_scope="admin_only")
        await _create_document(client, title="后端面试标准", visibility_scope="recruiter_manager")

        body = (await client.get("/recruitment-knowledge/documents")).json()
        assert body["total"] >= 2
        titles = {item["title"] for item in body["items"]}
        assert {"管理员专享制度", "后端面试标准"} <= titles
        listed = next(item for item in body["items"] if item["title"] == "后端面试标准")
        assert listed["version_count"] == 1
        assert listed["current_source_type"] == "manual"
        assert listed["chunk_count"] == 1

        # 非维护角色只能看到对其可见的知识
        await _login(client, "manager")
        body = (await client.get("/recruitment-knowledge/documents")).json()
        assert all(item["title"] == "后端面试标准" for item in body["items"])


@pytest.mark.asyncio
async def test_get_knowledge_document_detail_returns_chunks_and_raw_text(
    recruitment_knowledge_route_dependencies: RecruitmentKnowledgeRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        created = await _create_document(
            client, title="后端面试评分标准", visibility_scope="recruiter_manager"
        )
        document_id = created["document"]["id"]

        detail = await client.get(f"/recruitment-knowledge/documents/{document_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["title"] == "后端面试评分标准"
        assert body["current_version_number"] == 1
        assert "候选人需要说明资源边界" in body["raw_text"]
        assert len(body["versions"]) == 1
        assert len(body["current_chunks"]) == 1
        first = body["current_chunks"][0]
        assert first["chunk_index"] == 0
        assert "候选人需要说明资源边界" in first["chunk_text"]
        assert first["heading_path"] == ["接口设计"]
        assert first["status"] == "pending"


@pytest.mark.asyncio
async def test_get_knowledge_document_detail_hides_invisible_document_from_manager(
    recruitment_knowledge_route_dependencies: RecruitmentKnowledgeRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "recruiter")
        created = await _create_document(
            client, title="管理员专享制度", visibility_scope="admin_only"
        )
        document_id = created["document"]["id"]

        await _login(client, "manager")
        detail = await client.get(f"/recruitment-knowledge/documents/{document_id}")
        assert detail.status_code == 403
