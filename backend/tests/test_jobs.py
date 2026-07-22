from collections.abc import Generator

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@pytest.fixture
def job_dependencies() -> Generator[None, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        db.add(
            User(
                username="recruiter",
                password_hash=hash_password("correct-password"),
                display_name="测试招聘专员",
            )
        )
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

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_session_store
    yield
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
async def test_jobs_require_authentication(job_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/jobs")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_update_list_and_archive_job(job_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        create_response = await client.post(
            "/jobs",
            json={
                "title": "高级后端工程师",
                "department": "研发中心",
                "original_jd": "负责核心服务设计与开发。",
            },
        )
        assert create_response.status_code == 201
        job_id = create_response.json()["id"]

        update_response = await client.patch(
            f"/jobs/{job_id}",
            json={"title": "资深后端工程师"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["title"] == "资深后端工程师"

        list_response = await client.get("/jobs")
        assert list_response.status_code == 200
        assert [item["id"] for item in list_response.json()] == [job_id]

        detail_response = await client.get(f"/jobs/{job_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["criteria_versions"] == []

        archive_response = await client.post(f"/jobs/{job_id}/archive")
        assert archive_response.status_code == 200
        assert archive_response.json()["status"] == "archived"

        assert (await client.get("/jobs")).json() == []
        archived_jobs = await client.get("/jobs", params={"include_archived": True})
        assert len(archived_jobs.json()) == 1

        blocked_update = await client.patch(f"/jobs/{job_id}", json={"department": "平台部"})
        assert blocked_update.status_code == 409


@pytest.mark.asyncio
async def test_confirmed_criteria_are_immutable_and_versioned(job_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        job_response = await client.post(
            "/jobs",
            json={"title": "数据分析师", "department": "数据部", "original_jd": "分析业务数据。"},
        )
        job_id = job_response.json()["id"]

        draft_response = await client.post(f"/jobs/{job_id}/criteria/versions", json={})
        assert draft_response.status_code == 201
        version_id = draft_response.json()["id"]
        assert draft_response.json()["version_number"] == 1

        draft_payload = {
            "pass_threshold": 65,
            "hard_requirements": [
                {
                    "requirement_type": "min_experience_years",
                    "title": "相关经验",
                    "description": "数据分析相关经验",
                    "expected_value": "3年",
                    "auto_reject": True,
                    "sort_order": 0,
                }
            ],
            "scoring_dimensions": [
                {
                    "name": "数据分析能力",
                    "description": "统计分析与业务洞察",
                    "weight_percent": 60,
                    "sort_order": 0,
                },
                {
                    "name": "沟通能力",
                    "description": "跨团队表达与协作",
                    "weight_percent": 30,
                    "sort_order": 1,
                },
            ],
        }
        update_response = await client.put(
            f"/jobs/{job_id}/criteria/versions/{version_id}",
            json=draft_payload,
        )
        assert update_response.status_code == 200

        invalid_confirm = await client.post(
            f"/jobs/{job_id}/criteria/versions/{version_id}/confirm"
        )
        assert invalid_confirm.status_code == 422
        assert "当前为 90%" in invalid_confirm.json()["detail"]

        draft_payload["scoring_dimensions"][1]["weight_percent"] = 40
        await client.put(
            f"/jobs/{job_id}/criteria/versions/{version_id}",
            json=draft_payload,
        )
        confirm_response = await client.post(
            f"/jobs/{job_id}/criteria/versions/{version_id}/confirm"
        )
        assert confirm_response.status_code == 200
        assert confirm_response.json()["status"] == "confirmed"

        immutable_response = await client.put(
            f"/jobs/{job_id}/criteria/versions/{version_id}",
            json=draft_payload,
        )
        assert immutable_response.status_code == 409

        cloned_response = await client.post(
            f"/jobs/{job_id}/criteria/versions",
            json={"source_version_id": version_id},
        )
        assert cloned_response.status_code == 201
        cloned = cloned_response.json()
        assert cloned["version_number"] == 2
        assert cloned["status"] == "draft"
        assert cloned["source_version_id"] == version_id
        assert cloned["scoring_dimensions"][0]["weight_percent"] == 60

        versions_response = await client.get(f"/jobs/{job_id}/criteria/versions")
        versions = versions_response.json()
        assert [item["version_number"] for item in versions] == [2, 1]
        assert versions[1]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_auto_reject_is_limited_to_objective_requirements(job_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        job_response = await client.post(
            "/jobs",
            json={"title": "产品经理", "department": "产品部", "original_jd": "负责产品规划。"},
        )
        job_id = job_response.json()["id"]
        draft = await client.post(f"/jobs/{job_id}/criteria/versions", json={})
        version_id = draft.json()["id"]

        response = await client.put(
            f"/jobs/{job_id}/criteria/versions/{version_id}",
            json={
                "pass_threshold": 60,
                "hard_requirements": [
                    {
                        "requirement_type": "other",
                        "title": "行业经验",
                        "expected_value": "互联网行业",
                        "auto_reject": True,
                    }
                ],
                "scoring_dimensions": [],
            },
        )

    assert response.status_code == 422
    assert "只有客观硬性条件允许自动淘汰" in response.text
