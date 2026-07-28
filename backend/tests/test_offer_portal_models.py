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
    CandidateProcess,
    CandidateProcessEvent,
    Job,
    JobApplication,
    Offer,
    OfferPortalLink,
    OfferResponse,
    OfferVersion,
    User,
)
from app.services.offer_portal import phone_verification_digest
from app.services.security import hash_password


@pytest.fixture
def portal_session() -> Session:
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


def _seed_user(db: Session) -> User:
    user = User(
        username="portal-recruiter",
        password_hash=hash_password("correct-password"),
        display_name="门户招聘专员",
    )
    db.add(user)
    db.flush()
    return user


def _seed_offer(db: Session, user: User, suffix: str = "1") -> Offer:
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
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
    )
    offer = Offer(
        application=application,
        status="approved",
        created_by_id=user.id,
        versions=[version],
    )
    db.add_all([candidate, job, application, offer])
    db.flush()
    return offer


def _portal_link(
    offer: Offer,
    user: User,
    *,
    token_hash: str | None = None,
    idempotency_key: uuid.UUID | None = None,
) -> OfferPortalLink:
    link_id = uuid.uuid4()
    return OfferPortalLink(
        id=link_id,
        offer=offer,
        version=offer.current_version,
        idempotency_key=idempotency_key or uuid.uuid4(),
        token_hash=token_hash or uuid.uuid4().hex + uuid.uuid4().hex,
        verification_phone_digest=phone_verification_digest(
            "0001",
            link_id=link_id,
            secret_key="test-secret-key",
        ),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
    )


def test_portal_models_keep_link_response_and_process_history(
    portal_session: Session,
) -> None:
    assert CandidateProcess.__table__.c.current_stage.type.length == 40
    assert CandidateProcessEvent.__table__.c.from_stage.type.length == 40
    assert CandidateProcessEvent.__table__.c.to_stage.type.length == 40

    user = _seed_user(portal_session)
    offer = _seed_offer(portal_session, user)
    process = CandidateProcess(
        application=offer.application,
        current_stage="offer_pending_response",
        updated_by_id=user.id,
    )
    portal_session.add(process)
    portal_session.flush()
    process.events.append(
        CandidateProcessEvent(
            sequence_number=1,
            from_stage="completed",
            to_stage="offer_pending_response",
            reason="候选人 Offer 链接已生成",
            operator_id=user.id,
        )
    )
    link = _portal_link(offer, user)
    portal_session.add(link)
    offer.status = "pending_response"
    portal_session.flush()
    response = OfferResponse(
        offer=offer,
        version=offer.current_version,
        portal_link=link,
        idempotency_key=uuid.uuid4(),
        decision="accepted",
        verification_completed_at=datetime.now(UTC),
    )
    portal_session.add(response)
    offer.status = "accepted"
    process.current_stage = "onboarding_pending_confirmation"
    process.events.append(
        CandidateProcessEvent(
            sequence_number=2,
            from_stage="offer_pending_response",
            to_stage="onboarding_pending_confirmation",
            reason="候选人接受 Offer",
        )
    )
    portal_session.commit()

    assert offer.portal_links == [link]
    assert offer.candidate_response is response
    assert link.response is response
    assert response.version is offer.current_version
    assert process.current_stage == "onboarding_pending_confirmation"
    assert [item.to_stage for item in process.events] == [
        "offer_pending_response",
        "onboarding_pending_confirmation",
    ]


def test_only_one_unrevoked_portal_link_exists_per_offer(
    portal_session: Session,
) -> None:
    user = _seed_user(portal_session)
    offer = _seed_offer(portal_session, user)
    first = _portal_link(offer, user)
    portal_session.add(first)
    portal_session.commit()

    portal_session.add(_portal_link(offer, user))
    with pytest.raises(IntegrityError, match="offer_portal_links.offer_id"):
        portal_session.commit()
    portal_session.rollback()

    first = portal_session.get(OfferPortalLink, first.id)
    assert first is not None
    revoker_id = user.id
    revoker_username = user.username
    revoker_display_name = user.display_name
    first.revoked_by_id = revoker_id
    first.revoked_by_username = revoker_username
    first.revoked_by_display_name = revoker_display_name
    first.revocation_idempotency_key = uuid.uuid4()
    first.revocation_reason = "重新生成候选人链接"
    first.revoked_at = datetime.now(UTC)
    portal_session.commit()

    replacement = _portal_link(offer, user)
    portal_session.add(replacement)
    portal_session.commit()
    assert replacement.id is not None


@pytest.mark.parametrize(
    ("decision", "reason_code", "note"),
    [
        ("accepted", "compensation", None),
        ("accepted", None, "不应填写拒绝说明"),
        ("rejected", None, None),
        ("rejected", "unknown", None),
    ],
)
def test_offer_response_rejection_fields_follow_decision(
    portal_session: Session,
    decision: str,
    reason_code: str | None,
    note: str | None,
) -> None:
    user = _seed_user(portal_session)
    offer = _seed_offer(portal_session, user)
    link = _portal_link(offer, user)
    portal_session.add(link)
    portal_session.flush()
    portal_session.add(
        OfferResponse(
            offer=offer,
            version=offer.current_version,
            portal_link=link,
            idempotency_key=uuid.uuid4(),
            decision=decision,
            rejection_reason_code=reason_code,
            rejection_note=note,
            verification_completed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError, match="ck_offer_responses_rejection"):
        portal_session.commit()


def test_offer_response_requires_one_consistent_offer_chain(
    portal_session: Session,
) -> None:
    user = _seed_user(portal_session)
    first_offer = _seed_offer(portal_session, user, "1")
    second_offer = _seed_offer(portal_session, user, "2")
    link = _portal_link(first_offer, user)
    portal_session.add(link)
    portal_session.flush()
    portal_session.add(
        OfferResponse(
            offer_id=second_offer.id,
            version_id=second_offer.current_version.id,
            portal_link_id=link.id,
            idempotency_key=uuid.uuid4(),
            decision="accepted",
            verification_completed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
        portal_session.commit()


def test_offer_allows_only_one_final_candidate_response(
    portal_session: Session,
) -> None:
    user = _seed_user(portal_session)
    offer = _seed_offer(portal_session, user)
    first_link = _portal_link(offer, user)
    portal_session.add(first_link)
    portal_session.flush()
    portal_session.add(
        OfferResponse(
            offer=offer,
            version=offer.current_version,
            portal_link=first_link,
            idempotency_key=uuid.uuid4(),
            decision="rejected",
            rejection_reason_code="career",
            rejection_note="职业方向不匹配",
            verification_completed_at=datetime.now(UTC),
        )
    )
    first_link.revoked_at = datetime.now(UTC)
    first_link.revocation_idempotency_key = uuid.uuid4()
    first_link.revocation_reason = "测试第二条链接唯一性"
    portal_session.commit()

    second_link = _portal_link(offer, user)
    portal_session.add(second_link)
    portal_session.flush()
    portal_session.add(
        OfferResponse(
            offer_id=offer.id,
            version_id=offer.current_version.id,
            portal_link_id=second_link.id,
            idempotency_key=uuid.uuid4(),
            decision="accepted",
            verification_completed_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError, match="offer_responses.offer_id"):
        portal_session.commit()
