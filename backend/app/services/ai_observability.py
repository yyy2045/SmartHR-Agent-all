from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database import SessionLocal
from app.models import AiCallLog, AiTask, AiTaskEvent

SessionFactory = sessionmaker[Session]


def _now() -> datetime:
    return datetime.now(UTC)


def _task_by_celery_id(db: Session, celery_task_id: str | None) -> AiTask | None:
    if not celery_task_id:
        return None
    return db.scalar(select(AiTask).where(AiTask.celery_task_id == celery_task_id))


def record_task_started(
    *,
    celery_task_id: str,
    task_name: str,
    scenario: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    candidate_profile_id: uuid.UUID | None = None,
    attempt_count: int = 1,
    max_retries: int = 0,
    session_factory: Callable[[], Session] | SessionFactory = SessionLocal,
) -> uuid.UUID:
    with session_factory() as db:
        task = _task_by_celery_id(db, celery_task_id)
        if task is None:
            task = AiTask(
                celery_task_id=celery_task_id,
                task_name=task_name,
                scenario=scenario,
                resource_type=resource_type,
                resource_id=resource_id,
                job_id=job_id,
                batch_id=batch_id,
                document_id=document_id,
                application_id=application_id,
                candidate_profile_id=candidate_profile_id,
                max_retries=max_retries,
            )
            db.add(task)
        task.status = "running"
        task.attempt_count = max(task.attempt_count or 0, attempt_count)
        task.failure_code = None
        task.failure_message = None
        task.completed_at = None
        if task.started_at is None:
            task.started_at = _now()
        task.events.append(
            AiTaskEvent(
                event_type="started",
                status_after="running",
                message="任务开始执行",
            )
        )
        db.commit()
        return task.id


def record_task_finished(
    *,
    celery_task_id: str,
    succeeded: bool,
    failure_code: str | None = None,
    failure_message: str | None = None,
    session_factory: Callable[[], Session] | SessionFactory = SessionLocal,
) -> None:
    with session_factory() as db:
        task = _task_by_celery_id(db, celery_task_id)
        if task is None:
            return
        task.status = "succeeded" if succeeded else "failed"
        task.failure_code = None if succeeded else failure_code
        task.failure_message = None if succeeded else failure_message
        task.completed_at = _now()
        if task.started_at is not None:
            started_at = task.started_at
            completed_at = task.completed_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=UTC)
            task.duration_ms = max(
                0,
                int((completed_at - started_at).total_seconds() * 1000),
            )
        task.events.append(
            AiTaskEvent(
                event_type="succeeded" if succeeded else "failed",
                status_after=task.status,
                message="任务执行完成" if succeeded else (failure_message or "任务执行失败"),
            )
        )
        db.commit()


def record_ai_call(
    *,
    scenario: str,
    status: str,
    model_name: str | None = None,
    prompt_version: str | None = None,
    prompt_template_version_id: uuid.UUID | None = None,
    celery_task_id: str | None = None,
    retry_count: int = 0,
    duration_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    invoked_by_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    candidate_profile_id: uuid.UUID | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
    session_factory: Callable[[], Session] | SessionFactory = SessionLocal,
) -> uuid.UUID:
    with session_factory() as db:
        call = record_ai_call_in_session(
            db,
            scenario=scenario,
            status=status,
            model_name=model_name,
            prompt_version=prompt_version,
            prompt_template_version_id=prompt_template_version_id,
            celery_task_id=celery_task_id,
            retry_count=retry_count,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            invoked_by_id=invoked_by_id,
            resource_type=resource_type,
            resource_id=resource_id,
            job_id=job_id,
            batch_id=batch_id,
            document_id=document_id,
            application_id=application_id,
            candidate_profile_id=candidate_profile_id,
            failure_code=failure_code,
            failure_message=failure_message,
        )
        db.commit()
        return call.id


def record_ai_call_in_session(
    db: Session,
    *,
    scenario: str,
    status: str,
    model_name: str | None = None,
    prompt_version: str | None = None,
    prompt_template_version_id: uuid.UUID | None = None,
    celery_task_id: str | None = None,
    retry_count: int = 0,
    duration_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    invoked_by_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    candidate_profile_id: uuid.UUID | None = None,
    failure_code: str | None = None,
    failure_message: str | None = None,
) -> AiCallLog:
    task = _task_by_celery_id(db, celery_task_id)
    call = AiCallLog(
        task_id=task.id if task else None,
        scenario=scenario,
        status=status,
        model_name=model_name,
        prompt_version=prompt_version,
        prompt_template_version_id=prompt_template_version_id,
        retry_count=retry_count,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        invoked_by_id=invoked_by_id,
        resource_type=resource_type,
        resource_id=resource_id,
        job_id=job_id,
        batch_id=batch_id,
        document_id=document_id,
        application_id=application_id,
        candidate_profile_id=candidate_profile_id,
        failure_code=failure_code,
        failure_message=failure_message,
    )
    db.add(call)
    return call


def task_succeeded_from_result(result: dict[str, Any]) -> bool:
    return result.get("status") not in {"failed", "error"}
