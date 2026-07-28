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

import app.api.routes.offer_portal as offer_portal_routes
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    Candidate,
    CandidateProcess,
    Job,
    JobApplication,
    Offer,
    OfferApproval,
    OfferManagerConfirmation,
    OfferPortalLink,
    OfferResponse,
    OfferVersion,
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
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class PortalDependencies:
    session_factory: sessionmaker[Session]
    offer_id: uuid.UUID
    store: OfferPortalVerificationStore


@pytest.fixture
def portal_dependencies() -> Generator[PortalDependencies, None, None]:
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
                "recruiter": "招聘专员",
                "hiring_manager": "用人经理",
            }.items()
        }
        recruiter = User(
            username="portal-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="门户招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        other_recruiter = User(
            username="other-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="其他招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        manager = User(
            username="portal-manager",
            password_hash=hash_password("correct-password"),
            display_name="用人经理",
            role_assignments=[UserRole(role=roles["hiring_manager"])],
        )
        db.add_all([*roles.values(), recruiter, other_recruiter, manager])
        db.flush()
        job = Job(
            owner_id=recruiter.id,
            hiring_manager_id=manager.id,
            title="高级后端工程师",
            department="研发",
            original_jd="负责核心系统开发",
        )
        candidate = Candidate(full_name="候选人A", phone="13800001234")
        application = JobApplication(candidate=candidate, job=job)
        process = CandidateProcess(application=application, current_stage="completed")
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
            manager_confirmation=OfferManagerConfirmation(
                idempotency_key=uuid.uuid4(),
                confirmer_id=manager.id,
                confirmer_username=manager.username,
                confirmer_display_name=manager.display_name,
                decision="confirmed",
                comment="确认录用",
            ),
            approval=OfferApproval(
                idempotency_key=uuid.uuid4(),
                approver_username="approver",
                approver_display_name="审批人",
                decision="approved",
                comment="审批通过",
            ),
        )
        offer = Offer(
            application=application,
            status="approved",
            created_by_id=recruiter.id,
            versions=[version],
        )
        db.add_all([job, candidate, application, process, offer])
        db.commit()
        offer_id = offer.id

    redis_client = fakeredis.FakeRedis(decode_responses=True)
    session_store = SessionStore(redis_client=redis_client, ttl_seconds=3_600)
    portal_store = OfferPortalVerificationStore(
        redis_client=redis_client,
        verification_ttl_seconds=900,
        max_attempts=5,
        lock_seconds=900,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_offer_portal_store] = lambda: portal_store
    yield PortalDependencies(testing_session, offer_id, portal_store)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def _login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


async def _create_link(
    client: httpx.AsyncClient,
    dependencies: PortalDependencies,
    key: uuid.UUID | None = None,
) -> httpx.Response:
    return await client.post(
        f"/offers/{dependencies.offer_id}/portal-links",
        json={"idempotency_key": str(key or uuid.uuid4())},
    )


async def _verify_link(client: httpx.AsyncClient, token: str) -> str:
    response = await client.post(
        "/portal/offers/verify",
        json={"token": token, "phone_last_four": "1234"},
    )
    assert response.status_code == 200
    return response.json()["verification_token"]


@pytest.mark.anyio
async def test_recruiter_creates_hashed_link_and_replay_hides_raw_token(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    key = uuid.uuid4()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "portal-recruiter")
        created = await _create_link(client, portal_dependencies, key)
        replay = await _create_link(client, portal_dependencies, key)
        links = await client.get(
            f"/offers/{portal_dependencies.offer_id}/portal-links"
        )

    assert created.status_code == replay.status_code == 201
    token = created.json()["portal_token"]
    assert token and len(token) >= 32
    assert replay.json()["portal_token"] is None
    assert links.status_code == 200
    assert "portal_token" not in links.json()[0]

    with portal_dependencies.session_factory() as db:
        offer = db.get(Offer, portal_dependencies.offer_id)
        link = db.scalar(select(OfferPortalLink).where(OfferPortalLink.offer_id == offer.id))
        assert offer.status == "pending_response"
        assert offer.application.process.current_stage == "offer_pending_response"
        assert link.token_hash == hash_portal_token(token)
        assert token != link.token_hash
        assert len(link.verification_phone_digest) == 64
        assert "1234" not in link.verification_phone_digest
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "offer.portal_link_created")
        )
        assert token not in str(audit.details)


@pytest.mark.anyio
async def test_public_verification_needs_no_login_and_exposes_only_candidate_fields(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as internal:
        await _login(internal, "portal-recruiter")
        created = await _create_link(internal, portal_dependencies)
        token = created.json()["portal_token"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        status_response = await portal.post("/portal/offers/status", json={"token": token})
        verified = await portal.post(
            "/portal/offers/verify",
            json={"token": token, "phone_last_four": "1234"},
        )
        verification_token = verified.json()["verification_token"]
        detail = await portal.post(
            "/portal/offers/detail",
            json={"token": token, "verification_token": verification_token},
        )
        wrong_session = await portal.post(
            "/portal/offers/detail",
            json={"token": token, "verification_token": "x" * 43},
        )

    assert status_response.status_code == 200
    assert status_response.json() == {"status": "verification_required"}
    assert verified.status_code == detail.status_code == 200
    body = detail.json()
    assert body["candidate_name"] == "候选人A"
    assert body["job_title"] == "高级后端工程师"
    assert body["monthly_salary"] == "30000.00"
    assert body["notes"] == "候选人可见备注"
    assert not {
        "candidate_id",
        "offer_id",
        "version_id",
        "approval",
        "ai_score",
        "phone",
    }.intersection(body)
    assert wrong_session.status_code == 401
    redis_keys = [str(item) for item in portal_dependencies.store.redis_client.keys("*")]
    assert token not in redis_keys
    assert verification_token not in redis_keys


@pytest.mark.anyio
async def test_wrong_phone_locks_link_after_five_attempts(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "portal-recruiter")
        created = await _create_link(client, portal_dependencies)
        token = created.json()["portal_token"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        for _ in range(4):
            failed = await portal.post(
                "/portal/offers/verify",
                json={"token": token, "phone_last_four": "0000"},
            )
            assert failed.status_code == 401
        locked = await portal.post(
            "/portal/offers/verify",
            json={"token": token, "phone_last_four": "0000"},
        )
        correct_during_lock = await portal.post(
            "/portal/offers/verify",
            json={"token": token, "phone_last_four": "1234"},
        )

    assert locked.status_code == correct_during_lock.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0


@pytest.mark.anyio
async def test_phone_verification_uses_link_creation_snapshot(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as internal:
        await _login(internal, "portal-recruiter")
        created = await _create_link(internal, portal_dependencies)
        token = created.json()["portal_token"]

    with portal_dependencies.session_factory() as db:
        offer = db.get(Offer, portal_dependencies.offer_id)
        assert offer is not None
        offer.application.candidate.phone = "13999995678"
        db.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        current_phone = await portal.post(
            "/portal/offers/verify",
            json={"token": token, "phone_last_four": "5678"},
        )
        original_phone = await portal.post(
            "/portal/offers/verify",
            json={"token": token, "phone_last_four": "1234"},
        )

    assert current_phone.status_code == 401
    assert original_phone.status_code == 200


@pytest.mark.anyio
async def test_regenerate_and_revoke_invalidate_old_links_idempotently(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    regenerate_payload = {
        "idempotency_key": str(uuid.uuid4()),
        "revocation_idempotency_key": str(uuid.uuid4()),
        "reason": "候选人未收到原链接",
    }
    revoke_payload = {
        "idempotency_key": str(uuid.uuid4()),
        "reason": "薪酬方案需要重新确认",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "portal-recruiter")
        original = await _create_link(client, portal_dependencies)
        old_token = original.json()["portal_token"]
        invalid_reason = await client.post(
            f"/offers/{portal_dependencies.offer_id}/portal-links/regenerate",
            json={**regenerate_payload, "reason": "   "},
        )
        regenerated = await client.post(
            f"/offers/{portal_dependencies.offer_id}/portal-links/regenerate",
            json=regenerate_payload,
        )
        replay = await client.post(
            f"/offers/{portal_dependencies.offer_id}/portal-links/regenerate",
            json=regenerate_payload,
        )
        new_token = regenerated.json()["portal_token"]
        revoked = await client.post(
            f"/offers/{portal_dependencies.offer_id}/portal-links/"
            f"{regenerated.json()['id']}/revoke",
            json=revoke_payload,
        )
        revoke_replay = await client.post(
            f"/offers/{portal_dependencies.offer_id}/portal-links/"
            f"{regenerated.json()['id']}/revoke",
            json=revoke_payload,
        )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        old_status = await portal.post(
            "/portal/offers/status", json={"token": old_token}
        )
        new_status = await portal.post(
            "/portal/offers/status", json={"token": new_token}
        )

    assert invalid_reason.status_code == 422
    assert regenerated.status_code == replay.status_code == 201
    assert regenerated.json()["portal_token"]
    assert replay.json()["portal_token"] is None
    assert revoked.status_code == revoke_replay.status_code == 200
    assert old_status.status_code == new_status.status_code == 410
    with portal_dependencies.session_factory() as db:
        offer = db.get(Offer, portal_dependencies.offer_id)
        assert offer.status == "approved"
        assert offer.application.process.current_stage == "completed"
        assert [item.to_stage for item in offer.application.process.events] == [
            "offer_pending_response",
            "completed",
        ]


@pytest.mark.anyio
async def test_internal_permissions_missing_phone_and_expired_link(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "other-recruiter")
        hidden = await _create_link(client, portal_dependencies)
        assert hidden.status_code == 404

        await _login(client, "portal-manager")
        readonly = await _create_link(client, portal_dependencies)
        assert readonly.status_code == 403

    with portal_dependencies.session_factory() as db:
        offer = db.get(Offer, portal_dependencies.offer_id)
        offer.application.candidate.phone = None
        db.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _login(client, "portal-recruiter")
        missing_phone = await _create_link(client, portal_dependencies)
        assert missing_phone.status_code == 422

    with portal_dependencies.session_factory() as db:
        offer = db.get(Offer, portal_dependencies.offer_id)
        offer.application.candidate.phone = "13800001234"
        link = OfferPortalLink(
            id=(link_id := uuid.uuid4()),
            offer_id=offer.id,
            version_id=offer.current_version.id,
            idempotency_key=uuid.uuid4(),
            token_hash=hash_portal_token("expired-token" * 4),
            verification_phone_digest=phone_verification_digest(
                "1234",
                link_id=link_id,
                secret_key=settings.app_secret_key,
            ),
            expires_at=datetime.now(UTC) - timedelta(days=1),
            created_at=datetime.now(UTC) - timedelta(days=2),
            created_by_id=offer.created_by_id,
            created_by_username="portal-recruiter",
            created_by_display_name="门户招聘专员",
        )
        db.add(link)
        db.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        expired = await portal.post(
            "/portal/offers/status", json={"token": "expired-token" * 4}
        )
        unknown = await portal.post(
            "/portal/offers/status", json={"token": "unknown-token" * 4}
        )

    assert expired.status_code == 410
    assert unknown.status_code == 404


@pytest.mark.anyio
async def test_candidate_accepts_offer_idempotently_and_updates_process(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as internal:
        await _login(internal, "portal-recruiter")
        created = await _create_link(internal, portal_dependencies)
        token = created.json()["portal_token"]

    response_key = uuid.uuid4()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        verification_token = await _verify_link(portal, token)
        payload = {
            "token": token,
            "verification_token": verification_token,
            "idempotency_key": str(response_key),
            "decision": "accepted",
        }
        accepted = await portal.post("/portal/offers/respond", json=payload)
        replay = await portal.post("/portal/offers/respond", json=payload)
        detail = await portal.post(
            "/portal/offers/detail",
            json={"token": token, "verification_token": verification_token},
        )

    assert accepted.status_code == replay.status_code == detail.status_code == 200
    assert accepted.json() == replay.json() == detail.json()
    assert accepted.json()["progress"] == "accepted"
    assert accepted.json()["response"]["decision"] == "accepted"
    with portal_dependencies.session_factory() as db:
        offer = db.get(Offer, portal_dependencies.offer_id)
        responses = list(db.scalars(select(OfferResponse)).all())
        audits = list(
            db.scalars(
                select(AuditLog).where(AuditLog.action == "offer_portal.responded")
            ).all()
        )
        assert offer.status == "accepted"
        assert offer.application.process.current_stage == "onboarding_pending_confirmation"
        assert [item.to_stage for item in offer.application.process.events] == [
            "offer_pending_response",
            "onboarding_pending_confirmation",
        ]
        assert len(responses) == len(audits) == 1
        assert responses[0].idempotency_key == response_key
        assert audits[0].actor_username == "candidate_portal"
        assert audits[0].details["decision"] == "accepted"


@pytest.mark.anyio
async def test_candidate_rejects_offer_with_structured_reason(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as internal:
        await _login(internal, "portal-recruiter")
        created = await _create_link(internal, portal_dependencies)
        token = created.json()["portal_token"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        verification_token = await _verify_link(portal, token)
        missing_reason = await portal.post(
            "/portal/offers/respond",
            json={
                "token": token,
                "verification_token": verification_token,
                "idempotency_key": str(uuid.uuid4()),
                "decision": "rejected",
            },
        )
        rejected = await portal.post(
            "/portal/offers/respond",
            json={
                "token": token,
                "verification_token": verification_token,
                "idempotency_key": str(uuid.uuid4()),
                "decision": "rejected",
                "rejection_reason_code": "compensation",
                "rejection_note": "  薪资未达到预期  ",
            },
        )

    assert missing_reason.status_code == 422
    assert rejected.status_code == 200
    assert rejected.json()["progress"] == "declined"
    assert rejected.json()["response"]["rejection_reason_code"] == "compensation"
    assert rejected.json()["response"]["rejection_note"] == "薪资未达到预期"
    with portal_dependencies.session_factory() as db:
        offer = db.get(Offer, portal_dependencies.offer_id)
        assert offer.status == "declined"
        assert offer.application.process.current_stage == "offer_rejected"


@pytest.mark.anyio
async def test_candidate_response_rejects_invalid_session_and_conflicting_replies(
    portal_dependencies: PortalDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as internal:
        await _login(internal, "portal-recruiter")
        created = await _create_link(internal, portal_dependencies)
        token = created.json()["portal_token"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        invalid_session = await portal.post(
            "/portal/offers/respond",
            json={
                "token": token,
                "verification_token": "x" * 43,
                "idempotency_key": str(uuid.uuid4()),
                "decision": "accepted",
            },
        )
        verification_token = await _verify_link(portal, token)
        response_key = uuid.uuid4()
        accepted = await portal.post(
            "/portal/offers/respond",
            json={
                "token": token,
                "verification_token": verification_token,
                "idempotency_key": str(response_key),
                "decision": "accepted",
            },
        )
        different_key = await portal.post(
            "/portal/offers/respond",
            json={
                "token": token,
                "verification_token": verification_token,
                "idempotency_key": str(uuid.uuid4()),
                "decision": "accepted",
            },
        )
        different_decision = await portal.post(
            "/portal/offers/respond",
            json={
                "token": token,
                "verification_token": verification_token,
                "idempotency_key": str(response_key),
                "decision": "rejected",
                "rejection_reason_code": "other",
            },
        )

    assert invalid_session.status_code == 401
    assert accepted.status_code == 200
    assert different_key.status_code == different_decision.status_code == 409
    with portal_dependencies.session_factory() as db:
        response = db.scalar(
            select(OfferResponse).where(
                OfferResponse.offer_id == portal_dependencies.offer_id
            )
        )
        assert response is not None
        assert response.decision == "accepted"


@pytest.mark.anyio
async def test_candidate_response_rolls_back_when_audit_write_fails(
    portal_dependencies: PortalDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as internal:
        await _login(internal, "portal-recruiter")
        created = await _create_link(internal, portal_dependencies)
        token = created.json()["portal_token"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as portal:
        verification_token = await _verify_link(portal, token)

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(offer_portal_routes, "record_audit", fail_audit)
    failing_transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=failing_transport,
        base_url="http://test",
    ) as portal:
        failed = await portal.post(
            "/portal/offers/respond",
            json={
                "token": token,
                "verification_token": verification_token,
                "idempotency_key": str(uuid.uuid4()),
                "decision": "accepted",
            },
        )

    assert failed.status_code == 500
    with portal_dependencies.session_factory() as db:
        offer = db.get(Offer, portal_dependencies.offer_id)
        assert offer is not None
        assert offer.status == "pending_response"
        assert offer.candidate_response is None
        assert offer.application.process.current_stage == "offer_pending_response"
        assert [item.to_stage for item in offer.application.process.events] == [
            "offer_pending_response"
        ]
        assert db.scalar(select(OfferResponse)) is None
