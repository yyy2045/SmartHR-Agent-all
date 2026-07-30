import uuid
from collections.abc import Generator
from dataclasses import dataclass

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    Candidate,
    Role,
    TalentPoolMembership,
    TalentPoolMembershipEvent,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass(frozen=True)
class TalentPoolDependencies:
    session_factory: sessionmaker[Session]
    first_candidate_id: uuid.UUID
    second_candidate_id: uuid.UUID
    merged_candidate_id: uuid.UUID


@pytest.fixture
def talent_pool_dependencies() -> Generator[TalentPoolDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        roles = {
            key: Role(key=key, display_name=label)
            for key, label in {
                "administrator": "企业管理员",
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
                "approver": "审批人",
            }.items()
        }
        users = [
            User(
                username=key,
                password_hash=hash_password(f"{key}-password"),
                display_name=label,
                role_assignments=[UserRole(role=roles[key])],
            )
            for key, label in {
                "administrator": "企业管理员",
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
                "approver": "审批人",
            }.items()
        ]
        first = Candidate(
            full_name="张三",
            phone="13800138001",
            email="zhangsan@example.com",
        )
        second = Candidate(
            full_name="李四",
            phone="13800138002",
            email="lisi@example.com",
        )
        merged = Candidate(
            full_name="张三旧档",
            status="merged",
            merged_into=first,
        )
        db.add_all([*roles.values(), *users, first, second, merged])
        db.commit()
        dependency = TalentPoolDependencies(
            session_factory=testing_session,
            first_candidate_id=first.id,
            second_candidate_id=second.id,
            merged_candidate_id=merged.id,
        )

    session_store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    yield dependency
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": f"{username}-password"},
    )
    assert response.status_code == 200


async def create_group(
    client: httpx.AsyncClient,
    *,
    name: str = "后端人才",
    key: uuid.UUID | None = None,
) -> dict[str, object]:
    response = await client.post(
        "/talent-pool/groups",
        json={
            "name": name,
            "description": "长期关注的工程人才",
            "idempotency_key": str(key or uuid.uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_talent_pool_role_permissions(
    talent_pool_dependencies: TalentPoolDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthenticated = await client.get("/talent-pool/groups")
        await login(client, "approver")
        approver_list = await client.get("/talent-pool/groups")
        await login(client, "hiring_manager")
        manager_list = await client.get("/talent-pool/groups")
        manager_create = await client.post(
            "/talent-pool/groups",
            json={
                "name": "无权创建",
                "idempotency_key": str(uuid.uuid4()),
            },
        )

    assert unauthenticated.status_code == 401
    assert approver_list.status_code == 403
    assert manager_list.status_code == 200
    assert manager_list.json()["items"] == []
    assert manager_create.status_code == 403


@pytest.mark.asyncio
async def test_group_create_update_archive_and_idempotency(
    talent_pool_dependencies: TalentPoolDependencies,
) -> None:
    create_key = uuid.uuid4()
    update_key = uuid.uuid4()
    archive_key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        created = await client.post(
            "/talent-pool/groups",
            json={
                "name": "Core Talent",
                "description": "核心人才",
                "idempotency_key": str(create_key),
            },
        )
        repeated = await client.post(
            "/talent-pool/groups",
            json={
                "name": "Core Talent",
                "description": "核心人才",
                "idempotency_key": str(create_key),
            },
        )
        reused_key = await client.post(
            "/talent-pool/groups",
            json={
                "name": "不同内容",
                "idempotency_key": str(create_key),
            },
        )
        duplicate_name = await client.post(
            "/talent-pool/groups",
            json={
                "name": "core talent",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        group_id = created.json()["id"]
        stale_update = await client.patch(
            f"/talent-pool/groups/{group_id}",
            json={
                "name": "核心人才",
                "expected_version": 2,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        updated = await client.patch(
            f"/talent-pool/groups/{group_id}",
            json={
                "name": "核心人才",
                "expected_version": 1,
                "idempotency_key": str(update_key),
            },
        )
        repeated_update = await client.patch(
            f"/talent-pool/groups/{group_id}",
            json={
                "name": "核心人才",
                "expected_version": 1,
                "idempotency_key": str(update_key),
            },
        )
        archived = await client.post(
            f"/talent-pool/groups/{group_id}/archive",
            json={
                "expected_version": 2,
                "idempotency_key": str(archive_key),
                "reason": "人才组策略调整",
            },
        )
        repeated_archive = await client.post(
            f"/talent-pool/groups/{group_id}/archive",
            json={
                "expected_version": 2,
                "idempotency_key": str(archive_key),
                "reason": "人才组策略调整",
            },
        )
        replacement = await client.post(
            "/talent-pool/groups",
            json={
                "name": "核心人才",
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        all_groups = await client.get("/talent-pool/groups", params={"status": "all"})
        first_page = await client.get(
            "/talent-pool/groups",
            params={"status": "all", "limit": 1, "offset": 0},
        )
        second_page = await client.get(
            "/talent-pool/groups",
            params={"status": "all", "limit": 1, "offset": 1},
        )

    assert created.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["id"] == created.json()["id"]
    assert reused_key.status_code == 409
    assert duplicate_name.status_code == 409
    assert stale_update.status_code == 409
    assert updated.status_code == 200 and updated.json()["version"] == 2
    assert repeated_update.status_code == 200
    assert repeated_update.json()["version"] == 2
    assert archived.status_code == 200 and archived.json()["version"] == 3
    assert archived.json()["is_archived"] is True
    assert repeated_archive.status_code == 200
    assert repeated_archive.json()["version"] == 3
    assert replacement.status_code == 201
    assert all_groups.status_code == 200
    assert all_groups.json()["total"] == 2
    assert first_page.json()["total"] == 2
    assert second_page.json()["total"] == 2
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]


@pytest.mark.asyncio
async def test_bulk_membership_lifecycle_is_versioned_and_idempotent(
    talent_pool_dependencies: TalentPoolDependencies,
) -> None:
    dependency = talent_pool_dependencies
    add_key = uuid.uuid4()
    remove_key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "administrator")
        group = await create_group(client)
        group_id = group["id"]
        add_payload = {
            "members": [
                {"candidate_id": str(dependency.first_candidate_id)},
                {"candidate_id": str(dependency.second_candidate_id)},
            ],
            "reason": "具备后端工程经验",
            "expected_group_version": 1,
            "idempotency_key": str(add_key),
        }
        added = await client.post(
            f"/talent-pool/groups/{group_id}/memberships",
            json=add_payload,
        )
        repeated_add = await client.post(
            f"/talent-pool/groups/{group_id}/memberships",
            json=add_payload,
        )
        stale_add = await client.post(
            f"/talent-pool/groups/{group_id}/memberships",
            json={
                "members": [{"candidate_id": str(dependency.first_candidate_id)}],
                "reason": "旧版本写入",
                "expected_group_version": 1,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        active_list = await client.get("/talent-pool/memberships")
        removed = await client.post(
            f"/talent-pool/groups/{group_id}/memberships/remove",
            json={
                "candidate_ids": [str(dependency.second_candidate_id)],
                "reason": "候选人暂不考虑新机会",
                "expected_group_version": 2,
                "idempotency_key": str(remove_key),
            },
        )
        repeated_remove = await client.post(
            f"/talent-pool/groups/{group_id}/memberships/remove",
            json={
                "candidate_ids": [str(dependency.second_candidate_id)],
                "reason": "候选人暂不考虑新机会",
                "expected_group_version": 2,
                "idempotency_key": str(remove_key),
            },
        )
        removed_list = await client.get(
            "/talent-pool/memberships", params={"status": "removed"}
        )
        await login(client, "hiring_manager")
        manager_list = await client.get("/talent-pool/memberships")

    assert added.status_code == 200, added.text
    assert added.json()["group_version"] == 2
    assert {item["status"] for item in added.json()["items"]} == {"added"}
    assert repeated_add.status_code == 200
    assert repeated_add.json() == added.json()
    assert stale_add.status_code == 409
    assert active_list.status_code == 200 and active_list.json()["total"] == 2
    assert removed.status_code == 200
    assert removed.json()["group_version"] == 3
    assert removed.json()["items"][0]["status"] == "removed"
    assert repeated_remove.status_code == 200
    assert repeated_remove.json() == removed.json()
    assert removed_list.status_code == 200 and removed_list.json()["total"] == 1
    assert manager_list.status_code == 200 and manager_list.json()["total"] == 1
    assert manager_list.json()["items"][0]["phone"] is None
    assert manager_list.json()["items"][0]["email"] is None

    with dependency.session_factory() as db:
        assert db.scalar(select(func.count(TalentPoolMembership.id))) == 2
        assert db.scalar(select(func.count(TalentPoolMembershipEvent.id))) == 3
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "talent_pool.members_added"
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "talent_pool.members_removed"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_merged_candidate_resolves_to_active_master_and_archived_group_rejects_add(
    talent_pool_dependencies: TalentPoolDependencies,
) -> None:
    dependency = talent_pool_dependencies
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        group = await create_group(client, name="合并候选人组")
        group_id = group["id"]
        added = await client.post(
            f"/talent-pool/groups/{group_id}/memberships",
            json={
                "members": [{"candidate_id": str(dependency.merged_candidate_id)}],
                "reason": "历史档案自动解析到主档",
                "expected_group_version": 1,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        missing_candidate = await client.post(
            f"/talent-pool/groups/{group_id}/memberships",
            json={
                "members": [{"candidate_id": str(uuid.uuid4())}],
                "reason": "不存在的候选人",
                "expected_group_version": 2,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        missing_group = await client.get(
            "/talent-pool/memberships",
            params={"group_id": str(uuid.uuid4())},
        )
        duplicate_after_resolution = await client.post(
            f"/talent-pool/groups/{group_id}/memberships",
            json={
                "members": [
                    {"candidate_id": str(dependency.merged_candidate_id)},
                    {"candidate_id": str(dependency.first_candidate_id)},
                ],
                "reason": "解析后重复",
                "expected_group_version": 2,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        archived = await client.post(
            f"/talent-pool/groups/{group_id}/archive",
            json={
                "expected_version": 2,
                "idempotency_key": str(uuid.uuid4()),
                "reason": "结束维护",
            },
        )
        add_after_archive = await client.post(
            f"/talent-pool/groups/{group_id}/memberships",
            json={
                "members": [{"candidate_id": str(dependency.second_candidate_id)}],
                "reason": "归档后不应新增",
                "expected_group_version": 3,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        too_many = await client.post(
            f"/talent-pool/groups/{group_id}/memberships/remove",
            json={
                "candidate_ids": [str(uuid.uuid4()) for _ in range(101)],
                "reason": "超过批量上限",
                "expected_group_version": 3,
                "idempotency_key": str(uuid.uuid4()),
            },
        )

    assert added.status_code == 200
    assert added.json()["items"][0]["requested_candidate_id"] == str(
        dependency.merged_candidate_id
    )
    assert added.json()["items"][0]["candidate_id"] == str(
        dependency.first_candidate_id
    )
    assert missing_candidate.status_code == 404
    assert missing_group.status_code == 404
    assert duplicate_after_resolution.status_code == 422
    assert archived.status_code == 200
    assert add_after_archive.status_code == 409
    assert too_many.status_code == 422
