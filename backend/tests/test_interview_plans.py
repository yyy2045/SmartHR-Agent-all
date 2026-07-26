from collections.abc import Generator

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditLog, User
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@pytest.fixture
def interview_dependencies() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        db.add_all(
            [
                User(
                    username="recruiter",
                    password_hash=hash_password("correct-password"),
                    display_name="测试招聘专员",
                ),
                User(
                    username="other-recruiter",
                    password_hash=hash_password("correct-password"),
                    display_name="其他招聘专员",
                ),
            ]
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
    yield testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str = "recruiter") -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


async def create_job(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/jobs",
        json={
            "title": "高级后端工程师",
            "department": "研发中心",
            "original_jd": "负责核心服务设计与开发。",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def score_anchors(prefix: str) -> list[dict[str, object]]:
    return [
        {"score_value": score, "description": f"{prefix}{score}分表现"}
        for score in range(1, 6)
    ]


def valid_plan_payload() -> dict[str, object]:
    return {
        "rounds": [
            {
                "name": "技术一面",
                "round_type": "technical",
                "duration_minutes": 60,
                "pass_threshold": 70,
                "focus": "验证后端基础、系统设计和工程质量。",
                "sort_order": 0,
                "questions": [
                    {
                        "question_text": "请说明最近一个高并发系统的设计取舍。",
                        "evaluation_guide": "关注容量估算、数据一致性和故障降级。",
                        "sort_order": 0,
                    }
                ],
                "scoring_dimensions": [
                    {
                        "name": "系统设计",
                        "description": "评估架构拆分、扩展性和可靠性。",
                        "weight_percent": 60,
                        "sort_order": 0,
                        "anchors": score_anchors("系统设计"),
                    },
                    {
                        "name": "工程质量",
                        "description": "评估测试、可维护性和交付意识。",
                        "weight_percent": 40,
                        "sort_order": 1,
                        "anchors": score_anchors("工程质量"),
                    },
                ],
            }
        ]
    }


@pytest.mark.asyncio
async def test_interview_plans_require_authentication(interview_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/jobs/00000000-0000-0000-0000-000000000001/interview-plans/versions"
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_interview_plan_is_versioned_confirmed_and_audited(
    interview_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        job_id = await create_job(client)
        created = await client.post(f"/jobs/{job_id}/interview-plans/versions", json={})
        assert created.status_code == 201
        version_id = created.json()["id"]
        assert created.json()["version_number"] == 1
        assert created.json()["rounds"] == []

        invalid_payload = valid_plan_payload()
        invalid_payload["rounds"][0]["scoring_dimensions"][1]["weight_percent"] = 30
        saved_invalid = await client.put(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}",
            json=invalid_payload,
        )
        assert saved_invalid.status_code == 200
        invalid_confirm = await client.post(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}/confirm"
        )
        assert invalid_confirm.status_code == 422
        assert "当前为 90%" in invalid_confirm.json()["detail"]

        payload = valid_plan_payload()
        saved = await client.put(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}",
            json=payload,
        )
        assert saved.status_code == 200
        assert saved.json()["rounds"][0]["pass_threshold"] == 70
        assert len(saved.json()["rounds"][0]["scoring_dimensions"][0]["anchors"]) == 5

        confirmed = await client.post(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}/confirm"
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"
        repeated_confirm = await client.post(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}/confirm"
        )
        assert repeated_confirm.status_code == 200

        immutable = await client.put(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}",
            json=payload,
        )
        assert immutable.status_code == 409

        cloned = await client.post(
            f"/jobs/{job_id}/interview-plans/versions",
            json={"source_version_id": version_id},
        )
        assert cloned.status_code == 201
        cloned_body = cloned.json()
        assert cloned_body["version_number"] == 2
        assert cloned_body["status"] == "draft"
        assert cloned_body["source_version_id"] == version_id
        assert cloned_body["rounds"][0]["id"] != confirmed.json()["rounds"][0]["id"]
        assert cloned_body["rounds"][0]["questions"][0]["question_text"].startswith("请说明")

        versions = await client.get(f"/jobs/{job_id}/interview-plans/versions")
        assert [item["version_number"] for item in versions.json()] == [2, 1]

    with interview_dependencies() as db:
        confirmation_logs = list(
            db.scalars(
                select(AuditLog).where(AuditLog.action == "interview_plan.confirmed")
            )
        )
        actions = list(
            db.scalars(
                select(AuditLog.action)
                .where(AuditLog.target_type == "interview_plan_version")
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        )

    assert len(confirmation_logs) == 1
    assert confirmation_logs[0].details == {
        "version_number": 1,
        "round_count": 1,
        "question_count": 1,
        "dimension_count": 2,
    }
    assert actions.count("interview_plan.created") == 2
    assert actions.count("interview_plan.updated") == 2
    assert actions.count("interview_plan.confirmed") == 1


@pytest.mark.asyncio
async def test_interview_plan_requires_complete_score_anchors(
    interview_dependencies: None,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        job_id = await create_job(client)
        created = await client.post(f"/jobs/{job_id}/interview-plans/versions", json={})
        version_id = created.json()["id"]
        payload = valid_plan_payload()
        payload["rounds"][0]["scoring_dimensions"][0]["anchors"] = score_anchors("系统设计")[:4]
        await client.put(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}",
            json=payload,
        )

        response = await client.post(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}/confirm"
        )

    assert response.status_code == 422
    assert "必须完整配置 1～5 分评分锚点" in response.json()["detail"]


@pytest.mark.asyncio
async def test_interview_plan_allows_incomplete_draft_but_rejects_confirmation(
    interview_dependencies: None,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        job_id = await create_job(client)
        created = await client.post(f"/jobs/{job_id}/interview-plans/versions", json={})
        version_id = created.json()["id"]
        incomplete_payload = {
            "rounds": [
                {
                    "name": "",
                    "round_type": "technical",
                    "duration_minutes": 60,
                    "pass_threshold": 60,
                    "focus": "",
                    "sort_order": 0,
                    "questions": [
                        {"question_text": "", "evaluation_guide": "", "sort_order": 0}
                    ],
                    "scoring_dimensions": [
                        {
                            "name": "",
                            "description": "",
                            "weight_percent": 0,
                            "sort_order": 0,
                            "anchors": [],
                        }
                    ],
                }
            ]
        }

        saved = await client.put(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}",
            json=incomplete_payload,
        )
        confirmed = await client.post(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}/confirm"
        )

    assert saved.status_code == 200
    assert saved.json()["rounds"][0]["name"] == ""
    assert confirmed.status_code == 422
    assert confirmed.json()["detail"] == "面试轮次名称不能为空"


@pytest.mark.asyncio
async def test_interview_plan_rejects_duplicate_rounds_and_cross_owner_access(
    interview_dependencies: None,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        job_id = await create_job(client)
        created = await client.post(f"/jobs/{job_id}/interview-plans/versions", json={})
        version_id = created.json()["id"]
        duplicate_payload = valid_plan_payload()
        duplicate_payload["rounds"].append({**duplicate_payload["rounds"][0], "sort_order": 1})
        duplicate = await client.put(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}",
            json=duplicate_payload,
        )
        assert duplicate.status_code == 422
        assert "面试轮次名称不能重复" in duplicate.text

        await client.post("/auth/logout")
        await login(client, "other-recruiter")
        hidden_list = await client.get(f"/jobs/{job_id}/interview-plans/versions")
        hidden_detail = await client.get(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}"
        )

    assert hidden_list.status_code == 404
    assert hidden_detail.status_code == 404


@pytest.mark.asyncio
async def test_archived_job_blocks_interview_plan_changes(interview_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        job_id = await create_job(client)
        created = await client.post(f"/jobs/{job_id}/interview-plans/versions", json={})
        version_id = created.json()["id"]
        await client.post(f"/jobs/{job_id}/archive")

        blocked_create = await client.post(
            f"/jobs/{job_id}/interview-plans/versions",
            json={},
        )
        blocked_update = await client.put(
            f"/jobs/{job_id}/interview-plans/versions/{version_id}",
            json=valid_plan_payload(),
        )
        readable = await client.get(f"/jobs/{job_id}/interview-plans/versions")

    assert blocked_create.status_code == 409
    assert blocked_update.status_code == 409
    assert readable.status_code == 200
