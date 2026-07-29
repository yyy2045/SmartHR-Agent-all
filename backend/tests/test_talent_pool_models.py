import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Candidate,
    TalentPoolGroup,
    TalentPoolMembership,
    TalentPoolMembershipEvent,
    User,
)
from app.services.security import hash_password


@pytest.fixture
def talent_pool_session() -> Session:
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


def _user(db: Session) -> User:
    user = User(
        username="talent-pool-admin",
        password_hash=hash_password("correct-password"),
        display_name="人才库管理员",
    )
    db.add(user)
    db.flush()
    return user


def _membership(
    *,
    group: TalentPoolGroup,
    candidate: Candidate,
    user: User,
) -> TalentPoolMembership:
    return TalentPoolMembership(
        group=group,
        candidate=candidate,
        status="active",
        reason="候选人具备长期匹配价值",
        updated_by=user,
        events=[
            TalentPoolMembershipEvent(
                sequence_number=1,
                idempotency_key=uuid.uuid4(),
                action="added",
                from_status=None,
                to_status="active",
                reason="候选人具备长期匹配价值",
                candidate_id_snapshot=candidate.id,
                actor_user=user,
                actor_username=user.username,
                actor_display_name=user.display_name,
            )
        ],
    )


def test_active_group_name_is_case_insensitive_unique_and_reusable_after_archive(
    talent_pool_session: Session,
) -> None:
    user = _user(talent_pool_session)
    first = TalentPoolGroup(name="Core Talent", created_by=user)
    talent_pool_session.add(first)
    talent_pool_session.commit()

    talent_pool_session.add(TalentPoolGroup(name="core talent", created_by=user))
    with pytest.raises(IntegrityError):
        talent_pool_session.commit()
    talent_pool_session.rollback()

    stored = talent_pool_session.get(TalentPoolGroup, first.id)
    assert stored is not None
    stored.archived_at = datetime.now(UTC)
    stored.archived_by = user
    stored.version += 1
    replacement = TalentPoolGroup(name="core talent", created_by=user)
    talent_pool_session.add(replacement)
    talent_pool_session.commit()

    assert stored.is_archived is True
    assert replacement.is_archived is False


def test_candidate_has_one_current_membership_per_group_and_keeps_events(
    talent_pool_session: Session,
) -> None:
    user = _user(talent_pool_session)
    candidate = Candidate(full_name="人才候选人")
    group = TalentPoolGroup(name="后端人才", created_by=user)
    talent_pool_session.add_all([candidate, group])
    talent_pool_session.flush()
    membership = _membership(group=group, candidate=candidate, user=user)
    talent_pool_session.add(membership)
    talent_pool_session.commit()

    assert membership.status == "active"
    assert membership.version == 1
    assert [item.action for item in membership.events] == ["added"]
    assert candidate.talent_pool_memberships == [membership]

    duplicate = TalentPoolMembership(
        group_id=group.id,
        candidate_id=candidate.id,
        status="removed",
        reason="重复关系不应创建",
        removed_at=datetime.now(UTC),
    )
    talent_pool_session.add(duplicate)
    with pytest.raises(IntegrityError):
        talent_pool_session.commit()


def test_membership_event_sequence_and_idempotency_are_unique(
    talent_pool_session: Session,
) -> None:
    user = _user(talent_pool_session)
    candidate = Candidate(full_name="事件候选人")
    group = TalentPoolGroup(name="架构人才", created_by=user)
    talent_pool_session.add_all([candidate, group])
    talent_pool_session.flush()
    membership = _membership(group=group, candidate=candidate, user=user)
    talent_pool_session.add(membership)
    talent_pool_session.commit()

    first_event = membership.events[0]
    talent_pool_session.add(
        TalentPoolMembershipEvent(
            membership_id=membership.id,
            sequence_number=2,
            idempotency_key=first_event.idempotency_key,
            action="removed",
            from_status="active",
            to_status="removed",
            reason="测试重复幂等键",
            candidate_id_snapshot=candidate.id,
            actor_user_id=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        talent_pool_session.commit()
    talent_pool_session.rollback()

    stored_events = talent_pool_session.scalars(
        select(TalentPoolMembershipEvent).where(
            TalentPoolMembershipEvent.membership_id == membership.id
        )
    ).all()
    assert len(stored_events) == 1
