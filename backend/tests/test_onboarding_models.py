import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Candidate,
    Job,
    JobApplication,
    Offer,
    OfferPortalLink,
    OfferResponse,
    OfferVersion,
    Onboarding,
    OnboardingEvent,
    User,
)
from app.services.offer_portal import phone_verification_digest
from app.services.security import hash_password


@pytest.fixture
def onboarding_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def _seed_accepted_offer(db: Session, suffix: str = "1") -> tuple[Offer, OfferResponse]:
    user = User(
        username=f"onboarding-recruiter-{suffix}",
        password_hash=hash_password("correct-password"),
        display_name="入职招聘专员",
    )
    db.add(user)
    db.flush()
    candidate = Candidate(full_name=f"候选人{suffix}", phone=f"1380000{int(suffix):04d}")
    job = Job(
        owner_id=user.id,
        title=f"后端工程师{suffix}",
        department="研发",
        original_jd="负责核心系统开发",
    )
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
        created_by=user,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
    )
    offer = Offer(
        application=application,
        status="accepted",
        created_by=user,
        versions=[version],
    )
    db.add_all([candidate, job, application, offer])
    db.flush()
    link_id = uuid.uuid4()
    link = OfferPortalLink(
        id=link_id,
        offer=offer,
        version=version,
        idempotency_key=uuid.uuid4(),
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        verification_phone_digest=phone_verification_digest(
            "0001",
            link_id=link_id,
            secret_key="test-secret-key",
        ),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_by=user,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
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
    return offer, response


def _new_onboarding(offer: Offer, response: OfferResponse) -> Onboarding:
    return Onboarding(
        application=offer.application,
        offer=offer,
        offer_response=response,
        status="pending_confirmation",
        events=[
            OnboardingEvent(
                sequence_number=1,
                idempotency_key=uuid.uuid4(),
                action="created",
                from_status=None,
                to_status="pending_confirmation",
                reason="候选人接受 Offer，系统创建入职记录",
                actor_type="system",
            )
        ],
    )


def test_onboarding_keeps_current_state_and_immutable_event_history(
    onboarding_session: Session,
) -> None:
    offer, response = _seed_accepted_offer(onboarding_session)
    onboarding = _new_onboarding(offer, response)
    onboarding_session.add(onboarding)
    onboarding_session.commit()

    assert offer.application.onboarding is onboarding
    assert offer.onboarding is onboarding
    assert response.onboarding is onboarding
    assert onboarding.status == "pending_confirmation"
    assert onboarding.version == 1
    assert [item.action for item in onboarding.events] == ["created"]


def test_onboarding_requires_one_consistent_offer_chain(
    onboarding_session: Session,
) -> None:
    first_offer, first_response = _seed_accepted_offer(onboarding_session, "1")
    second_offer, _ = _seed_accepted_offer(onboarding_session, "2")
    onboarding_session.add(
        Onboarding(
            application_id=second_offer.application_id,
            offer_id=first_offer.id,
            offer_response_id=first_response.id,
            status="pending_confirmation",
        )
    )

    with pytest.raises(IntegrityError):
        onboarding_session.commit()


def test_only_one_onboarding_exists_for_an_application(
    onboarding_session: Session,
) -> None:
    offer, response = _seed_accepted_offer(onboarding_session)
    onboarding_session.add(_new_onboarding(offer, response))
    onboarding_session.commit()

    onboarding_session.add(_new_onboarding(offer, response))
    with pytest.raises(IntegrityError):
        onboarding_session.commit()


@pytest.mark.parametrize(
    "onboarding",
    [
        Onboarding(status="candidate_proposed_date"),
        Onboarding(status="pending_start"),
        Onboarding(status="onboarded", confirmed_start_date=date.today()),
        Onboarding(
            status="pending_confirmation",
            actual_start_date=date.today(),
        ),
        Onboarding(
            status="abandoned",
            abandonment_source="candidate_withdrew",
            abandonment_reason_code="personal",
        ),
        Onboarding(
            status="pending_confirmation",
            abandonment_source="other",
            abandonment_reason_code="other",
            abandonment_note="不应在非放弃状态出现",
        ),
    ],
)
def test_onboarding_rejects_inconsistent_status_fields(
    onboarding_session: Session,
    onboarding: Onboarding,
) -> None:
    offer, response = _seed_accepted_offer(onboarding_session)
    onboarding.application_id = offer.application_id
    onboarding.offer_id = offer.id
    onboarding.offer_response_id = response.id
    onboarding_session.add(onboarding)

    with pytest.raises(IntegrityError):
        onboarding_session.commit()


def test_onboarding_event_sequence_and_idempotency_are_unique(
    onboarding_session: Session,
) -> None:
    offer, response = _seed_accepted_offer(onboarding_session)
    onboarding = _new_onboarding(offer, response)
    onboarding_session.add(onboarding)
    onboarding_session.commit()

    existing_key = onboarding.events[0].idempotency_key
    onboarding_session.add(
        OnboardingEvent(
            onboarding_id=onboarding.id,
            sequence_number=2,
            idempotency_key=existing_key,
            action="candidate_proposed_date",
            from_status="pending_confirmation",
            to_status="candidate_proposed_date",
            date_after=date.today() + timedelta(days=30),
            actor_type="candidate",
        )
    )
    with pytest.raises(IntegrityError):
        onboarding_session.commit()
