import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import Job, User
from app.schemas.workbench import (
    WorkbenchItemType,
    WorkbenchListResponse,
    WorkbenchPriority,
    WorkbenchPriorityCount,
    WorkbenchSection,
    WorkbenchSectionCount,
    WorkbenchSummaryResponse,
    WorkbenchTypeCount,
)
from app.services.workbench import collect_workbench

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _visible_job_clause(user: User):
    if user.has_role("administrator", "approver"):
        return Job.id.is_not(None)
    clauses = []
    if user.has_role("recruiter"):
        clauses.append(Job.owner_id == user.id)
    if user.has_role("hiring_manager"):
        clauses.append(Job.hiring_manager_id == user.id)
    return or_(*clauses) if clauses else false()


def _ensure_visible_job(db: Session, user: User, job_id: uuid.UUID) -> None:
    if db.scalar(select(Job.id).where(Job.id == job_id, _visible_job_clause(user))) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")


@router.get("/summary", response_model=WorkbenchSummaryResponse)
def get_workbench_summary(
    current_user: CurrentUser,
    db: DbSession,
) -> WorkbenchSummaryResponse:
    as_of = datetime.now(UTC)
    collection = collect_workbench(db, current_user, as_of=as_of)
    section_counts = Counter[str]()
    priority_counts = Counter[str]()
    type_counts = Counter[str]()
    for item in collection.items:
        section_counts[item.section] += item.count
        priority_counts[item.priority] += item.count
        type_counts[item.item_type] += item.count
    return WorkbenchSummaryResponse(
        as_of=as_of,
        total_count=sum(section_counts.values()),
        action_required_count=section_counts["action_required"],
        sections=[
            WorkbenchSectionCount(section=section, count=section_counts[section])
            for section in ("action_required", "waiting_external", "risk_failure")
        ],
        priorities=[
            WorkbenchPriorityCount(priority=priority, count=priority_counts[priority])
            for priority in ("urgent", "high", "normal")
        ],
        types=[
            WorkbenchTypeCount(item_type=item_type, count=count)
            for item_type, count in sorted(type_counts.items())
        ],
        partial=bool(collection.failed_sources),
        failed_sources=list(collection.failed_sources),
    )


@router.get("/items", response_model=WorkbenchListResponse)
def list_workbench_items(
    current_user: CurrentUser,
    db: DbSession,
    section: WorkbenchSection | None = None,
    item_type: WorkbenchItemType | None = None,
    priority: WorkbenchPriority | None = None,
    job_id: uuid.UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> WorkbenchListResponse:
    if job_id is not None:
        _ensure_visible_job(db, current_user, job_id)
    as_of = datetime.now(UTC)
    collection = collect_workbench(db, current_user, as_of=as_of)
    items = [
        item
        for item in collection.items
        if (section is None or item.section == section)
        and (item_type is None or item.item_type == item_type)
        and (priority is None or item.priority == priority)
        and (job_id is None or item.job_id == job_id)
    ]
    total = len(items)
    offset = (page - 1) * page_size
    return WorkbenchListResponse(
        as_of=as_of,
        items=items[offset : offset + page_size],
        total=total,
        page=page,
        page_size=page_size,
        partial=bool(collection.failed_sources),
        failed_sources=list(collection.failed_sources),
    )
