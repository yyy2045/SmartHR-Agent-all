import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import date, timedelta

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    Candidate,
    InterviewReport,
    InterviewReportVersion,
    Job,
    JobApplication,
    Offer,
    Role,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class OfferDependencies:
    session_factory: sessionmaker[Session]
    job_id: uuid.UUID
    application_id: uuid.UUID


@pytest.fixture
def offer_dependencies() -> Generator[OfferDependencies, None, None]:
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
                "administrator": "管理员",
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
                "approver": "审批人",
            }.items()
        }
        recruiter = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        other_recruiter = User(
            username="other-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="其他招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        manager = User(
            username="manager",
            password_hash=hash_password("correct-password"),
            display_name="用人经理",
            role_assignments=[
                UserRole(role=roles["hiring_manager"]),
                UserRole(role=roles["approver"]),
            ],
        )
        approver = User(
            username="approver",
            password_hash=hash_password("correct-password"),
            display_name="独立审批人",
            role_assignments=[UserRole(role=roles["approver"])],
        )
        administrator = User(
            username="administrator",
            password_hash=hash_password("correct-password"),
            display_name="管理员",
            role_assignments=[UserRole(role=roles["administrator"])],
        )
        db.add_all(
            [
                *roles.values(),
                recruiter,
                other_recruiter,
                manager,
                approver,
                administrator,
            ]
        )
        db.flush()
        job = Job(
            owner_id=recruiter.id,
            hiring_manager_id=manager.id,
            title="高级后端工程师",
            department="研发",
            original_jd="负责核心服务开发",
        )
        candidate = Candidate(full_name="候选人A", phone="13800001234")
        application = JobApplication(candidate=candidate, job=job)
        db.add_all([job, candidate, application])
        db.flush()
        report = InterviewReport(
            application=application,
            status="confirmed",
            current_version_number=1,
            created_by_id=recruiter.id,
            confirmed_by_id=recruiter.id,
            versions=[
                InterviewReportVersion(
                    version_number=1,
                    idempotency_key=uuid.uuid4(),
                    generation_mode="manual",
                    conclusion="hire",
                    executive_summary="建议录用",
                    strengths=["技术能力符合要求"],
                    concerns=[],
                    follow_up_actions=[],
                    evidence_snapshot={},
                    missing_rounds=[],
                    created_by_id=recruiter.id,
                    created_by_username=recruiter.username,
                    created_by_display_name=recruiter.display_name,
                )
            ],
        )
        db.add(report)
        db.commit()
        dependencies = OfferDependencies(
            session_factory=testing_session,
            job_id=job.id,
            application_id=application.id,
        )

    store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3_600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    def override_store() -> SessionStore:
        return store

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_store
    yield dependencies
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


def create_path(dependencies: OfferDependencies) -> str:
    return (
        f"/jobs/{dependencies.job_id}/applications/"
        f"{dependencies.application_id}/offer"
    )


def offer_payload(key: uuid.UUID, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "idempotency_key": str(key),
        "monthly_salary": "30000.00",
        "annual_salary_months": "14.00",
        "probation_months": 3,
        "probation_monthly_salary": "27000.00",
        "bonus_description": "年度奖金另计",
        "expected_start_date": str(date.today() + timedelta(days=30)),
        "valid_until": str(date.today() + timedelta(days=7)),
        "notes": "仅授权人员可见",
    }
    payload.update(changes)
    return payload


@pytest.mark.anyio
async def test_offer_full_approval_flow_is_idempotent_and_audited(
    offer_dependencies: OfferDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    create_key = uuid.uuid4()
    submit_key = uuid.uuid4()
    manager_key = uuid.uuid4()
    approval_key = uuid.uuid4()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        created = await client.post(
            create_path(offer_dependencies), json=offer_payload(create_key)
        )
        replayed_create = await client.post(
            create_path(offer_dependencies), json=offer_payload(create_key)
        )
        assert created.status_code == replayed_create.status_code == 201
        assert created.json()["id"] == replayed_create.json()["id"]
        offer_id = created.json()["id"]
        version_id = created.json()["current_version"]["id"]
        conflicting_create = await client.post(
            create_path(offer_dependencies),
            json=offer_payload(create_key, monthly_salary="31000.00"),
        )
        assert conflicting_create.status_code == 409

        submitted = await client.post(
            f"/offers/{offer_id}/submit",
            json={"idempotency_key": str(submit_key), "version_id": version_id},
        )
        replayed_submit = await client.post(
            f"/offers/{offer_id}/submit",
            json={"idempotency_key": str(submit_key), "version_id": version_id},
        )
        assert submitted.status_code == replayed_submit.status_code == 200
        assert submitted.json()["status"] == "pending_manager_confirmation"
        conflicting_submit = await client.post(
            f"/offers/{offer_id}/submit",
            json={"idempotency_key": str(uuid.uuid4()), "version_id": version_id},
        )
        assert conflicting_submit.status_code == 409

        await login(client, "approver")
        assert (await client.get("/offers")).json() == []

        await login(client, "manager")
        manager = await client.post(
            f"/offers/{offer_id}/manager-decision",
            json={
                "idempotency_key": str(manager_key),
                "version_id": version_id,
                "decision": "confirmed",
                "comment": "确认录用",
            },
        )
        replayed_manager = await client.post(
            f"/offers/{offer_id}/manager-decision",
            json={
                "idempotency_key": str(manager_key),
                "version_id": version_id,
                "decision": "confirmed",
                "comment": "确认录用",
            },
        )
        assert manager.status_code == replayed_manager.status_code == 200
        assert manager.json()["status"] == "pending_approval"
        conflicting_manager = await client.post(
            f"/offers/{offer_id}/manager-decision",
            json={
                "idempotency_key": str(manager_key),
                "version_id": version_id,
                "decision": "confirmed",
                "comment": "不同意见",
            },
        )
        assert conflicting_manager.status_code == 409

        separation = await client.post(
            f"/offers/{offer_id}/approval-decision",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "version_id": version_id,
                "decision": "approved",
                "comment": "同意",
            },
        )
        assert separation.status_code == 409
        assert "必须是不同账号" in separation.text

        await login(client, "approver")
        visible = await client.get("/offers")
        assert visible.status_code == 200
        assert [item["id"] for item in visible.json()] == [offer_id]
        approved = await client.post(
            f"/offers/{offer_id}/approval-decision",
            json={
                "idempotency_key": str(approval_key),
                "version_id": version_id,
                "decision": "approved",
                "comment": "审批通过",
            },
        )
        replayed_approval = await client.post(
            f"/offers/{offer_id}/approval-decision",
            json={
                "idempotency_key": str(approval_key),
                "version_id": version_id,
                "decision": "approved",
                "comment": "审批通过",
            },
        )
        assert approved.status_code == replayed_approval.status_code == 200
        assert approved.json()["status"] == "approved"
        assert approved.json()["current_version"]["approval"]["decision"] == "approved"

    with offer_dependencies.session_factory() as db:
        actions = set(db.scalars(select(AuditLog.action)).all())
        assert {
            "offer.created",
            "offer.submitted",
            "offer.manager_confirmed",
            "offer.approved",
            "offer.sensitive_data_viewed",
        }.issubset(actions)


@pytest.mark.anyio
async def test_offer_rejection_requires_new_version_and_preserves_history(
    offer_dependencies: OfferDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        created = await client.post(
            create_path(offer_dependencies), json=offer_payload(uuid.uuid4())
        )
        offer_id = created.json()["id"]
        first_version_id = created.json()["current_version"]["id"]
        await client.post(
            f"/offers/{offer_id}/submit",
            json={"idempotency_key": str(uuid.uuid4()), "version_id": first_version_id},
        )

        await login(client, "manager")
        rejected_key = uuid.uuid4()
        rejected_payload = {
            "idempotency_key": str(rejected_key),
            "version_id": first_version_id,
            "decision": "rejected",
            "comment": "请调整月薪",
        }
        rejected = await client.post(
            f"/offers/{offer_id}/manager-decision", json=rejected_payload
        )
        replay = await client.post(
            f"/offers/{offer_id}/manager-decision", json=rejected_payload
        )
        assert rejected.status_code == replay.status_code == 200
        assert rejected.json()["status"] == "rejected"

        await login(client, "recruiter")
        revision_key = uuid.uuid4()
        revised_payload = offer_payload(
            revision_key,
            source_version_id=first_version_id,
            monthly_salary="32000.00",
        )
        revised = await client.post(
            f"/offers/{offer_id}/versions", json=revised_payload
        )
        assert revised.status_code == 200
        body = revised.json()
        assert body["status"] == "draft"
        assert body["current_version_number"] == 2
        assert len(body["versions"]) == 2
        assert body["versions"][0]["manager_confirmation"]["decision"] == "rejected"
        assert body["current_version"]["source_version_id"] == first_version_id


@pytest.mark.anyio
async def test_offer_permissions_eligibility_and_date_validation(
    offer_dependencies: OfferDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "other-recruiter")
        hidden = await client.post(
            create_path(offer_dependencies), json=offer_payload(uuid.uuid4())
        )
        assert hidden.status_code == 404

        await login(client, "manager")
        readonly = await client.post(
            create_path(offer_dependencies), json=offer_payload(uuid.uuid4())
        )
        assert readonly.status_code == 403

        await login(client, "recruiter")
        expired = await client.post(
            create_path(offer_dependencies),
            json=offer_payload(
                uuid.uuid4(),
                valid_until=str(date.today()),
                expected_start_date=str(date.today() + timedelta(days=2)),
            ),
        )
        assert expired.status_code == 201
        offer_id = expired.json()["id"]
        version_id = expired.json()["current_version"]["id"]
        invalid_submit = await client.post(
            f"/offers/{offer_id}/submit",
            json={"idempotency_key": str(uuid.uuid4()), "version_id": version_id},
        )
        assert invalid_submit.status_code == 422
        assert "必须晚于提交当天" in invalid_submit.text

    with offer_dependencies.session_factory() as db:
        application = db.get(JobApplication, offer_dependencies.application_id)
        assert application is not None
        application.offer = None
        report = application.interview_report
        assert report is not None
        report.current_version.conclusion = "next_round"
        db.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        ineligible = await client.post(
            create_path(offer_dependencies), json=offer_payload(uuid.uuid4())
        )
        assert ineligible.status_code == 422
        assert "结论为录用" in ineligible.text


@pytest.mark.anyio
async def test_offer_approval_rechecks_expiration_date(
    offer_dependencies: OfferDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        created = await client.post(
            create_path(offer_dependencies), json=offer_payload(uuid.uuid4())
        )
        offer_id = created.json()["id"]
        version_id = created.json()["current_version"]["id"]
        await client.post(
            f"/offers/{offer_id}/submit",
            json={"idempotency_key": str(uuid.uuid4()), "version_id": version_id},
        )
        await login(client, "manager")
        confirmed = await client.post(
            f"/offers/{offer_id}/manager-decision",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "version_id": version_id,
                "decision": "confirmed",
                "comment": "确认录用",
            },
        )
        assert confirmed.status_code == 200

    with offer_dependencies.session_factory() as db:
        offer = db.get(Offer, uuid.UUID(offer_id))
        assert offer is not None
        offer.current_version.valid_until = date.today()
        db.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "approver")
        expired = await client.post(
            f"/offers/{offer_id}/approval-decision",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "version_id": version_id,
                "decision": "approved",
                "comment": "同意",
            },
        )
        assert expired.status_code == 422
        assert "必须晚于提交当天" in expired.text
