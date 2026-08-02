import json
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    Candidate,
    CommunicationRecord,
    Job,
    JobApplication,
    MessageTemplate,
    MessageTemplateVersion,
    Offer,
    OfferVersion,
    Role,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.message_template_defaults import ensure_default_message_templates
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class CommunicationRouteDependencies:
    session_factory: sessionmaker[Session]
    offer_id: uuid.UUID
    foreign_offer_id: uuid.UUID
    missing_contact_offer_id: uuid.UUID
    template_version_id: uuid.UUID
    candidate_phone: str
    candidate_email: str
    raw_portal_token: str


def _offer_version(recruiter: User) -> OfferVersion:
    return OfferVersion(
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
        notes="仅授权人员可见",
        created_by_id=recruiter.id,
        created_by_username=recruiter.username,
        created_by_display_name=recruiter.display_name,
    )


@pytest.fixture
def communication_route_dependencies() -> Generator[CommunicationRouteDependencies, None, None]:
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

        def user(username: str, role_key: str, display_name: str) -> User:
            return User(
                username=username,
                password_hash=hash_password("correct-password"),
                display_name=display_name,
                role_assignments=[UserRole(role=roles[role_key])],
            )

        recruiter = user("recruiter", "recruiter", "招聘专员甲")
        other_recruiter = user("other-recruiter", "recruiter", "招聘专员乙")
        manager = user("manager", "hiring_manager", "用人经理甲")
        approver = user("approver", "approver", "审批人甲")
        administrator = user("administrator", "administrator", "管理员甲")
        db.add_all([*roles.values(), recruiter, other_recruiter, manager, approver, administrator])
        db.flush()

        job = Job(
            owner=recruiter,
            hiring_manager=manager,
            title="高级后端工程师",
            department="研发",
            original_jd="负责核心服务开发",
        )
        foreign_job = Job(
            owner=other_recruiter,
            title="数据工程师",
            department="研发",
            original_jd="负责数据平台开发",
        )
        candidate = Candidate(
            full_name="候选人甲",
            phone="13800001234",
            email="candidate@example.com",
        )
        missing_contact_candidate = Candidate(full_name="候选人乙")
        foreign_candidate = Candidate(full_name="候选人丙", phone="13900005678")
        application = JobApplication(candidate=candidate, job=job)
        missing_contact_application = JobApplication(candidate=missing_contact_candidate, job=job)
        foreign_application = JobApplication(candidate=foreign_candidate, job=foreign_job)
        offer = Offer(
            application=application,
            status="pending_response",
            created_by_id=recruiter.id,
            versions=[_offer_version(recruiter)],
        )
        missing_contact_offer = Offer(
            application=missing_contact_application,
            status="pending_response",
            created_by_id=recruiter.id,
            versions=[_offer_version(recruiter)],
        )
        foreign_offer = Offer(
            application=foreign_application,
            status="pending_response",
            created_by_id=other_recruiter.id,
            versions=[_offer_version(other_recruiter)],
        )
        db.add_all(
            [
                job,
                foreign_job,
                application,
                missing_contact_application,
                foreign_application,
                offer,
                missing_contact_offer,
                foreign_offer,
            ]
        )
        db.commit()
        offer_id = offer.id
        missing_contact_offer_id = missing_contact_offer.id
        foreign_offer_id = foreign_offer.id

    ensure_default_message_templates(testing_session)
    with testing_session() as db:
        template_version_id = db.scalar(
            select(MessageTemplateVersion.id)
            .join(MessageTemplate)
            .where(MessageTemplate.template_type == "offer_notification")
        )
        assert template_version_id is not None

    store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3_600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: store
    yield CommunicationRouteDependencies(
        session_factory=testing_session,
        offer_id=offer_id,
        foreign_offer_id=foreign_offer_id,
        missing_contact_offer_id=missing_contact_offer_id,
        template_version_id=template_version_id,
        candidate_phone="13800001234",
        candidate_email="candidate@example.com",
        raw_portal_token="raw-token-value-that-must-never-persist",
    )
    app.dependency_overrides.clear()
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


def sent_payload(
    dependencies: CommunicationRouteDependencies,
    *,
    key: uuid.UUID | None = None,
    context_id: uuid.UUID | None = None,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "context_type": "offer",
        "context_id": str(context_id or dependencies.offer_id),
        "template_version_id": str(dependencies.template_version_id),
        "channel": "wechat",
        "subject": "Offer 通知",
        "body": "请通过 [候选人专属链接已隐藏] 查看 Offer。",
        "sent_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        "idempotency_key": str(key or uuid.uuid4()),
    }
    payload.update(changes)
    return payload


def correction_payload(
    *,
    key: uuid.UUID | None = None,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "channel": "wechat",
        "subject": "Offer 通知更正",
        "body": "已通过外部工具重新告知候选人。",
        "sent_at": (datetime.now(UTC) - timedelta(minutes=3)).isoformat(),
        "correction_reason": "原登记内容不完整",
        "idempotency_key": str(key or uuid.uuid4()),
    }
    payload.update(changes)
    return payload


@pytest.mark.asyncio
async def test_create_list_detail_and_idempotency_keep_sensitive_data_masked(
    communication_route_dependencies: CommunicationRouteDependencies,
) -> None:
    key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        payload = sent_payload(communication_route_dependencies, key=key)
        created = await client.post("/communications", json=payload)
        replayed = await client.post("/communications", json=payload)
        reused = await client.post(
            "/communications",
            json=sent_payload(
                communication_route_dependencies,
                key=key,
                body="不同正文",
            ),
        )
        listed = await client.get("/communications?limit=10")
        detail = await client.get(f"/communications/{created.json()['id']}")

    assert created.status_code == 201, created.text
    assert replayed.status_code == 201
    assert replayed.json()["id"] == created.json()["id"]
    assert reused.status_code == 409
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert detail.status_code == 200
    created_payload = created.json()
    assert created_payload["recipient_masked"] == "138****1234"
    serialized = json.dumps(created_payload, ensure_ascii=False)
    assert communication_route_dependencies.candidate_phone not in serialized
    assert communication_route_dependencies.candidate_email not in serialized
    assert "30000" not in serialized
    assert communication_route_dependencies.raw_portal_token not in serialized
    with communication_route_dependencies.session_factory() as db:
        assert db.scalar(select(func.count(CommunicationRecord.id))) == 1
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "communication.sent_recorded"))
        assert audit is not None
        audit_payload = json.dumps(audit.details, ensure_ascii=False)
        assert communication_route_dependencies.candidate_phone not in audit_payload
        assert communication_route_dependencies.candidate_email not in audit_payload
        assert "30000" not in audit_payload
        assert communication_route_dependencies.raw_portal_token not in audit_payload


@pytest.mark.asyncio
async def test_copy_audit_is_idempotent_and_does_not_create_communication_record(
    communication_route_dependencies: CommunicationRouteDependencies,
) -> None:
    key = uuid.uuid4()
    raw_link = f"https://example.com/portal/offers/{communication_route_dependencies.raw_portal_token}"
    payload = {
        "context_type": "offer",
        "context_id": str(communication_route_dependencies.offer_id),
        "template_version_id": str(communication_route_dependencies.template_version_id),
        "subject": "Offer 通知",
        "body": f"请访问 {raw_link}",
        "idempotency_key": str(key),
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "manager")
        copied = await client.post("/communications/copy-audit", json=payload)
        replayed = await client.post("/communications/copy-audit", json=payload)
        reused = await client.post(
            "/communications/copy-audit",
            json={**payload, "body": "不同正文"},
        )
        await login(client, "approver")
        approver = await client.post("/communications/copy-audit", json=payload)

    assert copied.status_code == 200, copied.text
    assert replayed.status_code == 200
    assert replayed.json()["audit_id"] == copied.json()["audit_id"]
    assert reused.status_code == 409
    assert approver.status_code == 403
    with communication_route_dependencies.session_factory() as db:
        assert db.scalar(select(func.count(CommunicationRecord.id))) == 0
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "communication.copied"))
        assert audit is not None
        audit_payload = json.dumps(audit.details, ensure_ascii=False)
        assert communication_route_dependencies.raw_portal_token not in audit_payload
        assert raw_link not in audit_payload


@pytest.mark.asyncio
async def test_role_scope_and_channel_validation_are_enforced(
    communication_route_dependencies: CommunicationRouteDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get("/communications")
        await login(client, "manager")
        manager_write = await client.post(
            "/communications",
            json=sent_payload(communication_route_dependencies),
        )
        await login(client, "approver")
        approver_list = await client.get("/communications")
        await login(client, "other-recruiter")
        outside_scope = await client.post(
            "/communications",
            json=sent_payload(communication_route_dependencies),
        )
        await login(client, "recruiter")
        missing_phone = await client.post(
            "/communications",
            json=sent_payload(
                communication_route_dependencies,
                context_id=communication_route_dependencies.missing_contact_offer_id,
                channel="sms",
            ),
        )
        missing_email = await client.post(
            "/communications",
            json=sent_payload(
                communication_route_dependencies,
                context_id=communication_route_dependencies.missing_contact_offer_id,
                channel="email",
            ),
        )
        other_without_detail = await client.post(
            "/communications",
            json=sent_payload(communication_route_dependencies, channel="other"),
        )
        non_other_with_detail = await client.post(
            "/communications",
            json=sent_payload(communication_route_dependencies, channel_detail="多余说明"),
        )
        no_template = await client.post(
            "/communications",
            json=sent_payload(communication_route_dependencies, template_version_id=None),
        )
        historical_without_note = await client.post(
            "/communications",
            json=sent_payload(
                communication_route_dependencies,
                template_version_id=None,
                is_historical=True,
            ),
        )
        salary_leak = await client.post(
            "/communications",
            json=sent_payload(communication_route_dependencies, body="月薪 30000"),
        )
        token_leak = await client.post(
            "/communications",
            json=sent_payload(
                communication_route_dependencies,
                body="https://example.com/portal/offers/raw-token-value-that-must-never-persist",
            ),
        )

    assert anonymous.status_code == 401
    assert manager_write.status_code == 403
    assert approver_list.status_code == 403
    assert outside_scope.status_code == 404
    assert missing_phone.status_code == 422
    assert missing_email.status_code == 422
    assert other_without_detail.status_code == 422
    assert non_other_with_detail.status_code == 422
    assert no_template.status_code == 422
    assert historical_without_note.status_code == 422
    assert salary_leak.status_code == 422
    assert token_leak.status_code == 422


@pytest.mark.asyncio
async def test_correction_chain_is_linear_idempotent_and_readable_in_detail(
    communication_route_dependencies: CommunicationRouteDependencies,
) -> None:
    correction_key = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        original = await client.post(
            "/communications",
            json=sent_payload(communication_route_dependencies),
        )
        original_id = original.json()["id"]
        first_payload = correction_payload(key=correction_key)
        first = await client.post(
            f"/communications/{original_id}/corrections",
            json=first_payload,
        )
        replayed = await client.post(
            f"/communications/{original_id}/corrections",
            json=first_payload,
        )
        duplicate_branch = await client.post(
            f"/communications/{original_id}/corrections",
            json=correction_payload(),
        )
        second = await client.post(
            f"/communications/{first.json()['id']}/corrections",
            json=correction_payload(correction_reason="继续补充说明"),
        )
        detail = await client.get(f"/communications/{original_id}")
        await login(client, "manager")
        manager_correction = await client.post(
            f"/communications/{first.json()['id']}/corrections",
            json=correction_payload(),
        )

    assert original.status_code == 201
    assert first.status_code == 201, first.text
    assert replayed.status_code == 201
    assert replayed.json()["id"] == first.json()["id"]
    assert duplicate_branch.status_code == 409
    assert second.status_code == 201, second.text
    assert second.json()["correction_sequence"] == 2
    assert detail.status_code == 200
    assert [item["correction_sequence"] for item in detail.json()["corrections"]] == [1, 2]
    assert manager_correction.status_code == 403