from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.candidate import JobApplication
    from app.models.offer import Offer, OfferResponse
    from app.models.user import User


ONBOARDING_STATUSES = (
    "pending_confirmation",
    "candidate_proposed_date",
    "pending_start",
    "onboarded",
    "abandoned",
)
ONBOARDING_STATUS_SQL = ", ".join(f"'{status}'" for status in ONBOARDING_STATUSES)

ONBOARDING_EVENT_ACTIONS = (
    "created",
    "candidate_confirmed_date",
    "candidate_proposed_date",
    "recruiter_accepted_date",
    "recruiter_proposed_date",
    "onboarded",
    "abandoned",
    "onboarded_corrected",
)
ONBOARDING_EVENT_ACTION_SQL = ", ".join(
    f"'{action}'" for action in ONBOARDING_EVENT_ACTIONS
)

ONBOARDING_ACTOR_TYPES = ("system", "candidate", "recruiter", "admin")
ONBOARDING_ACTOR_TYPE_SQL = ", ".join(
    f"'{actor_type}'" for actor_type in ONBOARDING_ACTOR_TYPES
)

ONBOARDING_ABANDONMENT_SOURCES = (
    "candidate_withdrew",
    "company_cancelled",
    "other",
)
ONBOARDING_ABANDONMENT_SOURCE_SQL = ", ".join(
    f"'{source}'" for source in ONBOARDING_ABANDONMENT_SOURCES
)

ONBOARDING_ABANDONMENT_REASONS = (
    "compensation",
    "career",
    "location",
    "start_date",
    "personal",
    "position_cancelled",
    "business_change",
    "other",
)
ONBOARDING_ABANDONMENT_REASON_SQL = ", ".join(
    f"'{reason}'" for reason in ONBOARDING_ABANDONMENT_REASONS
)


class Onboarding(Base):
    __tablename__ = "onboardings"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_onboardings_application"),
        UniqueConstraint("offer_id", name="uq_onboardings_offer"),
        UniqueConstraint("offer_response_id", name="uq_onboardings_offer_response"),
        CheckConstraint(
            f"status IN ({ONBOARDING_STATUS_SQL})",
            name="ck_onboardings_status",
        ),
        CheckConstraint("version >= 1", name="ck_onboardings_version"),
        CheckConstraint(
            "status <> 'candidate_proposed_date' OR candidate_proposed_date IS NOT NULL",
            name="ck_onboardings_candidate_proposal",
        ),
        CheckConstraint(
            "status NOT IN ('pending_start', 'onboarded') "
            "OR confirmed_start_date IS NOT NULL",
            name="ck_onboardings_confirmed_start",
        ),
        CheckConstraint(
            "(status = 'onboarded' AND actual_start_date IS NOT NULL) OR "
            "(status <> 'onboarded' AND actual_start_date IS NULL)",
            name="ck_onboardings_actual_start",
        ),
        CheckConstraint(
            "(status = 'abandoned' "
            "AND abandonment_source IS NOT NULL "
            "AND abandonment_reason_code IS NOT NULL "
            "AND abandonment_note IS NOT NULL "
            "AND length(trim(abandonment_note)) > 0) OR "
            "(status <> 'abandoned' "
            "AND abandonment_source IS NULL "
            "AND abandonment_reason_code IS NULL "
            "AND abandonment_note IS NULL)",
            name="ck_onboardings_abandonment_fields",
        ),
        CheckConstraint(
            "abandonment_source IS NULL OR "
            f"abandonment_source IN ({ONBOARDING_ABANDONMENT_SOURCE_SQL})",
            name="ck_onboardings_abandonment_source",
        ),
        CheckConstraint(
            "abandonment_reason_code IS NULL OR "
            f"abandonment_reason_code IN ({ONBOARDING_ABANDONMENT_REASON_SQL})",
            name="ck_onboardings_abandonment_reason",
        ),
        ForeignKeyConstraint(
            ["application_id", "offer_id"],
            ["offers.application_id", "offers.id"],
            ondelete="CASCADE",
            name="fk_onboardings_application_offer",
        ),
        ForeignKeyConstraint(
            ["offer_id", "offer_response_id"],
            ["offer_responses.offer_id", "offer_responses.id"],
            ondelete="CASCADE",
            name="fk_onboardings_offer_response",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    offer_response_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending_confirmation",
        server_default="pending_confirmation",
        index=True,
    )
    candidate_proposed_date: Mapped[date | None] = mapped_column(Date)
    recruiter_proposed_date: Mapped[date | None] = mapped_column(Date)
    confirmed_start_date: Mapped[date | None] = mapped_column(Date)
    actual_start_date: Mapped[date | None] = mapped_column(Date)
    abandonment_source: Mapped[str | None] = mapped_column(String(30))
    abandonment_reason_code: Mapped[str | None] = mapped_column(String(40))
    abandonment_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    application: Mapped[JobApplication] = relationship(
        back_populates="onboarding",
        foreign_keys=[application_id],
        overlaps="offer,onboarding",
    )
    offer: Mapped[Offer] = relationship(
        back_populates="onboarding",
        foreign_keys=[application_id, offer_id],
        overlaps="application,onboarding",
    )
    offer_response: Mapped[OfferResponse] = relationship(
        back_populates="onboarding",
        foreign_keys=[offer_id, offer_response_id],
        overlaps="offer,onboarding",
    )
    events: Mapped[list[OnboardingEvent]] = relationship(
        back_populates="onboarding",
        cascade="all, delete-orphan",
        order_by="OnboardingEvent.sequence_number",
    )


class OnboardingEvent(Base):
    __tablename__ = "onboarding_events"
    __table_args__ = (
        CheckConstraint(
            f"action IN ({ONBOARDING_EVENT_ACTION_SQL})",
            name="ck_onboarding_events_action",
        ),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({ONBOARDING_STATUS_SQL})",
            name="ck_onboarding_events_from_status",
        ),
        CheckConstraint(
            f"to_status IN ({ONBOARDING_STATUS_SQL})",
            name="ck_onboarding_events_to_status",
        ),
        CheckConstraint(
            f"actor_type IN ({ONBOARDING_ACTOR_TYPE_SQL})",
            name="ck_onboarding_events_actor_type",
        ),
        CheckConstraint("sequence_number >= 1", name="ck_onboarding_events_sequence"),
        UniqueConstraint(
            "onboarding_id",
            "sequence_number",
            name="uq_onboarding_events_sequence",
        ),
        UniqueConstraint(
            "onboarding_id",
            "idempotency_key",
            name="uq_onboarding_events_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    onboarding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("onboardings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    date_before: Mapped[date | None] = mapped_column(Date)
    date_after: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    actor_username: Mapped[str | None] = mapped_column(String(64))
    actor_display_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    onboarding: Mapped[Onboarding] = relationship(back_populates="events")
    actor_user: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])
