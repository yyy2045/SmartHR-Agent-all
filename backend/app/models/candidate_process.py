from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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
    from app.models.user import User


PROCESS_STAGES = (
    "unprocessed",
    "pending",
    "shortlisted",
    "to_contact",
    "contacted",
    "to_interview",
    "completed",
    "rejected",
    "offer_pending_response",
    "offer_rejected",
    "onboarding_pending_confirmation",
)
PROCESS_STAGE_SQL = ", ".join(f"'{stage}'" for stage in PROCESS_STAGES)


class CandidateProcess(Base):
    __tablename__ = "candidate_processes"
    __table_args__ = (
        CheckConstraint(
            f"current_stage IN ({PROCESS_STAGE_SQL})",
            name="ck_candidate_processes_stage",
        ),
        UniqueConstraint("application_id", name="uq_candidate_process_application"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    current_stage: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    stage_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    application: Mapped[JobApplication] = relationship(back_populates="process")
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])
    events: Mapped[list[CandidateProcessEvent]] = relationship(
        back_populates="process",
        cascade="all, delete-orphan",
        order_by="CandidateProcessEvent.sequence_number",
    )


class CandidateProcessEvent(Base):
    __tablename__ = "candidate_process_events"
    __table_args__ = (
        CheckConstraint(
            f"from_stage IN ({PROCESS_STAGE_SQL})",
            name="ck_candidate_process_events_from_stage",
        ),
        CheckConstraint(
            f"to_stage IN ({PROCESS_STAGE_SQL})",
            name="ck_candidate_process_events_to_stage",
        ),
        CheckConstraint("sequence_number >= 1", name="ck_candidate_process_events_sequence"),
        UniqueConstraint(
            "process_id",
            "sequence_number",
            name="uq_candidate_process_event_sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    process_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_processes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    process: Mapped[CandidateProcess] = relationship(back_populates="events")
    operator: Mapped[User | None] = relationship(foreign_keys=[operator_id])
