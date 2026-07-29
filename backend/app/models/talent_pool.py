from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.candidate import Candidate, JobApplication
    from app.models.user import User


TALENT_POOL_MEMBERSHIP_STATUSES = ("active", "removed")
TALENT_POOL_MEMBERSHIP_STATUS_SQL = ", ".join(
    f"'{status}'" for status in TALENT_POOL_MEMBERSHIP_STATUSES
)

TALENT_POOL_MEMBERSHIP_ACTIONS = ("added", "removed", "candidate_merged")
TALENT_POOL_MEMBERSHIP_ACTION_SQL = ", ".join(
    f"'{action}'" for action in TALENT_POOL_MEMBERSHIP_ACTIONS
)


class TalentPoolGroup(Base):
    __tablename__ = "talent_pool_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
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

    __table_args__ = (
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_talent_pool_groups_name_not_blank",
        ),
        CheckConstraint("version >= 1", name="ck_talent_pool_groups_version"),
        Index(
            "uq_talent_pool_groups_active_name_ci",
            func.lower(name),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
            sqlite_where=text("archived_at IS NULL"),
        ),
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    archived_by: Mapped[User | None] = relationship(foreign_keys=[archived_by_id])
    memberships: Mapped[list[TalentPoolMembership]] = relationship(
        back_populates="group",
        order_by="TalentPoolMembership.created_at",
    )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class TalentPoolMembership(Base):
    __tablename__ = "talent_pool_memberships"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("talent_pool_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_applications.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({TALENT_POOL_MEMBERSHIP_STATUS_SQL})",
            name="ck_talent_pool_memberships_status",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_talent_pool_memberships_reason_not_blank",
        ),
        CheckConstraint("version >= 1", name="ck_talent_pool_memberships_version"),
        CheckConstraint(
            "(status = 'active' AND removed_at IS NULL) OR "
            "(status = 'removed' AND removed_at IS NOT NULL)",
            name="ck_talent_pool_memberships_removed_at",
        ),
        UniqueConstraint(
            "group_id",
            "candidate_id",
            name="uq_talent_pool_memberships_group_candidate",
        ),
        Index(
            "ix_talent_pool_memberships_group_status",
            "group_id",
            "status",
        ),
        Index(
            "ix_talent_pool_memberships_candidate_status",
            "candidate_id",
            "status",
        ),
    )

    group: Mapped[TalentPoolGroup] = relationship(back_populates="memberships")
    candidate: Mapped[Candidate] = relationship(back_populates="talent_pool_memberships")
    source_application: Mapped[JobApplication | None] = relationship(
        foreign_keys=[source_application_id]
    )
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])
    events: Mapped[list[TalentPoolMembershipEvent]] = relationship(
        back_populates="membership",
        cascade="all, delete-orphan",
        order_by="TalentPoolMembershipEvent.sequence_number",
    )


class TalentPoolMembershipEvent(Base):
    __tablename__ = "talent_pool_membership_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("talent_pool_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_id_snapshot: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    target_candidate_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_application_id_snapshot: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    actor_username: Mapped[str | None] = mapped_column(String(64))
    actor_display_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            f"action IN ({TALENT_POOL_MEMBERSHIP_ACTION_SQL})",
            name="ck_talent_pool_membership_events_action",
        ),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({TALENT_POOL_MEMBERSHIP_STATUS_SQL})",
            name="ck_talent_pool_membership_events_from_status",
        ),
        CheckConstraint(
            f"to_status IN ({TALENT_POOL_MEMBERSHIP_STATUS_SQL})",
            name="ck_talent_pool_membership_events_to_status",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_talent_pool_membership_events_reason_not_blank",
        ),
        CheckConstraint(
            "sequence_number >= 1",
            name="ck_talent_pool_membership_events_sequence",
        ),
        CheckConstraint(
            "(action = 'candidate_merged' AND target_candidate_id_snapshot IS NOT NULL) OR "
            "(action <> 'candidate_merged' AND target_candidate_id_snapshot IS NULL)",
            name="ck_talent_pool_membership_events_merge_target",
        ),
        UniqueConstraint(
            "membership_id",
            "sequence_number",
            name="uq_talent_pool_membership_events_sequence",
        ),
        UniqueConstraint(
            "membership_id",
            "idempotency_key",
            name="uq_talent_pool_membership_events_idempotency",
        ),
    )

    membership: Mapped[TalentPoolMembership] = relationship(back_populates="events")
    actor_user: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])
