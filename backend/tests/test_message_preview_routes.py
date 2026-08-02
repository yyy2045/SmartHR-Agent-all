import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    Candidate,
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    InterviewPlanVersion,
    InterviewRound,
    Job,
    JobApplication,
    MessageTemplate,
    MessageTemplateVersion,
    Offer,
    OfferPortalLink,
    OfferResponse,
    OfferVersion,
    Role,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.message_template_defaults import ensure_default_message_templates
from app.services.offer_portal import hash_portal_token, phone_verification_digest
from app.services.onboarding import create_onboarding_for_acceptance
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass
class MessagePreviewDependencies:
    session_factory: sessionmaker[Session]
    template_versions: dict[str, uuid.UUID]
    interview_round_id: uuid.UUID
    offer_id: uuid.UUID
    onboarding_id: uuid.UUID
    missing_name_offer_id: uuid.UUID
    foreign_offer_id: uuid.UUID
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
def message_preview_dependencies() -> Generator[MessagePreviewDependencies, None, None]:
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
    raw_portal_token = "preview-raw-token-must-never-be-returned"

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
            full_name="候选人<script>alert(1)</script>{{offer_portal_link}}",
            phone="13800001234",
        )
        application = JobApplication(candidate=candidate, job=job)
        db.add_all([job, foreign_job, candidate, application])
        db.flush()

        plan = InterviewPlanVersion(
            job=job,
            version_number=1,
            status="confirmed",
            confirmed_by_id=recruiter.id,
            confirmed_at=datetime.now(UTC),
            rounds=[
                InterviewRound(
                    name="技术一面",
                    round_type="technical",
                    duration_minutes=60,
                    pass_threshold=70,
                    focus="系统设计",
                    sort_order=0,
                )
            ],
        )
        schedule = CandidateInterviewSchedule(
            application=application,
            plan_version=plan,
            status="scheduled",
            created_by_id=recruiter.id,
            rounds=[
                CandidateInterviewRound(
                    plan_round=plan.rounds[0],
                    sort_order=0,
                    scheduled_start_at=datetime(2026, 8, 1, 1, 30, tzinfo=UTC),
                    interview_method="phone",
                    status="scheduled",
                    updated_by_id=recruiter.id,
                )
            ],
        )
        offer = Offer(
            application=application,
            status="pending_response",
            created_by_id=recruiter.id,
            versions=[_offer_version(recruiter)],
        )

        onboarding_candidate = Candidate(full_name="入职候选人", phone="13900005678")
        onboarding_application = JobApplication(candidate=onboarding_candidate, job=job)
        onboarding_offer = Offer(
            application=onboarding_application,
            status="accepted",
            created_by_id=recruiter.id,
            versions=[_offer_version(recruiter)],
        )

        missing_name_candidate = Candidate(phone="13700004321")
        missing_name_application = JobApplication(candidate=missing_name_candidate, job=job)
        missing_name_offer = Offer(
            application=missing_name_application,
            status="pending_response",
            created_by_id=recruiter.id,
            versions=[_offer_version(recruiter)],
        )

        foreign_candidate = Candidate(full_name="其他候选人", phone="13600001111")
        foreign_application = JobApplication(candidate=foreign_candidate, job=foreign_job)
        foreign_offer = Offer(
            application=foreign_application,
            status="pending_response",
            created_by_id=other_recruiter.id,
            versions=[_offer_version(other_recruiter)],
        )
        db.add_all(
            [
                plan,
                schedule,
                offer,
                onboarding_candidate,
                onboarding_application,
                onboarding_offer,
                missing_name_candidate,
                missing_name_application,
                missing_name_offer,
                foreign_candidate,
                foreign_application,
                foreign_offer,
            ]
        )
        db.flush()

        link_id = uuid.uuid4()
        onboarding_link = OfferPortalLink(
            id=link_id,
            offer=onboarding_offer,
            version=onboarding_offer.current_version,
            idempotency_key=uuid.uuid4(),
            token_hash=hash_portal_token(raw_portal_token),
            verification_phone_digest=phone_verification_digest(
                "5678",
                link_id=link_id,
                secret_key=settings.app_secret_key,
            ),
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by_id=recruiter.id,
            created_by_username=recruiter.username,
            created_by_display_name=recruiter.display_name,
        )
        onboarding_response = OfferResponse(
            offer=onboarding_offer,
            version=onboarding_offer.current_version,
            portal_link=onboarding_link,
            idempotency_key=uuid.uuid4(),
            decision="accepted",
            verification_completed_at=datetime.now(UTC),
        )
        db.add_all([onboarding_link, onboarding_response])
        db.flush()
        onboarding = create_onboarding_for_acceptance(
            db,
            offer=onboarding_offer,
            response=onboarding_response,
            portal_link=onboarding_link,
        )
        db.commit()

        interview_round_id = schedule.rounds[0].id
        offer_id = offer.id
        onboarding_id = onboarding.id
        missing_name_offer_id = missing_name_offer.id
        foreign_offer_id = foreign_offer.id

    ensure_default_message_templates(testing_session)
    with testing_session() as db:
        template_versions = {
            template_type: version_id
            for template_type, version_id in db.execute(
                select(MessageTemplate.template_type, MessageTemplateVersion.id)
                .join(
                    MessageTemplateVersion,
                    MessageTemplateVersion.template_id == MessageTemplate.id,
                )
                .where(MessageTemplateVersion.version_number == 1)
            )
        }

    store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3_600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = lambda: store
    yield MessagePreviewDependencies(
        session_factory=testing_session,
        template_versions=template_versions,
        interview_round_id=interview_round_id,
        offer_id=offer_id,
        onboarding_id=onboarding_id,
        missing_name_offer_id=missing_name_offer_id,
        foreign_offer_id=foreign_offer_id,
        raw_portal_token=raw_portal_token,
    )
    app.dependency_overrides.clear()
    engine.dispose()


async def login(client: httpx.AsyncClient, username: str) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": "correct-password"},
    )
    assert response.status_code == 200


def preview_payload(
    dependencies: MessagePreviewDependencies,
    *,
    template_type: str,
    context_type: str,
    context_id: uuid.UUID,
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "template_version_id": str(dependencies.template_versions[template_type]),
        "context_type": context_type,
        "context_id": str(context_id),
    }
    payload.update(changes)
    return payload


@pytest.mark.asyncio
async def test_interview_preview_is_one_pass_and_cleans_missing_optional_line(
    message_preview_dependencies: MessagePreviewDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        response = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="interview_invitation",
                context_type="interview_round",
                context_id=message_preview_dependencies.interview_round_id,
            ),
        )
        manual = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="interview_invitation",
                context_type="interview_round",
                context_id=message_preview_dependencies.interview_round_id,
                subject_override="人工确认标题",
                body_override="人工确认正文",
            ),
        )

    assert response.status_code == 200, response.text
    result = response.json()
    assert "2026年8月1日 09:30" in result["body"]
    assert "会议信息：" not in result["body"]
    assert result["missing_optional_variables"] == ["meeting_info"]
    assert "<script>alert(1)</script>" in result["body"]
    assert "{{offer_portal_link}}" in result["body"]
    assert manual.status_code == 200, manual.text
    assert manual.json()["subject"] == "人工确认标题"
    assert manual.json()["body"] == "人工确认正文"
    assert manual.json()["variables_used"] == []


@pytest.mark.asyncio
async def test_offer_preview_hides_token_and_enforces_role_and_data_scope(
    message_preview_dependencies: MessagePreviewDependencies,
) -> None:
    payload = preview_payload(
        message_preview_dependencies,
        template_type="offer_notification",
        context_type="offer",
        context_id=message_preview_dependencies.offer_id,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.post("/communications/preview", json=payload)
        await login(client, "manager")
        manager = await client.post("/communications/preview", json=payload)
        await login(client, "approver")
        approver = await client.post("/communications/preview", json=payload)
        await login(client, "other-recruiter")
        outside_scope = await client.post("/communications/preview", json=payload)

    assert anonymous.status_code == 401
    assert manager.status_code == 200, manager.text
    serialized = manager.text
    assert "[候选人专属链接已隐藏]" in manager.json()["body"]
    assert message_preview_dependencies.raw_portal_token not in serialized
    assert "30000" not in serialized
    assert "13800001234" not in serialized
    assert approver.status_code == 403
    assert outside_scope.status_code == 404


@pytest.mark.asyncio
async def test_onboarding_preview_uses_current_reference_date(
    message_preview_dependencies: MessagePreviewDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "administrator")
        response = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="onboarding_date_confirmation",
                context_type="onboarding",
                context_id=message_preview_dependencies.onboarding_id,
            ),
        )

    assert response.status_code == 200, response.text
    expected_date = date.today() + timedelta(days=30)
    assert f"{expected_date.year}年{expected_date.month}月{expected_date.day}日" in response.json()[
        "body"
    ]


@pytest.mark.asyncio
async def test_preview_rejects_context_mismatch_unknown_and_missing_variables(
    message_preview_dependencies: MessagePreviewDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        mismatch = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="offer_notification",
                context_type="interview_round",
                context_id=message_preview_dependencies.interview_round_id,
            ),
        )
        unknown = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="offer_notification",
                context_type="offer",
                context_id=message_preview_dependencies.offer_id,
                body_override="薪酬：{{monthly_salary}}",
            ),
        )
        malformed = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="offer_notification",
                context_type="offer",
                context_id=message_preview_dependencies.offer_id,
                body_override="您好，{{candidate_name",
            ),
        )
        missing = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="offer_notification",
                context_type="offer",
                context_id=message_preview_dependencies.missing_name_offer_id,
            ),
        )

    assert mismatch.status_code == 422
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "unknown_template_variables"
    assert unknown.json()["detail"]["variables"] == ["monthly_salary"]
    assert malformed.status_code == 422
    assert missing.status_code == 422
    assert missing.json()["detail"] == {
        "code": "missing_required_variables",
        "message": "生成文案所需业务信息不完整",
        "variables": ["candidate_name"],
    }


@pytest.mark.asyncio
async def test_preview_rejects_invalid_business_state_and_variable_declaration(
    message_preview_dependencies: MessagePreviewDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        cancellation_for_scheduled_round = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="interview_cancellation",
                context_type="interview_round",
                context_id=message_preview_dependencies.interview_round_id,
            ),
        )
        invalid_template = await client.post(
            "/message-templates",
            json={
                "template_type": "offer_notification",
                "name": "变量声明不完整的测试模板",
                "subject": "{{candidate_name}} Offer 通知",
                "body": "固定正文",
                "variables": [],
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        invalid_declaration = await client.post(
            "/communications/preview",
            json={
                "template_version_id": invalid_template.json()["current_version"]["id"],
                "context_type": "offer",
                "context_id": str(message_preview_dependencies.offer_id),
            },
        )
        oversized = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="offer_notification",
                context_type="offer",
                context_id=message_preview_dependencies.offer_id,
                body_override="x" * 5_001,
            ),
        )

    assert cancellation_for_scheduled_round.status_code == 409
    assert invalid_template.status_code == 201
    assert invalid_declaration.status_code == 422
    assert invalid_declaration.json()["detail"]["code"] == (
        "template_variable_declaration_mismatch"
    )
    assert oversized.status_code == 422


@pytest.mark.asyncio
async def test_preview_allows_historical_version_but_rejects_inactive_template(
    message_preview_dependencies: MessagePreviewDependencies,
) -> None:
    old_version_id = message_preview_dependencies.template_versions["offer_notification"]
    with message_preview_dependencies.session_factory() as db:
        old_version = db.get(MessageTemplateVersion, old_version_id)
        assert old_version is not None
        template = old_version.template
        template.versions.append(
            MessageTemplateVersion(
                id=uuid.uuid4(),
                version_number=2,
                idempotency_key=uuid.uuid4(),
                source_version_id=old_version.id,
                subject=old_version.subject,
                body=old_version.body,
                variables=old_version.variables,
                created_by_username="recruiter",
                created_by_display_name="招聘专员甲",
            )
        )
        template.current_version_number = 2
        template.resource_version = 2
        db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        historical = await client.post(
            "/communications/preview",
            json=preview_payload(
                message_preview_dependencies,
                template_type="offer_notification",
                context_type="offer",
                context_id=message_preview_dependencies.offer_id,
            ),
        )

    assert historical.status_code == 200, historical.text
    assert historical.json()["template_version_id"] == str(old_version_id)

    with message_preview_dependencies.session_factory() as db:
        current = db.scalar(
            select(MessageTemplateVersion).where(
                MessageTemplateVersion.template_id == template.id,
                MessageTemplateVersion.version_number == 2,
            )
        )
        assert current is not None
        current_version_id = current.id
        current.template.status = "inactive"
        db.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "recruiter")
        inactive_payload = preview_payload(
            message_preview_dependencies,
            template_type="offer_notification",
            context_type="offer",
            context_id=message_preview_dependencies.offer_id,
        )
        inactive_payload["template_version_id"] = str(current_version_id)
        inactive = await client.post("/communications/preview", json=inactive_payload)

    assert inactive.status_code == 409
