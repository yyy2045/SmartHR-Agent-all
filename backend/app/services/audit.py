import uuid
from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record_audit(
    db: Session,
    *,
    action: str,
    target_type: str,
    result: str,
    actor: User | None = None,
    actor_username: str | None = None,
    target_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    details: Mapping[str, object] | None = None,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=actor.id if actor is not None else None,
        actor_username=(actor.username if actor is not None else actor_username),
        action=action,
        target_type=target_type,
        target_id=target_id,
        job_id=job_id,
        batch_id=batch_id,
        result=result,
        details=dict(details or {}),
    )
    db.add(log)
    return log
