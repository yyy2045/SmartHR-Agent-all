import re
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    CandidateProcess,
    CandidateProcessEvent,
    JobApplication,
    RecruiterDecision,
    ResumeDocument,
    ResumeRedaction,
    ResumeTextSegment,
    ScreeningBatch,
    ScreeningResult,
    User,
)
from app.schemas.candidate_process import (
    CandidateProcessCardResponse,
    CandidateProcessTimelineEventResponse,
    CandidateStage,
    CandidateStageUpdate,
    CandidateStageUpdateResponse,
    InterviewEvaluationProgressResponse,
)
from app.schemas.screening import AIGroup, ManualDecision
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

STAGE_ORDER: tuple[CandidateStage, ...] = (
    "unprocessed",
    "pending",
    "shortlisted",
    "to_contact",
    "contacted",
    "to_interview",
    "completed",
    "rejected",
)
STAGE_RANK = {stage: index for index, stage in enumerate(STAGE_ORDER)}
ALLOWED_TRANSITIONS: dict[CandidateStage, set[CandidateStage]] = {
    "unprocessed": {"pending", "shortlisted", "rejected"},
    "pending": {"shortlisted", "rejected"},
    "shortlisted": {"pending", "to_contact", "rejected"},
    "to_contact": {"shortlisted", "contacted", "rejected"},
    "contacted": {"to_contact", "to_interview", "rejected"},
    "to_interview": {"contacted", "completed", "rejected"},
    "completed": set(),
    "rejected": set(),
}


def _result_options() -> tuple[object, ...]:
    return (
        selectinload(ScreeningResult.document).selectinload(ResumeDocument.batch),
        selectinload(ScreeningResult.document)
        .selectinload(ResumeDocument.application)
        .selectinload(JobApplication.process)
        .selectinload(CandidateProcess.events),
        selectinload(ScreeningResult.document)
        .selectinload(ResumeDocument.application)
        .selectinload(JobApplication.interview_schedule)
        .selectinload(CandidateInterviewSchedule.rounds)
        .selectinload(CandidateInterviewRound.plan_round),
        selectinload(ScreeningResult.document)
        .selectinload(ResumeDocument.application)
        .selectinload(JobApplication.interview_schedule)
        .selectinload(CandidateInterviewSchedule.rounds)
        .selectinload(CandidateInterviewRound.evaluation),
        selectinload(ScreeningResult.candidate_profile),
        selectinload(ScreeningResult.criteria_version),
        selectinload(ScreeningResult.recruiter_decisions).selectinload(
            RecruiterDecision.operator
        ),
    )


def _interview_evaluation_progress(
    schedule: CandidateInterviewSchedule | None,
) -> InterviewEvaluationProgressResponse | None:
    if schedule is None:
        return None
    ordered_rounds = sorted(schedule.rounds, key=lambda item: item.sort_order)
    active_rounds = [item for item in ordered_rounds if item.status != "cancelled"]
    cancelled_count = len(ordered_rounds) - len(active_rounds)
    submitted = [
        item
        for item in active_rounds
        if item.evaluation is not None and item.evaluation.status == "submitted"
    ]
    drafts = [
        item
        for item in active_rounds
        if item.evaluation is not None and item.evaluation.status == "draft"
    ]
    pending = [item for item in active_rounds if item.evaluation is None]

    if not active_rounds:
        progress_status = "cancelled"
    elif len(submitted) == len(active_rounds):
        progress_status = "completed"
    elif submitted or drafts:
        progress_status = "in_progress"
    else:
        progress_status = "not_started"

    if drafts:
        action_round = drafts[0]
    elif pending:
        action_round = pending[0]
    elif submitted:
        action_round = submitted[0]
    else:
        action_round = None
    action_status = None
    if action_round is not None:
        action_status = (
            action_round.evaluation.status
            if action_round.evaluation is not None
            else "not_started"
        )
    return InterviewEvaluationProgressResponse(
        status=progress_status,
        total_rounds=len(active_rounds),
        submitted_count=len(submitted),
        draft_count=len(drafts),
        pending_count=len(pending),
        cancelled_count=cancelled_count,
        action_round_id=action_round.id if action_round is not None else None,
        action_round_name=action_round.name if action_round is not None else None,
        action_evaluation_status=action_status,
    )


def _latest_document_decision(results: list[ScreeningResult]) -> RecruiterDecision | None:
    decisions = [decision for item in results for decision in item.recruiter_decisions]
    return max(decisions, key=lambda item: item.created_at) if decisions else None


def _manual_decision(
    results: list[ScreeningResult],
    process: CandidateProcess | None,
) -> ManualDecision:
    if process is not None:
        if process.current_stage == "rejected":
            return "rejected"
        if process.current_stage in {"pending", "shortlisted"}:
            return process.current_stage  # type: ignore[return-value]
        if process.current_stage in {"to_contact", "contacted", "to_interview", "completed"}:
            return "shortlisted"
    latest = _latest_document_decision(results)
    return latest.decision if latest is not None else "unprocessed"  # type: ignore[return-value]


def _current_stage(
    results: list[ScreeningResult],
    process: CandidateProcess | None,
) -> CandidateStage:
    if process is not None:
        return process.current_stage  # type: ignore[return-value]
    return _manual_decision(results, None)


def _stage_entered_at(
    result: ScreeningResult,
    results: list[ScreeningResult],
    process: CandidateProcess | None,
) -> datetime:
    if process is not None:
        return process.stage_entered_at
    latest = _latest_document_decision(results)
    return latest.created_at if latest is not None else result.completed_at or result.created_at


def _profile_skills(result: ScreeningResult) -> list[str]:
    if result.candidate_profile is None:
        return []
    skills: list[str] = []
    for item in result.candidate_profile.skills:
        name = item.get("name") if isinstance(item, dict) else None
        if isinstance(name, str) and name.strip() and name.strip() not in skills:
            skills.append(name.strip())
        if len(skills) == 5:
            break
    return skills


def _phones_by_document(
    db: Session,
    document_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    if not document_ids:
        return {}
    rows = db.execute(
        select(ResumeTextSegment.document_id, ResumeRedaction.original_text)
        .join(ResumeRedaction, ResumeRedaction.segment_id == ResumeTextSegment.id)
        .where(
            ResumeTextSegment.document_id.in_(document_ids),
            ResumeRedaction.entity_type == "phone",
        )
        .order_by(
            ResumeTextSegment.document_id,
            ResumeTextSegment.sort_order,
            ResumeRedaction.start_offset,
        )
    )
    phones: dict[uuid.UUID, str] = {}
    for document_id, original_text in rows:
        phone = _valid_display_phone(original_text)
        if phone is not None:
            phones.setdefault(document_id, phone)
    return phones


def _valid_display_phone(value: str) -> str | None:
    phone = value.strip()
    compact = re.sub(r"\D", "", phone)
    if re.fullmatch(r"1[3-9]\d{9}", compact):
        return phone
    if phone.startswith("+") and 8 <= len(compact) <= 15:
        return phone
    if re.fullmatch(r"0\d{2,3}[- ]?\d{7,8}", phone):
        return phone
    return None


def _latest_results_by_document(
    results: list[ScreeningResult],
) -> list[tuple[ScreeningResult, list[ScreeningResult]]]:
    grouped: dict[uuid.UUID, list[ScreeningResult]] = {}
    for item in results:
        grouped.setdefault(item.document_id, []).append(item)
    latest: list[tuple[ScreeningResult, list[ScreeningResult]]] = []
    for document_results in grouped.values():
        selected = max(
            document_results,
            key=lambda item: (
                item.created_at,
                item.criteria_version.version_number,
                item.analysis_version,
            ),
        )
        latest.append((selected, document_results))
    return latest


def _get_owned_document(
    db: Session,
    *,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
    for_update: bool = False,
) -> ResumeDocument:
    job = get_visible_job(db, job_id, user)
    if for_update:
        ensure_job_writable(job, user)
    statement = (
        select(ResumeDocument)
        .join(ScreeningBatch)
        .where(
            ResumeDocument.id == document_id,
            ScreeningBatch.job_id == job_id,
        )
        .options(
            selectinload(ResumeDocument.batch),
            selectinload(ResumeDocument.application)
            .selectinload(JobApplication.process)
            .selectinload(CandidateProcess.events)
            .selectinload(CandidateProcessEvent.operator),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    document = db.scalar(statement)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人简历不存在")
    return document


def _completed_document_results(db: Session, document_id: uuid.UUID) -> list[ScreeningResult]:
    return list(
        db.scalars(
            select(ScreeningResult)
            .where(
                ScreeningResult.document_id == document_id,
                ScreeningResult.status == "completed",
            )
            .options(*_result_options())
        )
        .unique()
        .all()
    )


@router.get(
    "/{job_id}/candidate-processes",
    response_model=list[CandidateProcessCardResponse],
)
def list_candidate_processes(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    batch_id: uuid.UUID | None = None,
    stage: CandidateStage | None = None,
    ai_group: AIGroup | None = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> list[CandidateProcessCardResponse]:
    job = get_visible_job(db, job_id, current_user)
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="最低分不能高于最高分",
        )

    results = list(
        db.scalars(
            select(ScreeningResult)
            .join(ResumeDocument)
            .join(ScreeningBatch)
            .where(
                ScreeningBatch.job_id == job_id,
                ScreeningResult.status == "completed",
            )
            .options(*_result_options())
        )
        .unique()
        .all()
    )
    latest_results = _latest_results_by_document(results)
    phones_by_document = (
        _phones_by_document(
            db,
            [result.document_id for result, _ in latest_results],
        )
        if current_user.has_role("administrator") or job.owner_id == current_user.id
        else {}
    )
    cards: list[CandidateProcessCardResponse] = []
    normalized_query = query.strip().lower() if query else None
    for result, document_results in latest_results:
        if result.ai_group is None or result.total_score is None:
            continue
        application = result.document.application
        if application is None:
            continue
        process = application.process
        current_stage = _current_stage(document_results, process)
        score = float(result.total_score)
        skills = _profile_skills(result)
        if batch_id is not None and result.document.batch_id != batch_id:
            continue
        if stage is not None and current_stage != stage:
            continue
        if ai_group is not None and result.ai_group != ai_group:
            continue
        if min_score is not None and score < min_score:
            continue
        if max_score is not None and score > max_score:
            continue
        if normalized_query is not None:
            searchable = " ".join(
                [
                    result.document.candidate_code,
                    result.document.original_filename,
                    result.document.batch.name,
                    *skills,
                ]
            ).lower()
            if normalized_query not in searchable:
                continue
        cards.append(
            CandidateProcessCardResponse(
                process_id=process.id if process is not None else None,
                application_id=application.id,
                screening_result_id=result.id,
                batch_id=result.document.batch_id,
                batch_name=result.document.batch.name,
                document_id=result.document_id,
                candidate_code=result.document.candidate_code,
                original_filename=result.document.original_filename,
                phone=phones_by_document.get(result.document_id),
                ai_group=result.ai_group,
                total_score=score,
                current_decision=_manual_decision(document_results, process),
                current_stage=current_stage,
                stage_entered_at=_stage_entered_at(result, document_results, process),
                skills=skills,
                analysis_created_at=result.created_at,
                interview_evaluation=_interview_evaluation_progress(
                    application.interview_schedule
                ),
            )
        )
    cards.sort(
        key=lambda item: (
            STAGE_RANK[item.current_stage],
            -item.total_score,
            item.candidate_code,
        )
    )
    return cards


@router.post(
    "/{job_id}/candidate-processes/{document_id}/stage",
    response_model=CandidateStageUpdateResponse,
)
def update_candidate_stage(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: CandidateStageUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateStageUpdateResponse:
    document = _get_owned_document(
        db,
        job_id=job_id,
        document_id=document_id,
        user=current_user,
        for_update=True,
    )
    document_results = _completed_document_results(db, document_id)
    if not document_results:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只有已完成 AI 初筛的候选人才能进入流程看板",
        )
    latest_result = max(
        document_results,
        key=lambda item: (
            item.created_at,
            item.criteria_version.version_number,
            item.analysis_version,
        ),
    )
    application = document.application
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="候选人简历尚未建立职位应聘记录",
        )
    process = application.process
    previous_stage = _current_stage(document_results, process)
    if previous_stage != payload.expected_stage:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="候选人阶段已发生变化，请刷新看板后重试",
        )
    if payload.target_stage not in ALLOWED_TRANSITIONS[previous_stage]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="不允许从当前阶段直接变更到目标阶段",
        )
    is_backward = STAGE_RANK[payload.target_stage] < STAGE_RANK[previous_stage]
    if (payload.target_stage == "rejected" or is_backward) and not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="淘汰或退回候选人时必须填写原因",
        )

    current_decision = _manual_decision(document_results, process)
    overrides_auto_rejection = (
        latest_result.ai_group == "auto_rejected"
        and payload.target_stage in {"pending", "shortlisted"}
    )
    if overrides_auto_rejection and not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="恢复自动淘汰候选人时必须填写原因",
        )

    if payload.target_stage in {"pending", "shortlisted", "rejected"}:
        target_decision: ManualDecision = payload.target_stage  # type: ignore[assignment]
        if current_decision != target_decision:
            decision = RecruiterDecision(
                screening_result_id=latest_result.id,
                operator_id=current_user.id,
                sequence_number=len(latest_result.recruiter_decisions) + 1,
                previous_decision=current_decision,
                decision=target_decision,
                reason=payload.reason,
                is_auto_rejection_override=overrides_auto_rejection,
            )
            db.add(decision)

    now = datetime.now(UTC)
    if process is None:
        process = CandidateProcess(
            application_id=application.id,
            current_stage=payload.target_stage,
            stage_entered_at=now,
            updated_by_id=current_user.id,
        )
        db.add(process)
        db.flush()
        sequence_number = 1
    else:
        sequence_number = len(process.events) + 1
        process.current_stage = payload.target_stage
        process.stage_entered_at = now
        process.updated_by_id = current_user.id

    event = CandidateProcessEvent(
        process_id=process.id,
        sequence_number=sequence_number,
        from_stage=previous_stage,
        to_stage=payload.target_stage,
        reason=payload.reason,
        operator_id=current_user.id,
    )
    db.add(event)
    record_audit(
        db,
        action="candidate_process.stage_changed",
        target_type="candidate_process",
        target_id=process.id,
        job_id=job_id,
        batch_id=document.batch_id,
        result="success",
        actor=current_user,
        details={
            "document_id": str(document.id),
            "application_id": str(application.id),
            "screening_result_id": str(latest_result.id),
            "from_stage": previous_stage,
            "to_stage": payload.target_stage,
            "has_reason": bool(payload.reason),
        },
    )
    db.commit()
    db.refresh(process)
    return CandidateStageUpdateResponse(
        process_id=process.id,
        application_id=application.id,
        document_id=document.id,
        previous_stage=previous_stage,
        current_stage=payload.target_stage,
        stage_entered_at=process.stage_entered_at,
    )


@router.get(
    "/{job_id}/candidate-processes/{document_id}/timeline",
    response_model=list[CandidateProcessTimelineEventResponse],
)
def get_candidate_process_timeline(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[CandidateProcessTimelineEventResponse]:
    document = _get_owned_document(
        db,
        job_id=job_id,
        document_id=document_id,
        user=current_user,
    )
    decisions = list(
        db.scalars(
            select(RecruiterDecision)
            .join(ScreeningResult)
            .where(ScreeningResult.document_id == document.id)
            .options(selectinload(RecruiterDecision.operator))
            .order_by(RecruiterDecision.created_at, RecruiterDecision.sequence_number)
        ).all()
    )
    application = document.application
    process = application.process if application is not None else None
    if process is not None:
        decisions = [
            decision
            for decision in decisions
            if decision.created_at < process.created_at
        ]
    timeline = [
        CandidateProcessTimelineEventResponse(
            event_type="decision",
            from_stage=decision.previous_decision,
            to_stage=decision.decision,
            reason=decision.reason,
            operator_id=decision.operator_id,
            operator_display_name=(
                decision.operator.display_name if decision.operator is not None else "已删除用户"
            ),
            created_at=decision.created_at,
        )
        for decision in decisions
    ]
    if process is not None:
        timeline.extend(
            CandidateProcessTimelineEventResponse(
                event_type="stage",
                from_stage=event.from_stage,
                to_stage=event.to_stage,
                reason=event.reason,
                operator_id=event.operator_id,
                operator_display_name=(
                    event.operator.display_name if event.operator is not None else "已删除用户"
                ),
                created_at=event.created_at,
            )
            for event in process.events
        )
    timeline.sort(key=lambda item: item.created_at)
    return timeline
