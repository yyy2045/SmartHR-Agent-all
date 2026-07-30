from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Candidate,
    JobApplication,
    TalentPoolGroup,
    TalentPoolMembership,
    TalentPoolMembershipEvent,
    User,
)
from app.schemas.talent_pool import TalentPoolMemberInput
from app.services.audit import record_audit


class TalentPoolServiceError(Exception):
    def __init__(self, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class MembershipOperationResult:
    requested_candidate_id: uuid.UUID
    candidate_id: uuid.UUID
    membership_id: uuid.UUID | None
    status: str


@dataclass(frozen=True)
class MembershipOperationOutcome:
    group: TalentPoolGroup
    group_version: int
    items: tuple[MembershipOperationResult, ...]


def _fingerprint(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _find_idempotent_audit(
    db: Session,
    *,
    action: str,
    group_id: uuid.UUID,
    idempotency_key: uuid.UUID,
) -> AuditLog | None:
    logs = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.action == action,
            AuditLog.target_type == "talent_pool_group",
            AuditLog.target_id == group_id,
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    ).all()
    expected_key = str(idempotency_key)
    return next(
        (
            log
            for log in logs
            if isinstance(log.details, dict)
            and log.details.get("idempotency_key") == expected_key
        ),
        None,
    )


def _check_replay(audit: AuditLog | None, *, fingerprint: str) -> dict[str, Any] | None:
    if audit is None:
        return None
    details = audit.details if isinstance(audit.details, dict) else {}
    if details.get("fingerprint") != fingerprint:
        raise TalentPoolServiceError("幂等键已被不同请求使用", status_code=409)
    return details


def _get_group(
    db: Session,
    group_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> TalentPoolGroup:
    statement = select(TalentPoolGroup).where(TalentPoolGroup.id == group_id)
    if for_update:
        statement = statement.with_for_update()
    group = db.scalar(statement)
    if group is None:
        raise TalentPoolServiceError("人才分组不存在", status_code=404)
    return group


def create_group(
    db: Session,
    *,
    name: str,
    description: str | None,
    idempotency_key: uuid.UUID,
    actor: User,
) -> TalentPoolGroup:
    request_fingerprint = _fingerprint({"name": name, "description": description})
    group_id = uuid.uuid5(uuid.NAMESPACE_URL, f"talent-pool-group:{idempotency_key}")
    existing = db.get(TalentPoolGroup, group_id)
    if existing is not None:
        replay = _check_replay(
            _find_idempotent_audit(
                db,
                action="talent_pool.group_created",
                group_id=group_id,
                idempotency_key=idempotency_key,
            ),
            fingerprint=request_fingerprint,
        )
        if replay is None:
            raise TalentPoolServiceError("人才分组创建标识冲突", status_code=409)
        return existing

    group = TalentPoolGroup(
        id=group_id,
        name=name,
        description=description,
        created_by_id=actor.id,
    )
    db.add(group)
    db.flush()
    record_audit(
        db,
        action="talent_pool.group_created",
        target_type="talent_pool_group",
        target_id=group.id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "fingerprint": request_fingerprint,
            "name": name,
        },
    )
    return group


def update_group(
    db: Session,
    *,
    group_id: uuid.UUID,
    name_is_set: bool,
    name: str | None,
    description_is_set: bool,
    description: str | None,
    expected_version: int,
    idempotency_key: uuid.UUID,
    actor: User,
) -> TalentPoolGroup:
    group = _get_group(db, group_id, for_update=True)
    request_fingerprint = _fingerprint(
        {
            "name_is_set": name_is_set,
            "name": name,
            "description_is_set": description_is_set,
            "description": description,
            "expected_version": expected_version,
        }
    )
    replay = _check_replay(
        _find_idempotent_audit(
            db,
            action="talent_pool.group_updated",
            group_id=group.id,
            idempotency_key=idempotency_key,
        ),
        fingerprint=request_fingerprint,
    )
    if replay is not None:
        return group
    if group.is_archived:
        raise TalentPoolServiceError("归档分组不能修改", status_code=409)
    if group.version != expected_version:
        raise TalentPoolServiceError("人才分组版本已变化，请刷新后重试", status_code=409)

    changed_fields: list[str] = []
    if name_is_set and name != group.name:
        if name is None:
            raise TalentPoolServiceError("人才分组名称不能设为空", status_code=422)
        group.name = name
        changed_fields.append("name")
    if description_is_set and description != group.description:
        group.description = description
        changed_fields.append("description")
    if changed_fields:
        group.version += 1
    db.flush()
    record_audit(
        db,
        action="talent_pool.group_updated",
        target_type="talent_pool_group",
        target_id=group.id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "fingerprint": request_fingerprint,
            "changed_fields": changed_fields,
            "version": group.version,
        },
    )
    return group


def archive_group(
    db: Session,
    *,
    group_id: uuid.UUID,
    expected_version: int,
    idempotency_key: uuid.UUID,
    reason: str,
    actor: User,
) -> TalentPoolGroup:
    group = _get_group(db, group_id, for_update=True)
    request_fingerprint = _fingerprint(
        {"expected_version": expected_version, "reason": reason}
    )
    replay = _check_replay(
        _find_idempotent_audit(
            db,
            action="talent_pool.group_archived",
            group_id=group.id,
            idempotency_key=idempotency_key,
        ),
        fingerprint=request_fingerprint,
    )
    if replay is not None:
        return group
    if group.is_archived:
        raise TalentPoolServiceError("人才分组已经归档", status_code=409)
    if group.version != expected_version:
        raise TalentPoolServiceError("人才分组版本已变化，请刷新后重试", status_code=409)

    group.archived_at = datetime.now(UTC)
    group.archived_by_id = actor.id
    group.version += 1
    record_audit(
        db,
        action="talent_pool.group_archived",
        target_type="talent_pool_group",
        target_id=group.id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "fingerprint": request_fingerprint,
            "reason": reason,
            "version": group.version,
        },
    )
    return group


def _resolve_candidate(db: Session, candidate_id: uuid.UUID) -> Candidate:
    visited: set[uuid.UUID] = set()
    current_id = candidate_id
    while current_id not in visited:
        visited.add(current_id)
        candidate = db.scalar(
            select(Candidate).where(Candidate.id == current_id).with_for_update()
        )
        if candidate is None:
            raise TalentPoolServiceError("候选人不存在", status_code=404)
        if candidate.status == "active":
            return candidate
        if candidate.merged_into_candidate_id is None:
            raise TalentPoolServiceError("已合并候选人缺少保留主档", status_code=409)
        current_id = candidate.merged_into_candidate_id
    raise TalentPoolServiceError("候选人合并关系存在循环", status_code=409)


def _validate_source_application(
    db: Session,
    *,
    source_application_id: uuid.UUID | None,
    candidate_id: uuid.UUID,
) -> None:
    if source_application_id is None:
        return
    application = db.get(JobApplication, source_application_id)
    if application is None:
        raise TalentPoolServiceError("来源应聘不存在", status_code=404)
    if application.candidate_id != candidate_id:
        raise TalentPoolServiceError("来源应聘不属于当前候选人", status_code=422)


def _next_event_sequence(db: Session, membership_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(
                func.coalesce(func.max(TalentPoolMembershipEvent.sequence_number), 0) + 1
            ).where(TalentPoolMembershipEvent.membership_id == membership_id)
        )
        or 1
    )


def _append_event(
    db: Session,
    *,
    membership: TalentPoolMembership,
    idempotency_key: uuid.UUID,
    action: str,
    from_status: str | None,
    to_status: str,
    reason: str,
    candidate_id: uuid.UUID,
    source_application_id: uuid.UUID | None,
    actor: User,
) -> None:
    membership.events.append(
        TalentPoolMembershipEvent(
            sequence_number=_next_event_sequence(db, membership.id),
            idempotency_key=idempotency_key,
            action=action,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            candidate_id_snapshot=candidate_id,
            source_application_id_snapshot=source_application_id,
            actor_user_id=actor.id,
            actor_username=actor.username,
            actor_display_name=actor.display_name,
        )
    )


def _operation_items_from_audit(details: dict[str, Any]) -> tuple[MembershipOperationResult, ...]:
    raw_items = details.get("items")
    if not isinstance(raw_items, list):
        raise TalentPoolServiceError("幂等操作记录不完整", status_code=409)
    return tuple(
        MembershipOperationResult(
            requested_candidate_id=uuid.UUID(str(item["requested_candidate_id"])),
            candidate_id=uuid.UUID(str(item["candidate_id"])),
            membership_id=(
                uuid.UUID(str(item["membership_id"]))
                if item.get("membership_id") is not None
                else None
            ),
            status=str(item["status"]),
        )
        for item in raw_items
        if isinstance(item, dict)
    )


def _audit_membership_operation(
    db: Session,
    *,
    action: str,
    group: TalentPoolGroup,
    idempotency_key: uuid.UUID,
    fingerprint: str,
    reason: str,
    items: list[MembershipOperationResult],
    actor: User,
) -> None:
    record_audit(
        db,
        action=action,
        target_type="talent_pool_group",
        target_id=group.id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "fingerprint": fingerprint,
            "reason": reason,
            "group_version": group.version,
            "items": [
                {
                    "requested_candidate_id": str(item.requested_candidate_id),
                    "candidate_id": str(item.candidate_id),
                    "membership_id": (
                        str(item.membership_id) if item.membership_id is not None else None
                    ),
                    "status": item.status,
                }
                for item in items
            ],
        },
    )


def add_memberships(
    db: Session,
    *,
    group_id: uuid.UUID,
    members: list[TalentPoolMemberInput],
    reason: str,
    expected_group_version: int,
    idempotency_key: uuid.UUID,
    actor: User,
) -> MembershipOperationOutcome:
    group = _get_group(db, group_id, for_update=True)
    request_members = sorted(
        (
            str(item.candidate_id),
            str(item.source_application_id) if item.source_application_id else None,
        )
        for item in members
    )
    request_fingerprint = _fingerprint(
        {
            "members": request_members,
            "reason": reason,
            "expected_group_version": expected_group_version,
        }
    )
    replay = _check_replay(
        _find_idempotent_audit(
            db,
            action="talent_pool.members_added",
            group_id=group.id,
            idempotency_key=idempotency_key,
        ),
        fingerprint=request_fingerprint,
    )
    if replay is not None:
        return MembershipOperationOutcome(
            group=group,
            group_version=int(replay["group_version"]),
            items=_operation_items_from_audit(replay),
        )
    if group.is_archived:
        raise TalentPoolServiceError("归档分组不能新增成员", status_code=409)
    if group.version != expected_group_version:
        raise TalentPoolServiceError("人才分组版本已变化，请刷新后重试", status_code=409)

    resolved: list[tuple[TalentPoolMemberInput, Candidate]] = []
    resolved_ids: set[uuid.UUID] = set()
    for item in members:
        candidate = _resolve_candidate(db, item.candidate_id)
        if candidate.id in resolved_ids:
            raise TalentPoolServiceError("候选人合并后在同一批次发生重复", status_code=422)
        resolved_ids.add(candidate.id)
        _validate_source_application(
            db,
            source_application_id=item.source_application_id,
            candidate_id=candidate.id,
        )
        resolved.append((item, candidate))

    existing_by_candidate = {
        membership.candidate_id: membership
        for membership in db.scalars(
            select(TalentPoolMembership)
            .where(
                TalentPoolMembership.group_id == group.id,
                TalentPoolMembership.candidate_id.in_(resolved_ids),
            )
            .with_for_update()
        ).all()
    }
    now = datetime.now(UTC)
    changed = False
    results: list[MembershipOperationResult] = []
    for requested, candidate in resolved:
        membership = existing_by_candidate.get(candidate.id)
        if membership is None:
            membership = TalentPoolMembership(
                id=uuid.uuid4(),
                group_id=group.id,
                candidate_id=candidate.id,
                source_application_id=requested.source_application_id,
                status="active",
                reason=reason,
                updated_by_id=actor.id,
            )
            db.add(membership)
            _append_event(
                db,
                membership=membership,
                idempotency_key=uuid.uuid5(
                    idempotency_key, f"add:{candidate.id}"
                ),
                action="added",
                from_status=None,
                to_status="active",
                reason=reason,
                candidate_id=candidate.id,
                source_application_id=requested.source_application_id,
                actor=actor,
            )
            operation_status = "added"
            changed = True
        elif membership.status == "active":
            operation_status = "already_active"
        else:
            membership.status = "active"
            membership.reason = reason
            membership.source_application_id = requested.source_application_id
            membership.joined_at = now
            membership.removed_at = None
            membership.version += 1
            membership.updated_by_id = actor.id
            _append_event(
                db,
                membership=membership,
                idempotency_key=uuid.uuid5(
                    idempotency_key, f"reactivate:{candidate.id}"
                ),
                action="added",
                from_status="removed",
                to_status="active",
                reason=reason,
                candidate_id=candidate.id,
                source_application_id=requested.source_application_id,
                actor=actor,
            )
            operation_status = "reactivated"
            changed = True
        results.append(
            MembershipOperationResult(
                requested_candidate_id=requested.candidate_id,
                candidate_id=candidate.id,
                membership_id=membership.id,
                status=operation_status,
            )
        )

    if changed:
        group.version += 1
    db.flush()
    _audit_membership_operation(
        db,
        action="talent_pool.members_added",
        group=group,
        idempotency_key=idempotency_key,
        fingerprint=request_fingerprint,
        reason=reason,
        items=results,
        actor=actor,
    )
    return MembershipOperationOutcome(
        group=group,
        group_version=group.version,
        items=tuple(results),
    )


def remove_memberships(
    db: Session,
    *,
    group_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
    reason: str,
    expected_group_version: int,
    idempotency_key: uuid.UUID,
    actor: User,
) -> MembershipOperationOutcome:
    group = _get_group(db, group_id, for_update=True)
    request_fingerprint = _fingerprint(
        {
            "candidate_ids": sorted(str(item) for item in candidate_ids),
            "reason": reason,
            "expected_group_version": expected_group_version,
        }
    )
    replay = _check_replay(
        _find_idempotent_audit(
            db,
            action="talent_pool.members_removed",
            group_id=group.id,
            idempotency_key=idempotency_key,
        ),
        fingerprint=request_fingerprint,
    )
    if replay is not None:
        return MembershipOperationOutcome(
            group=group,
            group_version=int(replay["group_version"]),
            items=_operation_items_from_audit(replay),
        )
    if group.version != expected_group_version:
        raise TalentPoolServiceError("人才分组版本已变化，请刷新后重试", status_code=409)

    resolved: list[tuple[uuid.UUID, Candidate]] = []
    resolved_ids: set[uuid.UUID] = set()
    for requested_id in candidate_ids:
        candidate = _resolve_candidate(db, requested_id)
        if candidate.id in resolved_ids:
            raise TalentPoolServiceError("候选人合并后在同一批次发生重复", status_code=422)
        resolved_ids.add(candidate.id)
        resolved.append((requested_id, candidate))

    existing_by_candidate = {
        membership.candidate_id: membership
        for membership in db.scalars(
            select(TalentPoolMembership)
            .where(
                TalentPoolMembership.group_id == group.id,
                TalentPoolMembership.candidate_id.in_(resolved_ids),
            )
            .with_for_update()
        ).all()
    }
    now = datetime.now(UTC)
    changed = False
    results: list[MembershipOperationResult] = []
    for requested_id, candidate in resolved:
        membership = existing_by_candidate.get(candidate.id)
        if membership is None:
            operation_status = "not_member"
        elif membership.status == "removed":
            operation_status = "already_removed"
        else:
            membership.status = "removed"
            membership.reason = reason
            membership.removed_at = now
            membership.version += 1
            membership.updated_by_id = actor.id
            _append_event(
                db,
                membership=membership,
                idempotency_key=uuid.uuid5(
                    idempotency_key, f"remove:{candidate.id}"
                ),
                action="removed",
                from_status="active",
                to_status="removed",
                reason=reason,
                candidate_id=candidate.id,
                source_application_id=membership.source_application_id,
                actor=actor,
            )
            operation_status = "removed"
            changed = True
        results.append(
            MembershipOperationResult(
                requested_candidate_id=requested_id,
                candidate_id=candidate.id,
                membership_id=membership.id if membership is not None else None,
                status=operation_status,
            )
        )

    if changed:
        group.version += 1
    db.flush()
    _audit_membership_operation(
        db,
        action="talent_pool.members_removed",
        group=group,
        idempotency_key=idempotency_key,
        fingerprint=request_fingerprint,
        reason=reason,
        items=results,
        actor=actor,
    )
    return MembershipOperationOutcome(
        group=group,
        group_version=group.version,
        items=tuple(results),
    )
