import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Candidate,
    Job,
    JobApplication,
    Offer,
    OfferApproval,
    OfferManagerConfirmation,
    OfferVersion,
    User,
)
from app.services.security import hash_password


@pytest.fixture
def offer_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def _offer_version(
    user: User,
    *,
    version_number: int = 1,
    idempotency_key: uuid.UUID | None = None,
    source_version_id: uuid.UUID | None = None,
) -> OfferVersion:
    return OfferVersion(
        version_number=version_number,
        idempotency_key=idempotency_key or uuid.uuid4(),
        source_version_id=source_version_id,
        currency="CNY",
        monthly_salary=Decimal("30000.00"),
        annual_salary_months=Decimal("14.00"),
        probation_months=3,
        probation_monthly_salary=Decimal("27000.00"),
        bonus_description="年度绩效奖金另计",
        expected_start_date=date.today() + timedelta(days=30),
        valid_until=date.today() + timedelta(days=7),
        notes="薪酬方案仅限授权人员查看",
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
    )


def _seed_application(db: Session) -> tuple[User, JobApplication]:
    recruiter = User(
        username="offer-recruiter",
        password_hash=hash_password("correct-password"),
        display_name="Offer 招聘专员",
    )
    db.add(recruiter)
    db.flush()
    candidate = Candidate(full_name="候选人A")
    job = Job(
        owner_id=recruiter.id,
        title="高级后端工程师",
        department="研发",
        original_jd="负责核心系统开发",
    )
    application = JobApplication(candidate=candidate, job=job)
    db.add_all([candidate, job, application])
    db.flush()
    return recruiter, application


def test_offer_keeps_immutable_versions_and_decision_history(
    offer_session: Session,
) -> None:
    recruiter, application = _seed_application(offer_session)
    first = _offer_version(recruiter)
    offer = Offer(
        application=application,
        created_by_id=recruiter.id,
        versions=[first],
    )
    offer_session.add(offer)
    offer_session.flush()

    first.manager_confirmation = OfferManagerConfirmation(
        confirmer_id=recruiter.id,
        confirmer_username="manager",
        confirmer_display_name="用人经理",
        decision="rejected",
        comment="请调整薪酬结构",
    )
    second = _offer_version(
        recruiter,
        version_number=2,
        source_version_id=first.id,
    )
    offer.versions.append(second)
    offer.current_version_number = 2
    offer.status = "pending_approval"
    second.manager_confirmation = OfferManagerConfirmation(
        confirmer_id=recruiter.id,
        confirmer_username="manager",
        confirmer_display_name="用人经理",
        decision="confirmed",
        comment="确认录用",
    )
    second.approval = OfferApproval(
        approver_id=recruiter.id,
        approver_username="approver",
        approver_display_name="审批人",
        decision="approved",
        comment="同意",
    )
    offer_session.commit()

    assert offer.current_version is second
    assert first.manager_confirmation.decision == "rejected"
    assert second.manager_confirmation.decision == "confirmed"
    assert second.approval.decision == "approved"
    assert first.monthly_salary == Decimal("30000.00")
    assert second.source_version_id == first.id


def test_offer_constraints_reject_duplicate_application_and_version_keys(
    offer_session: Session,
) -> None:
    recruiter, application = _seed_application(offer_session)
    key = uuid.uuid4()
    first_offer = Offer(
        application=application,
        created_by_id=recruiter.id,
        versions=[_offer_version(recruiter, idempotency_key=key)],
    )
    offer_session.add(first_offer)
    offer_session.commit()

    offer_session.add(
        Offer(
            application_id=application.id,
            created_by_id=recruiter.id,
            versions=[_offer_version(recruiter)],
        )
    )
    with pytest.raises(IntegrityError):
        offer_session.commit()
    offer_session.rollback()

    first_offer = offer_session.get(Offer, first_offer.id)
    assert first_offer is not None
    first_offer.versions.append(
        _offer_version(
            recruiter,
            version_number=2,
            idempotency_key=key,
            source_version_id=first_offer.current_version.id,
        )
    )
    with pytest.raises(IntegrityError):
        offer_session.commit()


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"currency": "USD"}, "ck_offer_versions_currency"),
        ({"monthly_salary": Decimal("0")}, "ck_offer_versions_monthly_salary"),
        (
            {"annual_salary_months": Decimal("0")},
            "ck_offer_versions_annual_salary_months",
        ),
        ({"probation_months": 13}, "ck_offer_versions_probation_months"),
        (
            {"probation_months": 0, "probation_monthly_salary": Decimal("1")},
            "ck_offer_versions_probation_salary",
        ),
    ],
)
def test_offer_version_financial_constraints(
    offer_session: Session,
    changes: dict[str, object],
    constraint: str,
) -> None:
    recruiter, application = _seed_application(offer_session)
    version = _offer_version(recruiter)
    for field, value in changes.items():
        setattr(version, field, value)
    offer_session.add(
        Offer(
            application=application,
            created_by_id=recruiter.id,
            versions=[version],
        )
    )

    with pytest.raises(IntegrityError, match=constraint):
        offer_session.commit()
