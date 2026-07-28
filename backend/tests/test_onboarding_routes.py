import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

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
    Job,
    JobApplication,
    Offer,
    OfferPortalLink,
    OfferResponse,
    OfferVersion,
    Onboarding,
    Role,
    User,
    UserRole,
)
from app.redis_client import get_offer_portal_store, get_session_store
from app.services.offer_portal import (
    OfferPortalVerificationStore,
    hash_portal_token,
    phone_verification_digest,
)
from app.services.onboarding import create_onboarding_for_acceptance
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class OnboardingDependencies:
    session_factory: sessionmaker[Session]
    onboarding_id: uuid.UUID
    offer_id: uuid.UUID
    token: str
    portal_store: OfferPortalVerificationStore


@pytest.fixture
def onboarding_dependencies() -> Generator[OnboardingDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    token = "onboarding-access-token-00000000000000000000"

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
            username="onboarding-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="入职招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        other_recruiter = User(
            username="other-onboarding-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="其他招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        manager = User(
            username="onboarding-manager",
            password_hash=hash_password("correct-password"),
            display_name="入职用人经理",
            role_assignments=[UserRole(role=roles["hiring_manager"])],
        )
        approver = User(
            username="onboarding-approver",
            password_hash=hash_password("correct-password"),
            display_name="入职审批人",
            role_assignments=[UserRole(role=roles["approver"])],
        )
        administrator = User(
            username="onboarding-administrator",
            password_hash=hash_password("correct-password"),
            display_name="入职管理员",
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
        version = OfferVersion(
            version_number=1,
            idempotency_key=uuid.uuid4(),
            currency="CNY",
            monthly_salary=Decimal("30000.00"),
            annual_salary_months=Decimal("14.00"),
            probation_months=3,
            probation_monthly_salary=Decimal("27000.00"),
            bonus_description="年度奖金另计",
            expected_start_date=date.today() + timedelta(days=30),
            valid_until=date.today() + timedelta(days=7),
            notes="候选人可见备注",
            created_by_id=recruiter.id,
            created_by_username=recruiter.username,
            created_by_display_name=recruiter.display_name,
        )
        offer = Offer(
            application=application,
            status="accepted",
            created_by_id=recruiter.id,
            versions=[version],
        )
        db.add_all([job, candidate, application, offer])
        db.flush()
        link_id = uuid.uuid4()
        link = OfferPortalLink(
            id=link_id,
            offer=offer,
            version=version,
            idempotency_key=uuid.uuid4(),
            token_hash=hash_portal_token(token),
            verification_phone_digest=phone_verification_digest(
                "1234",
                link_id=link_id,
                secret_key="development-only-change-me",
            ),
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by_id=recruiter.id,
            created_by_username=recruiter.username,
            created_by_display_name=recruiter.display_name,
        )
        response = OfferResponse(
            offer=offer,
            version=version,
            portal_link=link,
            idempotency_key=uuid.uuid4(),
            decision="accepted",
            verification_completed_at=datetime.now(UTC),
        )
        db.add_all([link, response])
        db.flush()
        onboarding = create_onboarding_for_acceptance(
            db,
            offer=offer,
            response=response,
            portal_link=link,
        )
        db.commit()
        onboarding_id = onboarding.id
        offer_id = offer.id

    redis_client = fakeredis.FakeRedis(decode_responses=True)
    session_store = SessionStore(redis_client=redis_client, ttl_seconds=3_600)
    portal_store = OfferPortalVerificationStore(
        redis_client=redis_client,
        verification_ttl_seconds=900,
        max_attempts=5,
        lock_seconds=900,
    )
    dependencies = OnboardingDependencies(
        session_factory=testing_session,
        onboarding_id=onboarding_id,
        offer_id=offer_id,
        token=token,
        portal_store=portal_store,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_offer_portal_store] = lambda: portal_store
    yield dependencies
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def _login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


async def _verify(client: httpx.AsyncClient, token: str) -> str:
    response = await client.post(
        "/portal/offers/verify",
        json={"token": token, "phone_last_four": "1234"},
    )
    assert response.status_code == 200
    return response.json()["verification_token"]


@pytest.mark.anyio
async def test_onboarding_list_and_detail_enforce_role_scope(
    onboarding_dependencies: OnboardingDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "onboarding-recruiter")
        recruiter_list = await client.get("/onboardings")
        assert recruiter_list.status_code == 200
        assert recruiter_list.json()["total"] == 1
        assert recruiter_list.json()["items"][0]["candidate_phone"] == "13800001234"

        await _login(client, "onboarding-manager")
        manager_detail = await client.get(
            f"/onboardings/{onboarding_dependencies.onboarding_id}"
        )
        manager_write = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/date-decision",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "version": 1,
                "decision": "propose",
                "proposed_date": str(date.today() + timedelta(days=31)),
                "note": "调整日期",
            },
        )
        assert manager_detail.status_code == 200
        assert manager_detail.json()["candidate_phone"] is None
        assert manager_write.status_code == 403

        await _login(client, "other-onboarding-recruiter")
        other_list = await client.get("/onboardings")
        other_detail = await client.get(
            f"/onboardings/{onboarding_dependencies.onboarding_id}"
        )
        assert other_list.json()["total"] == 0
        assert other_detail.status_code == 404

        await _login(client, "onboarding-approver")
        approver_list = await client.get("/onboardings")
        approver_detail = await client.get(
            f"/onboardings/{onboarding_dependencies.onboarding_id}"
        )
        assert approver_list.json()["total"] == 0
        assert approver_detail.status_code == 404


@pytest.mark.anyio
async def test_candidate_proposes_recruiter_accepts_and_admin_corrects_onboarding(
    onboarding_dependencies: OnboardingDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    proposed_date = date.today() + timedelta(days=35)
    proposal_key = uuid.uuid4()
    accept_key = uuid.uuid4()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        verification_token = await _verify(client, onboarding_dependencies.token)
        proposal_payload = {
            "token": onboarding_dependencies.token,
            "verification_token": verification_token,
            "idempotency_key": str(proposal_key),
            "version": 1,
            "start_date": str(proposed_date),
            "note": "需要完成工作交接",
        }
        proposed = await client.post(
            "/portal/offers/onboarding/propose-date",
            json=proposal_payload,
        )
        replay = await client.post(
            "/portal/offers/onboarding/propose-date",
            json=proposal_payload,
        )
        conflicting_replay = await client.post(
            "/portal/offers/onboarding/propose-date",
            json={**proposal_payload, "start_date": str(proposed_date + timedelta(days=1))},
        )
        assert proposed.status_code == replay.status_code == 200
        assert proposed.json() == replay.json()
        assert proposed.json()["onboarding"]["status"] == "candidate_proposed_date"
        assert proposed.json()["onboarding"]["version"] == 2
        assert "events" not in proposed.json()["onboarding"]
        assert "abandonment_note" not in proposed.json()["onboarding"]
        assert conflicting_replay.status_code == 409

        await _login(client, "onboarding-recruiter")
        accept_payload = {
            "idempotency_key": str(accept_key),
            "version": 2,
            "decision": "accept",
            "note": "同意候选人日期",
        }
        accepted = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/date-decision",
            json=accept_payload,
        )
        accepted_replay = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/date-decision",
            json=accept_payload,
        )
        assert accepted.status_code == accepted_replay.status_code == 200
        assert accepted.json() == accepted_replay.json()
        assert accepted.json()["status"] == "pending_start"
        assert accepted.json()["confirmed_start_date"] == str(proposed_date)

        onboarded = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/onboard",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "version": 3,
                "actual_start_date": str(date.today()),
                "note": "已完成报到",
            },
        )
        recruiter_correction = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/corrections",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "version": 4,
                "reason": "测试无权更正",
            },
        )
        assert onboarded.status_code == 200
        assert onboarded.json()["status"] == "onboarded"
        assert recruiter_correction.status_code == 403

        await _login(client, "onboarding-administrator")
        corrected = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/corrections",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "version": 4,
                "reason": "招聘专员误点已入职",
            },
        )
        assert corrected.status_code == 200
        assert corrected.json()["status"] == "pending_start"
        assert corrected.json()["actual_start_date"] is None
        assert corrected.json()["version"] == 5

    with onboarding_dependencies.session_factory() as db:
        onboarding = db.get(Onboarding, onboarding_dependencies.onboarding_id)
        assert onboarding.offer.status == "accepted"
        assert [event.action for event in onboarding.events] == [
            "created",
            "candidate_proposed_date",
            "recruiter_accepted_date",
            "onboarded",
            "onboarded_corrected",
        ]
        proposal_audits = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "onboarding.candidate_proposed_date"
                )
            )
        )
        accept_audits = list(
            db.scalars(
                select(AuditLog).where(AuditLog.action == "onboarding.date_accept")
            )
        )
        assert len(proposal_audits) == len(accept_audits) == 1


@pytest.mark.anyio
async def test_recruiter_proposes_candidate_confirms_then_abandons(
    onboarding_dependencies: OnboardingDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    recruiter_date = date.today() + timedelta(days=40)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "onboarding-recruiter")
        proposed = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/date-decision",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "version": 1,
                "decision": "propose",
                "proposed_date": str(recruiter_date),
                "note": "项目入职窗口调整",
            },
        )
        assert proposed.status_code == 200
        assert proposed.json()["action_owner"] == "candidate"

        verification_token = await _verify(client, onboarding_dependencies.token)
        confirmed = await client.post(
            "/portal/offers/onboarding/confirm-date",
            json={
                "token": onboarding_dependencies.token,
                "verification_token": verification_token,
                "idempotency_key": str(uuid.uuid4()),
                "version": 2,
                "start_date": str(recruiter_date),
            },
        )
        abandoned = await client.post(
            "/portal/offers/onboarding/abandon",
            json={
                "token": onboarding_dependencies.token,
                "verification_token": verification_token,
                "idempotency_key": str(uuid.uuid4()),
                "version": 3,
                "reason_code": "personal",
                "note": "个人计划发生变化",
            },
        )
        repeated_action = await client.post(
            "/portal/offers/onboarding/confirm-date",
            json={
                "token": onboarding_dependencies.token,
                "verification_token": verification_token,
                "idempotency_key": str(uuid.uuid4()),
                "version": 4,
                "start_date": str(recruiter_date),
            },
        )

    assert confirmed.status_code == 200
    assert confirmed.json()["onboarding"]["status"] == "pending_start"
    assert abandoned.status_code == 200
    assert abandoned.json()["onboarding"]["status"] == "abandoned"
    assert abandoned.json()["onboarding"]["abandonment_source"] == "candidate_withdrew"
    assert repeated_action.status_code == 409
    with onboarding_dependencies.session_factory() as db:
        offer = db.get(Offer, onboarding_dependencies.offer_id)
        assert offer.status == "accepted"
        assert offer.candidate_response.decision == "accepted"


@pytest.mark.anyio
async def test_onboarding_portal_rejects_invalid_session_and_past_date(
    onboarding_dependencies: OnboardingDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        invalid_session = await client.post(
            "/portal/offers/onboarding/propose-date",
            json={
                "token": onboarding_dependencies.token,
                "verification_token": "x" * 43,
                "idempotency_key": str(uuid.uuid4()),
                "version": 1,
                "start_date": str(date.today() + timedelta(days=35)),
                "note": "测试",
            },
        )
        verification_token = await _verify(client, onboarding_dependencies.token)
        past_date = await client.post(
            "/portal/offers/onboarding/propose-date",
            json={
                "token": onboarding_dependencies.token,
                "verification_token": verification_token,
                "idempotency_key": str(uuid.uuid4()),
                "version": 1,
                "start_date": str(date.today() - timedelta(days=1)),
                "note": "测试过去日期",
            },
        )
    assert invalid_session.status_code == 401
    assert past_date.status_code == 422


@pytest.mark.anyio
async def test_recruiter_regenerates_onboarding_access_link_without_new_response(
    onboarding_dependencies: OnboardingDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    create_key = uuid.uuid4()
    revocation_key = uuid.uuid4()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "onboarding-recruiter")
        regenerated = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/portal-links/regenerate",
            json={
                "idempotency_key": str(create_key),
                "revocation_idempotency_key": str(revocation_key),
                "reason": "候选人手机号修正后重新生成",
            },
        )
        replay = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/portal-links/regenerate",
            json={
                "idempotency_key": str(create_key),
                "revocation_idempotency_key": str(revocation_key),
                "reason": "候选人手机号修正后重新生成",
            },
        )
        conflicting_replay = await client.post(
            f"/onboardings/{onboarding_dependencies.onboarding_id}/portal-links/regenerate",
            json={
                "idempotency_key": str(create_key),
                "revocation_idempotency_key": str(uuid.uuid4()),
                "reason": "不同的重新生成参数",
            },
        )
        new_token = regenerated.json()["portal_token"]
        old_link = await client.post(
            "/portal/offers/status",
            json={"token": onboarding_dependencies.token},
        )
        new_verification = await _verify(client, new_token)
        new_detail = await client.post(
            "/portal/offers/detail",
            json={"token": new_token, "verification_token": new_verification},
        )

    assert regenerated.status_code == replay.status_code == 201
    assert conflicting_replay.status_code == 409
    assert replay.json()["portal_token"] is None
    assert old_link.status_code == 410
    assert new_detail.status_code == 200
    assert new_detail.json()["response"]["decision"] == "accepted"
    assert new_detail.json()["onboarding"]["status"] == "pending_confirmation"
    with onboarding_dependencies.session_factory() as db:
        assert len(list(db.scalars(select(OfferResponse)))) == 1
        assert len(list(db.scalars(select(Onboarding)))) == 1
        audits = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "onboarding.portal_link_regenerated"
                )
            )
        )
        assert len(audits) == 1
