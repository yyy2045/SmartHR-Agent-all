from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditLog, MessageTemplate, MessageTemplateVersion, User
from app.services.audit import record_audit


class MessageTemplateServiceError(Exception):
    def __init__(self, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _fingerprint(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _find_idempotent_audit(
    db: Session,
    *,
    action: str,
    template_id: uuid.UUID,
    idempotency_key: uuid.UUID,
) -> AuditLog | None:
    logs = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.action == action,
            AuditLog.target_type == "message_template",
            AuditLog.target_id == template_id,
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
        raise MessageTemplateServiceError("幂等键已被不同请求使用", status_code=409)
    return details


def get_template(
    db: Session,
    template_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> MessageTemplate:
    statement = (
        select(MessageTemplate)
        .where(MessageTemplate.id == template_id)
        .options(selectinload(MessageTemplate.versions))
    )
    if for_update:
        statement = statement.with_for_update()
    template = db.scalar(statement)
    if template is None:
        raise MessageTemplateServiceError("沟通模板不存在", status_code=404)
    return template


def create_template(
    db: Session,
    *,
    template_type: str,
    name: str,
    subject: str,
    body: str,
    variables: list[str],
    idempotency_key: uuid.UUID,
    actor: User,
) -> MessageTemplate:
    template_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"message-template:{actor.id}:{idempotency_key}",
    )
    request_fingerprint = _fingerprint(
        {
            "template_type": template_type,
            "name": name,
            "subject": subject,
            "body": body,
            "variables": variables,
        }
    )
    existing = db.get(MessageTemplate, template_id)
    if existing is not None:
        replay = _check_replay(
            _find_idempotent_audit(
                db,
                action="message_template.created",
                template_id=template_id,
                idempotency_key=idempotency_key,
            ),
            fingerprint=request_fingerprint,
        )
        if replay is None:
            raise MessageTemplateServiceError("沟通模板创建标识冲突", status_code=409)
        return get_template(db, template_id)

    template = MessageTemplate(
        id=template_id,
        template_type=template_type,
        name=name,
        status="active",
        current_version_number=1,
        resource_version=1,
        created_by_id=actor.id,
        created_by_username=actor.username,
        created_by_display_name=actor.display_name,
    )
    version = MessageTemplateVersion(
        id=uuid.uuid5(template_id, f"version:{idempotency_key}"),
        version_number=1,
        idempotency_key=idempotency_key,
        subject=subject,
        body=body,
        variables=variables,
        created_by_id=actor.id,
        created_by_username=actor.username,
        created_by_display_name=actor.display_name,
    )
    template.versions.append(version)
    db.add(template)
    db.flush()
    record_audit(
        db,
        action="message_template.created",
        target_type="message_template",
        target_id=template.id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "fingerprint": request_fingerprint,
            "template_type": template_type,
            "version_number": 1,
        },
    )
    return template


def create_template_version(
    db: Session,
    *,
    template_id: uuid.UUID,
    subject: str,
    body: str,
    variables: list[str],
    expected_version: int,
    idempotency_key: uuid.UUID,
    actor: User,
) -> MessageTemplate:
    template = get_template(db, template_id, for_update=True)
    request_fingerprint = _fingerprint(
        {
            "subject": subject,
            "body": body,
            "variables": variables,
            "expected_version": expected_version,
        }
    )
    replay = _check_replay(
        _find_idempotent_audit(
            db,
            action="message_template.version_created",
            template_id=template.id,
            idempotency_key=idempotency_key,
        ),
        fingerprint=request_fingerprint,
    )
    if replay is not None:
        return template
    if template.resource_version != expected_version:
        raise MessageTemplateServiceError("沟通模板版本已变化，请刷新后重试", status_code=409)

    source_version = template.current_version
    version_number = template.current_version_number + 1
    template.versions.append(
        MessageTemplateVersion(
            id=uuid.uuid5(template.id, f"version:{idempotency_key}"),
            version_number=version_number,
            idempotency_key=idempotency_key,
            source_version_id=source_version.id,
            subject=subject,
            body=body,
            variables=variables,
            created_by_id=actor.id,
            created_by_username=actor.username,
            created_by_display_name=actor.display_name,
        )
    )
    template.current_version_number = version_number
    template.resource_version += 1
    db.flush()
    record_audit(
        db,
        action="message_template.version_created",
        target_type="message_template",
        target_id=template.id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "fingerprint": request_fingerprint,
            "source_version_number": source_version.version_number,
            "version_number": version_number,
            "resource_version": template.resource_version,
        },
    )
    return template


def set_template_status(
    db: Session,
    *,
    template_id: uuid.UUID,
    target_status: str,
    expected_version: int,
    idempotency_key: uuid.UUID,
    actor: User,
) -> MessageTemplate:
    template = get_template(db, template_id, for_update=True)
    action = (
        "message_template.activated"
        if target_status == "active"
        else "message_template.deactivated"
    )
    request_fingerprint = _fingerprint(
        {"target_status": target_status, "expected_version": expected_version}
    )
    replay = _check_replay(
        _find_idempotent_audit(
            db,
            action=action,
            template_id=template.id,
            idempotency_key=idempotency_key,
        ),
        fingerprint=request_fingerprint,
    )
    if replay is not None:
        return template
    if template.resource_version != expected_version:
        raise MessageTemplateServiceError("沟通模板版本已变化，请刷新后重试", status_code=409)
    if template.status == target_status:
        detail = "沟通模板已经启用" if target_status == "active" else "沟通模板已经停用"
        raise MessageTemplateServiceError(detail, status_code=409)

    previous_status = template.status
    template.status = target_status
    template.resource_version += 1
    db.flush()
    record_audit(
        db,
        action=action,
        target_type="message_template",
        target_id=template.id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "fingerprint": request_fingerprint,
            "previous_status": previous_status,
            "status": target_status,
            "resource_version": template.resource_version,
        },
    )
    return template
