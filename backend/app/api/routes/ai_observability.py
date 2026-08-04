from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import AiCallLog, AiTask, User
from app.schemas.ai_observability import (
    AiCallLogListResponse,
    AiCallLogRecord,
    AiObservabilityCount,
    AiObservabilitySummaryResponse,
    AiTaskListResponse,
    AiTaskRecord,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

TaskStatusFilter = Literal["queued", "running", "succeeded", "failed", "retrying", "cancelled"]
CallStatusFilter = Literal["succeeded", "failed"]


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _is_administrator(user: User) -> bool:
    return user.has_role("administrator")


def _task_scope(user: User) -> list[object]:
    if _is_administrator(user):
        return []
    return [AiTask.created_by_id == user.id]


def _call_scope(user: User) -> list[object]:
    if _is_administrator(user):
        return []
    return [AiCallLog.invoked_by_id == user.id]


def _count_rows(rows: list[tuple[str, int]]) -> list[AiObservabilityCount]:
    return [AiObservabilityCount(key=key, count=count) for key, count in rows]


def _limited_failure_message(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) <= 500:
        return value
    return f"{value[:497]}..."


def _task_response(task: AiTask) -> AiTaskRecord:
    return AiTaskRecord(
        id=task.id,
        celery_task_id=task.celery_task_id,
        task_name=task.task_name,
        scenario=task.scenario,
        status=task.status,
        attempt_count=task.attempt_count,
        max_retries=task.max_retries,
        resource_type=task.resource_type,
        resource_id=task.resource_id,
        job_id=task.job_id,
        batch_id=task.batch_id,
        document_id=task.document_id,
        application_id=task.application_id,
        candidate_profile_id=task.candidate_profile_id,
        failure_code=task.failure_code,
        failure_message=_limited_failure_message(task.failure_message),
        duration_ms=task.duration_ms,
        started_at=_ensure_utc(task.started_at),
        completed_at=_ensure_utc(task.completed_at),
        created_at=_ensure_utc(task.created_at),
    )


def _call_response(call: AiCallLog) -> AiCallLogRecord:
    return AiCallLogRecord(
        id=call.id,
        task_id=call.task_id,
        scenario=call.scenario,
        status=call.status,
        model_name=call.model_name,
        prompt_version=call.prompt_version,
        prompt_template_version_id=call.prompt_template_version_id,
        provider=call.provider,
        retry_count=call.retry_count,
        duration_ms=call.duration_ms,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        total_tokens=call.total_tokens,
        resource_type=call.resource_type,
        resource_id=call.resource_id,
        job_id=call.job_id,
        batch_id=call.batch_id,
        document_id=call.document_id,
        application_id=call.application_id,
        candidate_profile_id=call.candidate_profile_id,
        failure_code=call.failure_code,
        failure_message=_limited_failure_message(call.failure_message),
        created_at=_ensure_utc(call.created_at),
    )


@router.get("/summary", response_model=AiObservabilitySummaryResponse)
def get_ai_observability_summary(
    current_user: CurrentUser,
    db: DbSession,
) -> AiObservabilitySummaryResponse:
    task_filters = _task_scope(current_user)
    call_filters = _call_scope(current_user)

    task_total = db.scalar(select(func.count(AiTask.id)).where(*task_filters)) or 0
    call_total = db.scalar(select(func.count(AiCallLog.id)).where(*call_filters)) or 0
    failed_task_count = (
        db.scalar(select(func.count(AiTask.id)).where(*task_filters, AiTask.status == "failed"))
        or 0
    )
    failed_call_count = (
        db.scalar(
            select(func.count(AiCallLog.id)).where(*call_filters, AiCallLog.status == "failed")
        )
        or 0
    )
    total_input_tokens = (
        db.scalar(select(func.coalesce(func.sum(AiCallLog.input_tokens), 0)).where(*call_filters))
        or 0
    )
    total_output_tokens = (
        db.scalar(select(func.coalesce(func.sum(AiCallLog.output_tokens), 0)).where(*call_filters))
        or 0
    )
    total_tokens = (
        db.scalar(select(func.coalesce(func.sum(AiCallLog.total_tokens), 0)).where(*call_filters))
        or 0
    )
    avg_task_duration = db.scalar(select(func.avg(AiTask.duration_ms)).where(*task_filters))
    avg_call_duration = db.scalar(select(func.avg(AiCallLog.duration_ms)).where(*call_filters))

    task_status_rows = list(
        db.execute(
            select(AiTask.status, func.count(AiTask.id))
            .where(*task_filters)
            .group_by(AiTask.status)
            .order_by(AiTask.status)
        )
    )
    call_status_rows = list(
        db.execute(
            select(AiCallLog.status, func.count(AiCallLog.id))
            .where(*call_filters)
            .group_by(AiCallLog.status)
            .order_by(AiCallLog.status)
        )
    )
    call_scenario_rows = list(
        db.execute(
            select(AiCallLog.scenario, func.count(AiCallLog.id))
            .where(*call_filters)
            .group_by(AiCallLog.scenario)
            .order_by(func.count(AiCallLog.id).desc(), AiCallLog.scenario)
            .limit(10)
        )
    )

    return AiObservabilitySummaryResponse(
        task_total=task_total,
        call_total=call_total,
        failed_task_count=failed_task_count,
        failed_call_count=failed_call_count,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_tokens=total_tokens,
        avg_task_duration_ms=int(avg_task_duration) if avg_task_duration is not None else None,
        avg_call_duration_ms=int(avg_call_duration) if avg_call_duration is not None else None,
        task_status_counts=_count_rows(task_status_rows),
        call_status_counts=_count_rows(call_status_rows),
        call_scenario_counts=_count_rows(call_scenario_rows),
    )


@router.get("/tasks", response_model=AiTaskListResponse)
def list_ai_tasks(
    current_user: CurrentUser,
    db: DbSession,
    status: Annotated[TaskStatusFilter | None, Query()] = None,
    scenario: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AiTaskListResponse:
    filters = _task_scope(current_user)
    if status:
        filters.append(AiTask.status == status)
    if scenario:
        filters.append(AiTask.scenario == scenario.strip())

    total = db.scalar(select(func.count(AiTask.id)).where(*filters)) or 0
    items = list(
        db.scalars(
            select(AiTask)
            .where(*filters)
            .order_by(AiTask.created_at.desc(), AiTask.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return AiTaskListResponse(
        items=[_task_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/calls", response_model=AiCallLogListResponse)
def list_ai_calls(
    current_user: CurrentUser,
    db: DbSession,
    status: Annotated[CallStatusFilter | None, Query()] = None,
    scenario: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AiCallLogListResponse:
    filters = _call_scope(current_user)
    if status:
        filters.append(AiCallLog.status == status)
    if scenario:
        filters.append(AiCallLog.scenario == scenario.strip())

    total = db.scalar(select(func.count(AiCallLog.id)).where(*filters)) or 0
    items = list(
        db.scalars(
            select(AiCallLog)
            .where(*filters)
            .order_by(AiCallLog.created_at.desc(), AiCallLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return AiCallLogListResponse(
        items=[_call_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
