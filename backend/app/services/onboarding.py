from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Offer, OfferPortalLink, OfferResponse, Onboarding, OnboardingEvent, User

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_WRITABLE_STATUSES = {
    "pending_confirmation",
    "candidate_proposed_date",
    "pending_start",
}


class OnboardingConflictError(Exception):
    pass


class OnboardingValidationError(Exception):
    pass


def shanghai_today() -> date:
    return datetime.now(_SHANGHAI).date()


def onboarding_portal_expiry(reference_date: date) -> datetime:
    local_expiry = datetime.combine(
        reference_date + timedelta(days=30),
        time(23, 59, 59),
        _SHANGHAI,
    )
    return local_expiry.astimezone(UTC)


def onboarding_action_owner(onboarding: Onboarding) -> str:
    if onboarding.status == "candidate_proposed_date":
        return "recruiter"
    if onboarding.status == "pending_confirmation":
        return "candidate"
    return "none"


def onboarding_reference_date(onboarding: Onboarding) -> date:
    if onboarding.status == "onboarded" and onboarding.actual_start_date is not None:
        return onboarding.actual_start_date
    if onboarding.status == "abandoned":
        return shanghai_today()
    if onboarding.status == "candidate_proposed_date":
        return (
            onboarding.candidate_proposed_date
            or onboarding.offer.current_version.expected_start_date
        )
    if onboarding.status == "pending_confirmation":
        return (
            onboarding.recruiter_proposed_date
            or onboarding.offer.current_version.expected_start_date
        )
    return onboarding.confirmed_start_date or onboarding.offer.current_version.expected_start_date


def sync_portal_access_expiry(onboarding: Onboarding) -> None:
    expires_at = onboarding_portal_expiry(onboarding_reference_date(onboarding))
    for link in onboarding.offer.portal_links:
        if link.revoked_at is None:
            link.expires_at = expires_at


def _append_event(
    db: Session,
    onboarding: Onboarding,
    *,
    idempotency_key: uuid.UUID,
    action: str,
    from_status: str | None,
    to_status: str,
    date_before: date | None = None,
    date_after: date | None = None,
    reason: str | None = None,
    actor_type: str,
    actor: User | None = None,
) -> OnboardingEvent:
    event = OnboardingEvent(
        onboarding_id=onboarding.id,
        sequence_number=len(onboarding.events) + 1,
        idempotency_key=idempotency_key,
        action=action,
        from_status=from_status,
        to_status=to_status,
        date_before=date_before,
        date_after=date_after,
        reason=reason,
        actor_type=actor_type,
        actor_user_id=actor.id if actor is not None else None,
        actor_username=actor.username if actor is not None else None,
        actor_display_name=actor.display_name if actor is not None else None,
    )
    onboarding.events.append(event)
    return event


def create_onboarding_for_acceptance(
    db: Session,
    *,
    offer: Offer,
    response: OfferResponse,
    portal_link: OfferPortalLink,
) -> Onboarding:
    if offer.onboarding is not None:
        if offer.onboarding.offer_response_id == response.id:
            return offer.onboarding
        raise OnboardingConflictError("Offer 已关联其他入职记录")

    onboarding = Onboarding(
        application_id=offer.application_id,
        offer_id=offer.id,
        offer_response_id=response.id,
        status="pending_confirmation",
    )
    db.add(onboarding)
    db.flush()
    _append_event(
        db,
        onboarding,
        idempotency_key=response.idempotency_key,
        action="created",
        from_status=None,
        to_status="pending_confirmation",
        reason="候选人接受 Offer，系统创建入职记录",
        actor_type="system",
    )
    portal_link.expires_at = onboarding_portal_expiry(
        offer.current_version.expected_start_date
    )
    return onboarding


def find_event_by_key(
    onboarding: Onboarding,
    idempotency_key: uuid.UUID,
) -> OnboardingEvent | None:
    return next(
        (event for event in onboarding.events if event.idempotency_key == idempotency_key),
        None,
    )


def ensure_replay(
    event: OnboardingEvent,
    *,
    action: str,
    date_after: date | None,
    reason: str | None,
) -> None:
    if (
        event.action != action
        or event.date_after != date_after
        or event.reason != reason
    ):
        raise OnboardingConflictError("幂等键已用于不同的入职操作")


def ensure_version(onboarding: Onboarding, version: int) -> None:
    if onboarding.version != version:
        raise OnboardingConflictError("入职状态已更新，请刷新后重试")


def _validate_future_date(value: date) -> None:
    if value < shanghai_today():
        raise OnboardingValidationError("入职日期不能早于操作当天")


def _validate_date_note(onboarding: Onboarding, value: date, note: str | None) -> None:
    if value != onboarding.offer.current_version.expected_start_date and note is None:
        raise OnboardingValidationError("入职日期偏离 Offer 预计日期时必须填写说明")


def candidate_confirm_date(
    db: Session,
    onboarding: Onboarding,
    *,
    idempotency_key: uuid.UUID,
    version: int,
    start_date: date,
) -> OnboardingEvent:
    replay = find_event_by_key(onboarding, idempotency_key)
    if replay is not None:
        ensure_replay(
            replay,
            action="candidate_confirmed_date",
            date_after=start_date,
            reason=None,
        )
        return replay
    ensure_version(onboarding, version)
    if onboarding.status != "pending_confirmation":
        raise OnboardingConflictError("当前入职状态不等待候选人确认日期")
    expected = (
        onboarding.recruiter_proposed_date
        or onboarding.offer.current_version.expected_start_date
    )
    if start_date != expected:
        raise OnboardingConflictError("确认日期不是招聘方当前提议日期")
    _validate_future_date(start_date)
    previous_status = onboarding.status
    previous_date = onboarding.confirmed_start_date
    onboarding.confirmed_start_date = start_date
    onboarding.status = "pending_start"
    onboarding.version += 1
    event = _append_event(
        db,
        onboarding,
        idempotency_key=idempotency_key,
        action="candidate_confirmed_date",
        from_status=previous_status,
        to_status="pending_start",
        date_before=previous_date,
        date_after=start_date,
        actor_type="candidate",
    )
    sync_portal_access_expiry(onboarding)
    return event


def candidate_propose_date(
    db: Session,
    onboarding: Onboarding,
    *,
    idempotency_key: uuid.UUID,
    version: int,
    proposed_date: date,
    note: str | None,
) -> OnboardingEvent:
    replay = find_event_by_key(onboarding, idempotency_key)
    if replay is not None:
        ensure_replay(
            replay,
            action="candidate_proposed_date",
            date_after=proposed_date,
            reason=note,
        )
        return replay
    ensure_version(onboarding, version)
    if onboarding.status != "pending_confirmation":
        raise OnboardingConflictError("当前入职状态不允许候选人重新提议日期")
    _validate_future_date(proposed_date)
    current_offer_date = onboarding.offer.current_version.expected_start_date
    if proposed_date == (onboarding.recruiter_proposed_date or current_offer_date):
        raise OnboardingValidationError("同意当前日期时请使用确认操作")
    _validate_date_note(onboarding, proposed_date, note)
    previous_status = onboarding.status
    previous_date = onboarding.candidate_proposed_date
    onboarding.candidate_proposed_date = proposed_date
    onboarding.status = "candidate_proposed_date"
    onboarding.version += 1
    event = _append_event(
        db,
        onboarding,
        idempotency_key=idempotency_key,
        action="candidate_proposed_date",
        from_status=previous_status,
        to_status="candidate_proposed_date",
        date_before=previous_date,
        date_after=proposed_date,
        reason=note,
        actor_type="candidate",
    )
    sync_portal_access_expiry(onboarding)
    return event


def recruiter_date_decision(
    db: Session,
    onboarding: Onboarding,
    *,
    idempotency_key: uuid.UUID,
    version: int,
    decision: str,
    proposed_date: date | None,
    note: str | None,
    actor: User,
) -> OnboardingEvent:
    if decision == "accept":
        action = "recruiter_accepted_date"
        event_date = onboarding.candidate_proposed_date
    else:
        action = "recruiter_proposed_date"
        event_date = proposed_date
    replay = find_event_by_key(onboarding, idempotency_key)
    if replay is not None:
        ensure_replay(replay, action=action, date_after=event_date, reason=note)
        return replay
    ensure_version(onboarding, version)

    previous_status = onboarding.status
    if decision == "accept":
        if (
            onboarding.status != "candidate_proposed_date"
            or onboarding.candidate_proposed_date is None
        ):
            raise OnboardingConflictError("当前没有等待招聘方确认的候选人日期")
        previous_date = onboarding.confirmed_start_date
        onboarding.confirmed_start_date = onboarding.candidate_proposed_date
        onboarding.status = "pending_start"
        target_status = "pending_start"
    else:
        if onboarding.status not in _WRITABLE_STATUSES:
            raise OnboardingConflictError("当前入职状态不能再提议日期")
        if proposed_date is None:
            raise OnboardingValidationError("招聘方必须填写新日期")
        _validate_future_date(proposed_date)
        _validate_date_note(onboarding, proposed_date, note)
        previous_date = onboarding.recruiter_proposed_date
        onboarding.recruiter_proposed_date = proposed_date
        onboarding.confirmed_start_date = None
        onboarding.status = "pending_confirmation"
        target_status = "pending_confirmation"

    onboarding.version += 1
    event = _append_event(
        db,
        onboarding,
        idempotency_key=idempotency_key,
        action=action,
        from_status=previous_status,
        to_status=target_status,
        date_before=previous_date,
        date_after=event_date,
        reason=note,
        actor_type="admin" if actor.has_role("administrator") else "recruiter",
        actor=actor,
    )
    sync_portal_access_expiry(onboarding)
    return event


def mark_onboarded(
    db: Session,
    onboarding: Onboarding,
    *,
    idempotency_key: uuid.UUID,
    version: int,
    actual_start_date: date,
    note: str | None,
    actor: User,
) -> OnboardingEvent:
    replay = find_event_by_key(onboarding, idempotency_key)
    if replay is not None:
        ensure_replay(
            replay,
            action="onboarded",
            date_after=actual_start_date,
            reason=note,
        )
        return replay
    ensure_version(onboarding, version)
    if onboarding.status != "pending_start":
        raise OnboardingConflictError("只有待入职记录可以标记已入职")
    if actual_start_date > shanghai_today():
        raise OnboardingValidationError("实际入职日期不能晚于操作当天")
    previous_status = onboarding.status
    onboarding.actual_start_date = actual_start_date
    onboarding.status = "onboarded"
    onboarding.version += 1
    event = _append_event(
        db,
        onboarding,
        idempotency_key=idempotency_key,
        action="onboarded",
        from_status=previous_status,
        to_status="onboarded",
        date_before=None,
        date_after=actual_start_date,
        reason=note,
        actor_type="admin" if actor.has_role("administrator") else "recruiter",
        actor=actor,
    )
    sync_portal_access_expiry(onboarding)
    return event


def abandon_onboarding(
    db: Session,
    onboarding: Onboarding,
    *,
    idempotency_key: uuid.UUID,
    version: int,
    source: str,
    reason_code: str,
    note: str,
    actor_type: str,
    actor: User | None,
) -> OnboardingEvent:
    replay = find_event_by_key(onboarding, idempotency_key)
    if replay is not None:
        ensure_replay(replay, action="abandoned", date_after=None, reason=note)
        if (
            onboarding.abandonment_source != source
            or onboarding.abandonment_reason_code != reason_code
        ):
            raise OnboardingConflictError("幂等键已用于不同的放弃入职操作")
        return replay
    ensure_version(onboarding, version)
    if onboarding.status not in _WRITABLE_STATUSES:
        raise OnboardingConflictError("当前入职状态不能标记放弃")
    previous_status = onboarding.status
    onboarding.status = "abandoned"
    onboarding.abandonment_source = source
    onboarding.abandonment_reason_code = reason_code
    onboarding.abandonment_note = note
    onboarding.version += 1
    event = _append_event(
        db,
        onboarding,
        idempotency_key=idempotency_key,
        action="abandoned",
        from_status=previous_status,
        to_status="abandoned",
        reason=note,
        actor_type=actor_type,
        actor=actor,
    )
    sync_portal_access_expiry(onboarding)
    return event


def correct_onboarded_status(
    db: Session,
    onboarding: Onboarding,
    *,
    idempotency_key: uuid.UUID,
    version: int,
    reason: str,
    actor: User,
) -> OnboardingEvent:
    replay = find_event_by_key(onboarding, idempotency_key)
    if replay is not None:
        ensure_replay(
            replay,
            action="onboarded_corrected",
            date_after=onboarding.confirmed_start_date,
            reason=reason,
        )
        return replay
    ensure_version(onboarding, version)
    if onboarding.status != "onboarded" or onboarding.actual_start_date is None:
        raise OnboardingConflictError("只有已入职记录可以执行更正")
    previous_actual_date = onboarding.actual_start_date
    onboarding.actual_start_date = None
    onboarding.status = "pending_start"
    onboarding.version += 1
    event = _append_event(
        db,
        onboarding,
        idempotency_key=idempotency_key,
        action="onboarded_corrected",
        from_status="onboarded",
        to_status="pending_start",
        date_before=previous_actual_date,
        date_after=onboarding.confirmed_start_date,
        reason=reason,
        actor_type="admin",
        actor=actor,
    )
    sync_portal_access_expiry(onboarding)
    return event
