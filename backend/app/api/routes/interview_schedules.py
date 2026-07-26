import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.api.routes.interview_plans import get_owned_plan_version
from app.api.routes.jobs import ensure_job_active, get_owned_job
from app.database import get_db
from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    Job,
    ResumeDocument,
    ScreeningBatch,
)
from app.schemas.interview_schedule import (
    InterviewRoundCancel,
    InterviewRoundReschedule,
    InterviewScheduleCreate,
    InterviewScheduleResponse,
)
from app.services.audit import record_audit

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def schedule_load_options() -> tuple[object, ...]:
    return (
        selectinload(CandidateInterviewSchedule.document),
        selectinload(CandidateInterviewSchedule.plan_version),
        selectinload(CandidateInterviewSchedule.rounds).selectinload(
            CandidateInterviewRound.plan_round
        ),
    )


def get_owned_document(
    db: Session,
    *,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> ResumeDocument:
    document = db.scalar(
        select(ResumeDocument)
        .join(ScreeningBatch)
        .join(Job)
        .where(
            ResumeDocument.id == document_id,
            ScreeningBatch.job_id == job_id,
            Job.owner_id == owner_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人简历不存在")
    return document


def get_owned_schedule(
    db: Session,
    *,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    owner_id: uuid.UUID,
    for_update: bool = False,
) -> CandidateInterviewSchedule:
    statement = (
        select(CandidateInterviewSchedule)
        .join(ResumeDocument)
        .join(ScreeningBatch)
        .join(Job)
        .where(
            CandidateInterviewSchedule.document_id == document_id,
            ScreeningBatch.job_id == job_id,
            Job.owner_id == owner_id,
        )
        .options(*schedule_load_options())
    )
    if for_update:
        statement = statement.with_for_update()
    schedule = db.scalar(statement)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人面试安排不存在")
    return schedule


def get_schedule_round(
    schedule: CandidateInterviewSchedule,
    round_id: uuid.UUID,
) -> CandidateInterviewRound:
    round_item = next((item for item in schedule.rounds if item.id == round_id), None)
    if round_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人面试轮次不存在")
    return round_item


def refresh_schedule(
    db: Session,
    schedule_id: uuid.UUID,
) -> CandidateInterviewSchedule:
    schedule = db.scalar(
        select(CandidateInterviewSchedule)
        .where(CandidateInterviewSchedule.id == schedule_id)
        .options(*schedule_load_options())
    )
    if schedule is None:
        raise RuntimeError("候选人面试安排保存后无法读取")
    return schedule


def update_schedule_status(schedule: CandidateInterviewSchedule) -> None:
    cancelled_count = sum(item.status == "cancelled" for item in schedule.rounds)
    if cancelled_count == len(schedule.rounds):
        schedule.status = "cancelled"
    elif cancelled_count:
        schedule.status = "partially_cancelled"
    else:
        schedule.status = "scheduled"


@router.get(
    "/{job_id}/candidate-processes/{document_id}/interview-schedule",
    response_model=InterviewScheduleResponse,
)
def get_candidate_interview_schedule(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateInterviewSchedule:
    get_owned_job(db, job_id, current_user.id)
    return get_owned_schedule(
        db,
        job_id=job_id,
        document_id=document_id,
        owner_id=current_user.id,
    )


@router.post(
    "/{job_id}/candidate-processes/{document_id}/interview-schedule",
    response_model=InterviewScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate_interview_schedule(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: InterviewScheduleCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateInterviewSchedule:
    job = get_owned_job(db, job_id, current_user.id)
    ensure_job_active(job)
    document = get_owned_document(
        db,
        job_id=job_id,
        document_id=document_id,
        owner_id=current_user.id,
    )
    existing = db.scalar(
        select(CandidateInterviewSchedule.id).where(
            CandidateInterviewSchedule.document_id == document_id
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="候选人已有面试安排")

    plan_version = get_owned_plan_version(
        db,
        job_id,
        payload.plan_version_id,
        current_user.id,
    )
    if plan_version.status != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="只能使用已确认的面试方案版本",
        )
    expected_round_ids = {item.id for item in plan_version.rounds}
    supplied_round_ids = {item.plan_round_id for item in payload.rounds}
    if supplied_round_ids != expected_round_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="必须完整配置所选面试方案的全部轮次",
        )
    arrangement_by_round = {item.plan_round_id: item for item in payload.rounds}
    schedule = CandidateInterviewSchedule(
        document_id=document.id,
        plan_version_id=plan_version.id,
        status="scheduled",
        created_by_id=current_user.id,
        rounds=[
            CandidateInterviewRound(
                plan_round_id=plan_round.id,
                sort_order=plan_round.sort_order,
                scheduled_start_at=arrangement_by_round[plan_round.id].scheduled_start_at,
                interview_method=arrangement_by_round[plan_round.id].interview_method,
                location=arrangement_by_round[plan_round.id].location,
                meeting_url=arrangement_by_round[plan_round.id].meeting_url,
                status="scheduled",
                updated_by_id=current_user.id,
            )
            for plan_round in plan_version.rounds
        ],
    )
    db.add(schedule)
    db.flush()
    record_audit(
        db,
        actor=current_user,
        action="interview_schedule.created",
        target_type="candidate_interview_schedule",
        target_id=schedule.id,
        job_id=job_id,
        batch_id=document.batch_id,
        result="success",
        details={
            "document_id": str(document_id),
            "plan_version_id": str(plan_version.id),
            "plan_version_number": plan_version.version_number,
            "round_count": len(schedule.rounds),
        },
    )
    schedule_id = schedule.id
    db.commit()
    return refresh_schedule(db, schedule_id)


@router.patch(
    "/{job_id}/candidate-processes/{document_id}/interview-schedule/rounds/{round_id}",
    response_model=InterviewScheduleResponse,
)
def reschedule_candidate_interview_round(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    round_id: uuid.UUID,
    payload: InterviewRoundReschedule,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateInterviewSchedule:
    job = get_owned_job(db, job_id, current_user.id)
    ensure_job_active(job)
    schedule = get_owned_schedule(
        db,
        job_id=job_id,
        document_id=document_id,
        owner_id=current_user.id,
        for_update=True,
    )
    round_item = get_schedule_round(schedule, round_id)
    if round_item.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已取消轮次不能改期")
    previous_start_at = round_item.scheduled_start_at
    previous_method = round_item.interview_method
    round_item.scheduled_start_at = payload.scheduled_start_at
    round_item.interview_method = payload.interview_method
    round_item.location = payload.location
    round_item.meeting_url = payload.meeting_url
    round_item.status = "rescheduled"
    round_item.reschedule_count += 1
    round_item.last_change_reason = payload.reason
    round_item.updated_by_id = current_user.id
    schedule.updated_at = datetime.now(UTC)
    record_audit(
        db,
        actor=current_user,
        action="interview_schedule.round_rescheduled",
        target_type="candidate_interview_round",
        target_id=round_item.id,
        job_id=job_id,
        batch_id=schedule.document.batch_id,
        result="success",
        details={
            "schedule_id": str(schedule.id),
            "document_id": str(document_id),
            "plan_round_id": str(round_item.plan_round_id),
            "reason": payload.reason,
            "previous_start_at": previous_start_at.isoformat(),
            "scheduled_start_at": payload.scheduled_start_at.isoformat(),
            "previous_method": previous_method,
            "interview_method": payload.interview_method,
        },
    )
    schedule_id = schedule.id
    db.commit()
    return refresh_schedule(db, schedule_id)


@router.post(
    "/{job_id}/candidate-processes/{document_id}/interview-schedule/rounds/{round_id}/cancel",
    response_model=InterviewScheduleResponse,
)
def cancel_candidate_interview_round(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    round_id: uuid.UUID,
    payload: InterviewRoundCancel,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateInterviewSchedule:
    job = get_owned_job(db, job_id, current_user.id)
    ensure_job_active(job)
    schedule = get_owned_schedule(
        db,
        job_id=job_id,
        document_id=document_id,
        owner_id=current_user.id,
        for_update=True,
    )
    round_item = get_schedule_round(schedule, round_id)
    if round_item.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="面试轮次已取消")
    cancelled_at = datetime.now(UTC)
    round_item.status = "cancelled"
    round_item.last_change_reason = payload.reason
    round_item.cancelled_at = cancelled_at
    round_item.updated_by_id = current_user.id
    update_schedule_status(schedule)
    schedule.updated_at = cancelled_at
    record_audit(
        db,
        actor=current_user,
        action="interview_schedule.round_cancelled",
        target_type="candidate_interview_round",
        target_id=round_item.id,
        job_id=job_id,
        batch_id=schedule.document.batch_id,
        result="success",
        details={
            "schedule_id": str(schedule.id),
            "document_id": str(document_id),
            "plan_round_id": str(round_item.plan_round_id),
            "reason": payload.reason,
            "scheduled_start_at": round_item.scheduled_start_at.isoformat(),
            "schedule_status": schedule.status,
        },
    )
    schedule_id = schedule.id
    db.commit()
    return refresh_schedule(db, schedule_id)
