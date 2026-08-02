import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Candidate,
    InternalNotification,
    Job,
    JobApplication,
    Offer,
    OfferResponse,
    OfferVersion,
    Onboarding,
    OnboardingEvent,
    RecruitmentRequest,
    RecruitmentRequestVersion,
    Role,
    User,
    UserRole,
)
from app.services.recruitment_notifications import (
    notify_offer_approval_decided,
    notify_offer_candidate_responded,
    notify_offer_manager_decided,
    notify_offer_submitted,
    notify_onboarding_event,
    notify_recruitment_request_decided,
    notify_recruitment_request_submitted,
)
from app.services.security import hash_password


@pytest.fixture
def notification_domain_session() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _user(username: str, role: Role, *, active: bool = True) -> User:
    return User(
        username=username,
        password_hash=hash_password("correct-password"),
        display_name=username,
        is_active=active,
        role_assignments=[UserRole(role=role)],
    )


def _seed_roles_and_users(db: Session) -> dict[str, User]:
    roles = {
        key: Role(key=key, display_name=key)
        for key in ("administrator", "recruiter", "hiring_manager", "approver")
    }
    users = {
        "recruiter": _user("recruiter", roles["recruiter"]),
        "manager": _user("manager", roles["hiring_manager"]),
        "approver": _user("approver", roles["approver"]),
        "inactive_approver": _user(
            "inactive-approver",
            roles["approver"],
            active=False,
        ),
    }
    db.add_all([*roles.values(), *users.values()])
    db.flush()
    return users


def _request(users: dict[str, User]) -> RecruitmentRequest:
    request = RecruitmentRequest(
        idempotency_key=uuid.uuid4(),
        requester_id=users["manager"].id,
        recruiter_id=users["recruiter"].id,
        created_by_id=users["manager"].id,
        status="pending_approval",
        versions=[
            RecruitmentRequestVersion(
                version_number=1,
                created_by_id=users["manager"].id,
                created_by_username=users["manager"].username,
                created_by_display_name=users["manager"].display_name,
                job_title="高级后端工程师",
                headcount=2,
                reason="平台扩容",
                priority="high",
                target_start_date=date.today() + timedelta(days=30),
                salary_min=25000,
                salary_max=35000,
                notes="需要尽快到岗",
            )
        ],
    )
    request.requester = users["manager"]
    request.recruiter = users["recruiter"]
    return request


def _offer_graph(users: dict[str, User]) -> tuple[Offer, OfferResponse, Onboarding]:
    job = Job(
        owner=users["recruiter"],
        hiring_manager=users["manager"],
        title="高级后端工程师",
        department="研发",
        original_jd="负责平台服务开发",
    )
    candidate = Candidate(
        full_name="候选人A",
        phone="13800001234",
        email="candidate@example.com",
    )
    application = JobApplication(candidate=candidate, job=job)
    offer = Offer(
        application=application,
        created_by_id=users["recruiter"].id,
        current_version_number=1,
        versions=[
            OfferVersion(
                version_number=1,
                idempotency_key=uuid.uuid4(),
                submission_idempotency_key=uuid.uuid4(),
                submitted_at=datetime.now(UTC),
                monthly_salary=Decimal("30000"),
                annual_salary_months=Decimal("13"),
                probation_months=3,
                probation_monthly_salary=Decimal("24000"),
                bonus_description="项目奖金",
                expected_start_date=date.today() + timedelta(days=60),
                valid_until=date.today() + timedelta(days=30),
                notes="内部备注",
                created_by_id=users["recruiter"].id,
                created_by_username=users["recruiter"].username,
                created_by_display_name=users["recruiter"].display_name,
            )
        ],
    )
    response = OfferResponse(
        offer=offer,
        version=offer.current_version,
        portal_link_id=uuid.uuid4(),
        idempotency_key=uuid.uuid4(),
        decision="accepted",
        verification_completed_at=datetime.now(UTC),
    )
    onboarding = Onboarding(
        application=application,
        offer=offer,
        offer_response=response,
        status="pending_confirmation",
        events=[
            OnboardingEvent(
                sequence_number=1,
                idempotency_key=response.idempotency_key,
                action="created",
                from_status=None,
                to_status="pending_confirmation",
                actor_type="system",
            )
        ],
    )
    return offer, response, onboarding


def _notifications(db: Session) -> list[InternalNotification]:
    return list(
        db.scalars(
            select(InternalNotification).order_by(
                InternalNotification.notification_type,
                InternalNotification.recipient_user_id,
            )
        )
    )


def _assert_safe(notification: InternalNotification) -> None:
    text = f"{notification.title}\n{notification.summary}"
    assert "13800001234" not in text
    assert "candidate@example.com" not in text
    assert "25000" not in text
    assert "30000" not in text
    assert "/portal/offers/" not in text


def test_recruitment_request_notifications_are_idempotent_and_safe(
    notification_domain_session: sessionmaker[Session],
) -> None:
    with notification_domain_session() as db:
        users = _seed_roles_and_users(db)
        request = _request(users)
        db.add(request)
        db.commit()

        notify_recruitment_request_submitted(db, request)
        notify_recruitment_request_submitted(db, request)
        notify_recruitment_request_decided(db, request, decision="approved")
        db.commit()

        notifications = _notifications(db)
        assert [item.notification_type for item in notifications] == [
            "recruitment_request_approved",
            "recruitment_request_approved",
            "recruitment_request_submitted",
        ]
        assert db.scalar(select(func.count(InternalNotification.id))) == 3
        assert {
            item.recipient_user_id
            for item in notifications
            if item.notification_type == "recruitment_request_submitted"
        } == {users["approver"].id}
        for item in notifications:
            _assert_safe(item)


def test_offer_flow_notifications_cover_manager_approval_and_candidate_response(
    notification_domain_session: sessionmaker[Session],
) -> None:
    with notification_domain_session() as db:
        users = _seed_roles_and_users(db)
        offer, response, _onboarding = _offer_graph(users)
        db.add(offer)
        db.add(response)
        db.commit()

        notify_offer_submitted(db, offer)
        notify_offer_manager_decided(db, offer, decision="confirmed")
        notify_offer_approval_decided(db, offer, decision="approved")
        notify_offer_candidate_responded(db, offer, response)
        notify_offer_candidate_responded(db, offer, response)
        db.commit()

        notifications = _notifications(db)
        assert [item.notification_type for item in notifications] == [
            "offer_approval_requested",
            "offer_approved",
            "offer_approved",
            "offer_candidate_accepted",
            "offer_candidate_accepted",
            "offer_manager_confirmation_requested",
        ]
        assert db.scalar(select(func.count(InternalNotification.id))) == 6
        for item in notifications:
            _assert_safe(item)


def test_onboarding_event_notifications_cover_dates_completion_and_abandonment(
    notification_domain_session: sessionmaker[Session],
) -> None:
    with notification_domain_session() as db:
        users = _seed_roles_and_users(db)
        offer, response, onboarding = _offer_graph(users)
        db.add_all([offer, response, onboarding])
        db.commit()

        events = [
            OnboardingEvent(
                onboarding_id=onboarding.id,
                sequence_number=2,
                idempotency_key=uuid.uuid4(),
                action="candidate_proposed_date",
                from_status="pending_confirmation",
                to_status="candidate_proposed_date",
                actor_type="candidate",
            ),
            OnboardingEvent(
                onboarding_id=onboarding.id,
                sequence_number=3,
                idempotency_key=uuid.uuid4(),
                action="recruiter_accepted_date",
                from_status="candidate_proposed_date",
                to_status="pending_start",
                actor_type="recruiter",
                actor_user_id=users["recruiter"].id,
            ),
            OnboardingEvent(
                onboarding_id=onboarding.id,
                sequence_number=4,
                idempotency_key=uuid.uuid4(),
                action="onboarded",
                from_status="pending_start",
                to_status="onboarded",
                actor_type="recruiter",
                actor_user_id=users["recruiter"].id,
            ),
            OnboardingEvent(
                onboarding_id=onboarding.id,
                sequence_number=5,
                idempotency_key=uuid.uuid4(),
                action="abandoned",
                from_status="pending_start",
                to_status="abandoned",
                actor_type="candidate",
            ),
        ]
        db.add_all(events)
        db.flush()

        for event in events:
            notify_onboarding_event(db, onboarding, event)
        notify_onboarding_event(db, onboarding, events[0])
        db.commit()

        notifications = _notifications(db)
        assert [item.notification_type for item in notifications] == [
            "onboarding_abandoned",
            "onboarding_abandoned",
            "onboarding_completed",
            "onboarding_completed",
            "onboarding_date_changed",
            "onboarding_date_changed",
        ]
        assert db.scalar(select(func.count(InternalNotification.id))) == 6
        for item in notifications:
            _assert_safe(item)
