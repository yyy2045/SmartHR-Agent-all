import uuid
from collections.abc import Generator
from datetime import date, timedelta

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
    Job,
    RecruitmentRequest,
    RecruitmentRequestApproval,
    RecruitmentRequestVersion,
    Role,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@pytest.fixture
def request_dependencies() -> Generator[sessionmaker[Session], None, None]:
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

        def make_user(username: str, role_key: str) -> User:
            return User(
                username=username,
                password_hash=hash_password(f"{username}-password"),
                display_name=username,
                role_assignments=[UserRole(role=roles[role_key])],
            )

        db.add_all(
            [
                *roles.values(),
                make_user("administrator", "administrator"),
                make_user("manager", "hiring_manager"),
                make_user("other-manager", "hiring_manager"),
                make_user("recruiter", "recruiter"),
                make_user("other-recruiter", "recruiter"),
                make_user("approver", "approver"),
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

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    yield testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": f"{username}-password"},
    )
    assert response.status_code == 200


def request_payload(*, recruiter_id: str, idempotency_key: uuid.UUID | None = None):
    return {
        "idempotency_key": str(idempotency_key or uuid.uuid4()),
        "recruiter_id": recruiter_id,
        "job_title": "高级后端工程师",
        "headcount": 2,
        "reason": "核心平台扩容",
        "priority": "high",
        "target_start_date": (date.today() + timedelta(days=45)).isoformat(),
        "salary_min": 25000,
        "salary_max": 35000,
        "notes": "优先具备高并发系统经验",
    }


def version_payload(source_version_id: str, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_version_id": source_version_id,
        "job_title": "高级后端工程师",
        "headcount": 2,
        "reason": "核心平台扩容",
        "priority": "high",
        "target_start_date": (date.today() + timedelta(days=45)).isoformat(),
        "salary_min": 25000,
        "salary_max": 35000,
        "notes": "优先具备高并发系统经验",
    }
    payload.update(changes)
    return payload


async def create_approved_request(
    transport: httpx.ASGITransport,
) -> tuple[str, str, str]:
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        recruiter_id = next(
            item["id"]
            for item in (await manager.get("/users/options", params={"role": "recruiter"})).json()
            if item["username"] == "recruiter"
        )
        created = await manager.post(
            "/recruitment-requests",
            json=request_payload(recruiter_id=recruiter_id),
        )
        request_id = created.json()["id"]
        manager_id = created.json()["requester"]["id"]
        version_id = created.json()["current_version"]["id"]
        submitted = await manager.post(
            f"/recruitment-requests/{request_id}/submit",
            json={"version_id": version_id},
        )
        assert submitted.status_code == 200

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as approver:
        await login(approver, "approver")
        approved = await approver.post(
            f"/recruitment-requests/{request_id}/decision",
            json={"version_id": version_id, "decision": "approved", "comment": "同意"},
        )
        assert approved.status_code == 200

    return request_id, recruiter_id, manager_id


@pytest.mark.asyncio
async def test_recruitment_requests_require_authentication(request_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/recruitment-requests")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_is_idempotent_and_draft_scope_is_role_based(
    request_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        recruiters = await manager.get("/users/options", params={"role": "recruiter"})
        assert recruiters.status_code == 200
        recruiter_id = next(
            item["id"] for item in recruiters.json() if item["username"] == "recruiter"
        )
        key = uuid.uuid4()
        payload = request_payload(recruiter_id=recruiter_id, idempotency_key=key)
        created = await manager.post("/recruitment-requests", json=payload)
        repeated = await manager.post("/recruitment-requests", json=payload)
        conflicting = await manager.post(
            "/recruitment-requests",
            json={**payload, "job_title": "不同职位"},
        )
        manager_list = await manager.get("/recruitment-requests")

    assert created.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["id"] == created.json()["id"]
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"] == "幂等键已用于不同的招聘需求内容"
    assert [item["id"] for item in manager_list.json()] == [created.json()["id"]]
    assert created.json()["status"] == "draft"
    assert created.json()["current_version_number"] == 1
    assert created.json()["current_version"]["job_title"] == "高级后端工程师"

    request_id = created.json()["id"]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as recruiter:
        await login(recruiter, "recruiter")
        assert [item["id"] for item in (await recruiter.get("/recruitment-requests")).json()] == [
            request_id
        ]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await login(other, "other-manager")
        assert (await other.get("/recruitment-requests")).json() == []
        assert (await other.get(f"/recruitment-requests/{request_id}")).status_code == 404

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as approver:
        await login(approver, "approver")
        assert (await approver.get("/recruitment-requests")).json() == []
        assert (await approver.get(f"/recruitment-requests/{request_id}")).status_code == 404

    with request_dependencies() as db:
        created_audits = db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.action == "recruitment_request.created")
        )
        requests = db.scalar(select(func.count(RecruitmentRequest.id)))
    assert created_audits == 1
    assert requests == 1


@pytest.mark.asyncio
async def test_submit_and_approval_are_idempotent_and_lock_the_version(
    request_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        recruiter_id = next(
            item["id"]
            for item in (await manager.get("/users/options", params={"role": "recruiter"})).json()
            if item["username"] == "recruiter"
        )
        created = await manager.post(
            "/recruitment-requests",
            json=request_payload(recruiter_id=recruiter_id),
        )
        request_id = created.json()["id"]
        version_id = created.json()["current_version"]["id"]
        stale = await manager.post(
            f"/recruitment-requests/{request_id}/submit",
            json={"version_id": str(uuid.uuid4())},
        )
        submitted = await manager.post(
            f"/recruitment-requests/{request_id}/submit",
            json={"version_id": version_id},
        )
        repeated_submit = await manager.post(
            f"/recruitment-requests/{request_id}/submit",
            json={"version_id": version_id},
        )
        manager_decision = await manager.post(
            f"/recruitment-requests/{request_id}/decision",
            json={"version_id": version_id, "decision": "approved", "comment": ""},
        )

    assert stale.status_code == 409
    assert submitted.status_code == 200
    assert repeated_submit.status_code == 200
    assert submitted.json()["status"] == "pending_approval"
    assert manager_decision.status_code == 403

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as approver:
        await login(approver, "approver")
        assert [item["id"] for item in (await approver.get("/recruitment-requests")).json()] == [
            request_id
        ]
        approved = await approver.post(
            f"/recruitment-requests/{request_id}/decision",
            json={
                "version_id": version_id,
                "decision": "approved",
                "comment": "岗位必要，同意招聘",
            },
        )
        repeated = await approver.post(
            f"/recruitment-requests/{request_id}/decision",
            json={"version_id": version_id, "decision": "approved", "comment": "重试"},
        )
        reversed_decision = await approver.post(
            f"/recruitment-requests/{request_id}/decision",
            json={"version_id": version_id, "decision": "rejected", "comment": "改变结论"},
        )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert len(approved.json()["approvals"]) == 1
    assert approved.json()["approvals"][0]["comment"] == "岗位必要，同意招聘"
    assert repeated.status_code == 200
    assert len(repeated.json()["approvals"]) == 1
    assert reversed_decision.status_code == 409

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        locked = await manager.post(
            f"/recruitment-requests/{request_id}/versions",
            json=version_payload(version_id, job_title="不能修改"),
        )
    assert locked.status_code == 409

    with request_dependencies() as db:
        assert db.scalar(select(func.count(RecruitmentRequestApproval.id))) == 1
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "recruitment_request.submitted"
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "recruitment_request.approved"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_rejected_request_requires_a_new_version_before_resubmission(
    request_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        recruiter_id = next(
            item["id"]
            for item in (await manager.get("/users/options", params={"role": "recruiter"})).json()
            if item["username"] == "recruiter"
        )
        created = await manager.post(
            "/recruitment-requests",
            json=request_payload(recruiter_id=recruiter_id),
        )
        request_id = created.json()["id"]
        version_1_id = created.json()["current_version"]["id"]
        await manager.post(
            f"/recruitment-requests/{request_id}/submit",
            json={"version_id": version_1_id},
        )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as approver:
        await login(approver, "approver")
        missing_comment = await approver.post(
            f"/recruitment-requests/{request_id}/decision",
            json={"version_id": version_1_id, "decision": "rejected", "comment": ""},
        )
        rejected = await approver.post(
            f"/recruitment-requests/{request_id}/decision",
            json={
                "version_id": version_1_id,
                "decision": "rejected",
                "comment": "到岗时间过早，请调整",
            },
        )

    assert missing_comment.status_code == 422
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        blocked_resubmit = await manager.post(
            f"/recruitment-requests/{request_id}/submit",
            json={"version_id": version_1_id},
        )
        stale_edit = await manager.post(
            f"/recruitment-requests/{request_id}/versions",
            json=version_payload(
                str(uuid.uuid4()),
                target_start_date=(date.today() + timedelta(days=90)).isoformat(),
            ),
        )
        versioned = await manager.post(
            f"/recruitment-requests/{request_id}/versions",
            json=version_payload(
                version_1_id,
                target_start_date=(date.today() + timedelta(days=90)).isoformat(),
            ),
        )
        version_2_id = versioned.json()["current_version"]["id"]
        submitted = await manager.post(
            f"/recruitment-requests/{request_id}/submit",
            json={"version_id": version_2_id},
        )

    assert blocked_resubmit.status_code == 409
    assert stale_edit.status_code == 409
    assert versioned.status_code == 201
    assert versioned.json()["status"] == "draft"
    assert versioned.json()["current_version_number"] == 2
    assert len(versioned.json()["versions"]) == 2
    assert versioned.json()["versions"][1]["source_version_id"] == version_1_id
    assert submitted.status_code == 200

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as approver:
        await login(approver, "approver")
        approved = await approver.post(
            f"/recruitment-requests/{request_id}/decision",
            json={"version_id": version_2_id, "decision": "approved", "comment": "已调整"},
        )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert [item["decision"] for item in approved.json()["approvals"]] == [
        "rejected",
        "approved",
    ]
    with request_dependencies() as db:
        assert db.scalar(select(func.count(RecruitmentRequestVersion.id))) == 2
        assert db.scalar(select(func.count(RecruitmentRequestApproval.id))) == 2


@pytest.mark.asyncio
async def test_creation_validates_roles_and_permissions(request_dependencies: None) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        recruiter_options = (
            await manager.get("/users/options", params={"role": "recruiter"})
        ).json()
        recruiter_id = next(
            item["id"] for item in recruiter_options if item["username"] == "recruiter"
        )
        manager_options = await manager.get("/users/options", params={"role": "hiring_manager"})
        forbidden_other_role_options = manager_options
        wrong_requester = await manager.post(
            "/recruitment-requests",
            json={
                **request_payload(recruiter_id=recruiter_id),
                "requester_id": str(uuid.uuid4()),
            },
        )
        wrong_recruiter = await manager.post(
            "/recruitment-requests",
            json=request_payload(recruiter_id=str(uuid.uuid4())),
        )

    assert forbidden_other_role_options.status_code == 403
    assert wrong_requester.status_code == 403
    assert wrong_recruiter.status_code == 422

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as recruiter:
        await login(recruiter, "recruiter")
        forbidden = await recruiter.post(
            "/recruitment-requests",
            json=request_payload(recruiter_id=recruiter_id),
        )
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_approved_request_creates_exactly_one_linked_job(
    request_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    request_id, recruiter_id, manager_id = await create_approved_request(transport)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as recruiter:
        await login(recruiter, "recruiter")
        created = await recruiter.post(
            f"/recruitment-requests/{request_id}/job",
            json={"department": "平台研发", "original_jd": "负责核心平台建设。"},
        )
        repeated = await recruiter.post(
            f"/recruitment-requests/{request_id}/job",
            json={"department": "其他部门", "original_jd": "重复请求不应覆盖。"},
        )
        request_detail = await recruiter.get(f"/recruitment-requests/{request_id}")

    assert created.status_code == 201
    assert created.json()["title"] == "高级后端工程师"
    assert created.json()["department"] == "平台研发"
    assert created.json()["recruiter_id"] == recruiter_id
    assert created.json()["hiring_manager_id"] == manager_id
    assert created.json()["recruitment_request_id"] == request_id
    assert repeated.status_code == 201
    assert repeated.json()["id"] == created.json()["id"]
    assert repeated.json()["original_jd"] == "负责核心平台建设。"
    assert request_detail.json()["status"] == "converted"
    assert request_detail.json()["linked_job_id"] == created.json()["id"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        visible_job = await manager.get(f"/jobs/{created.json()['id']}")
    assert visible_job.status_code == 200

    with request_dependencies() as db:
        assert db.scalar(select(func.count(Job.id))) == 1
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "recruitment_request.converted"
                )
            )
            == 1
        )
        assert (
            db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "job.created")) == 1
        )


@pytest.mark.asyncio
async def test_only_assigned_recruiter_can_convert_an_approved_request(
    request_dependencies: sessionmaker[Session],
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        recruiter_id = next(
            item["id"]
            for item in (await manager.get("/users/options", params={"role": "recruiter"})).json()
            if item["username"] == "recruiter"
        )
        created = await manager.post(
            "/recruitment-requests",
            json=request_payload(recruiter_id=recruiter_id),
        )
        request_id = created.json()["id"]
        version_id = created.json()["current_version"]["id"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as recruiter:
        await login(recruiter, "recruiter")
        draft_blocked = await recruiter.post(
            f"/recruitment-requests/{request_id}/job",
            json={"department": "", "original_jd": "尚未批准。"},
        )
    assert draft_blocked.status_code == 409

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        await manager.post(
            f"/recruitment-requests/{request_id}/submit",
            json={"version_id": version_id},
        )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as approver:
        await login(approver, "approver")
        await approver.post(
            f"/recruitment-requests/{request_id}/decision",
            json={"version_id": version_id, "decision": "approved", "comment": "同意"},
        )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as manager:
        await login(manager, "manager")
        manager_blocked = await manager.post(
            f"/recruitment-requests/{request_id}/job",
            json={"department": "", "original_jd": "不能创建。"},
        )
    assert manager_blocked.status_code == 403

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await login(other, "other-recruiter")
        hidden = await other.post(
            f"/recruitment-requests/{request_id}/job",
            json={"department": "", "original_jd": "不能看到。"},
        )
    assert hidden.status_code == 404

    with request_dependencies() as db:
        assert db.scalar(select(func.count(Job.id))) == 0
