import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import Job, TalentRecommendationRun, User
from app.schemas.talent_recommendation import (
    TalentRecommendationAction,
    TalentRecommendationActionRequest,
    TalentRecommendationCreateRequest,
    TalentRecommendationCreateResponse,
    TalentRecommendationGroupSnapshotResponse,
    TalentRecommendationResultResponse,
    TalentRecommendationRunDetailResponse,
    TalentRecommendationRunListResponse,
    TalentRecommendationRunResponse,
    TalentRecommendationRunStatus,
    TalentRecommendationSelectionItemResponse,
    TalentRecommendationSelectionRequest,
    TalentRecommendationSelectionResponse,
)
from app.services.authorization import get_visible_job
from app.services.talent_recommendation import (
    TalentRecommendationServiceError,
    attach_task_id,
    cancel_recommendation_run,
    create_recommendation_run,
    mark_dispatch_failed,
    recommendation_run_options,
    retry_failed_recommendation_results,
)
from app.services.talent_recommendation_selection import (
    TalentRecommendationSelectionError,
    select_recommended_candidates,
)
from app.workers.dispatcher import enqueue_talent_recommendation, revoke_task

logger = logging.getLogger(__name__)
router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _raise_service_error(error: TalentRecommendationServiceError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


def _ensure_read_role(user: User) -> None:
    if not user.has_role("administrator", "recruiter", "hiring_manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有人才推荐访问权限",
        )


def _can_write(job: Job, user: User) -> bool:
    return user.has_role("administrator") or (
        user.has_role("recruiter") and job.owner_id == user.id
    )


def _allowed_actions(
    run: TalentRecommendationRun,
    *,
    can_write: bool,
) -> list[TalentRecommendationAction]:
    if not can_write:
        return []
    actions: list[TalentRecommendationAction] = []
    if run.status in ("queued", "retrieving", "rescoring"):
        actions.append("cancel")
    if run.status == "partial" and run.failed_count > 0 and not run.criteria_stale:
        actions.append("retry_failed_items")
    if (
        run.status in ("completed", "partial")
        and run.completed_count > 0
        and not run.criteria_stale
    ):
        actions.append("select_candidates")
    return actions


def _run_response(
    run: TalentRecommendationRun,
    *,
    can_write: bool,
) -> TalentRecommendationRunResponse:
    criteria_version_number = run.criteria_snapshot.get("version_number")
    if not isinstance(criteria_version_number, int):
        criteria_version_number = run.criteria_version.version_number
    return TalentRecommendationRunResponse(
        id=run.id,
        job_id=run.job_id,
        job_title=run.job.title,
        criteria_version_id=run.criteria_version_id,
        criteria_version_number=criteria_version_number,
        created_by_id=run.created_by_id,
        created_by_username=run.created_by_username_snapshot,
        created_by_display_name=run.created_by_display_name_snapshot,
        status=run.status,  # type: ignore[arg-type]
        ai_input_mode=run.ai_input_mode,  # type: ignore[arg-type]
        recall_limit=run.recall_limit,
        rescore_limit=run.rescore_limit,
        scope_candidate_count=run.scope_candidate_count,
        retrieved_count=run.retrieved_count,
        rescored_count=run.rescored_count,
        completed_count=run.completed_count,
        failed_count=run.failed_count,
        excluded_count=run.excluded_count,
        criteria_stale=run.criteria_stale,
        criteria_stale_at=run.criteria_stale_at,
        failure_code=run.failure_code,
        failure_summary=run.failure_summary,
        resource_version=run.resource_version,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        groups=[
            TalentRecommendationGroupSnapshotResponse(
                group_id=item.group_id,
                group_name=item.group_name_snapshot,
                group_version=item.group_version_snapshot,
            )
            for item in run.group_snapshots
        ],
        allowed_actions=_allowed_actions(run, can_write=can_write),
    )


def _detail_response(
    run: TalentRecommendationRun,
    *,
    can_write: bool,
) -> TalentRecommendationRunDetailResponse:
    summary = _run_response(run, can_write=can_write)
    return TalentRecommendationRunDetailResponse(
        **summary.model_dump(),
        results=[
            TalentRecommendationResultResponse(
                id=item.id,
                candidate_id=item.candidate_id,
                resolved_candidate_id=item.resolved_candidate_id,
                candidate_code=item.candidate_code_snapshot,
                candidate_name=item.candidate_name_snapshot,
                candidate_merged_at=item.candidate_merged_at,
                document_id=item.document_id,
                candidate_profile_id=item.candidate_profile_id,
                profile_version=item.profile_version_snapshot,
                vector_rank=item.vector_rank,
                similarity_score=item.similarity_score,
                matched_group_ids=item.matched_group_ids,
                matched_chunks=item.matched_chunks,
                status=item.status,  # type: ignore[arg-type]
                ai_score=item.ai_score,
                ai_group=item.ai_group,  # type: ignore[arg-type]
                ai_dimension_scores=item.ai_dimension_scores,
                ai_hard_requirement_results=item.ai_hard_requirement_results,
                ai_strengths=item.ai_strengths,
                ai_gaps=item.ai_gaps,
                ai_missing_items=item.ai_missing_items,
                ai_interview_questions=item.ai_interview_questions,
                ai_evidence=item.ai_evidence,
                processing_attempt_count=item.processing_attempt_count,
                failure_code=item.failure_code,
                failure_message=item.failure_message,
                exclusion_code=item.exclusion_code,
                exclusion_reason=item.exclusion_reason,
                document_stale=item.document_stale,
                profile_stale=item.profile_stale,
                embedding_stale=item.embedding_stale,
                stale_at=item.stale_at,
                completed_at=item.completed_at,
            )
            for item in sorted(run.results, key=lambda value: value.vector_rank)
        ],
    )


def _load_run(
    db: Session,
    *,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
) -> TalentRecommendationRun:
    run = db.scalar(
        select(TalentRecommendationRun)
        .where(
            TalentRecommendationRun.id == run_id,
            TalentRecommendationRun.job_id == job_id,
        )
        .options(*recommendation_run_options(include_results=True))
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="推荐任务不存在",
        )
    return run


def _dispatch(
    db: Session,
    *,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    operation_key: uuid.UUID,
    actor: User,
    retry_failed_only: bool,
) -> None:
    task_id: str | None = None
    attached = False
    try:
        task_id = enqueue_talent_recommendation(
            run_id,
            retry_failed_only=retry_failed_only,
        )
        attached = attach_task_id(
            db,
            job_id=job_id,
            run_id=run_id,
            task_id=task_id,
        )
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("人才推荐任务入队失败，run_id=%s", run_id)
        try:
            mark_dispatch_failed(
                db,
                job_id=job_id,
                run_id=run_id,
                operation_key=operation_key,
                error_message=str(error) or error.__class__.__name__,
                actor=actor,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("记录人才推荐入队失败状态时再次失败，run_id=%s", run_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="推荐任务暂时无法入队，请稍后重试",
        ) from error
    if task_id is not None and not attached:
        try:
            revoke_task(task_id)
        except Exception:
            logger.exception(
                "撤销未绑定的 Celery 推荐任务失败，run_id=%s",
                run_id,
            )


@router.post(
    "/{job_id:uuid}/recommendations",
    response_model=TalentRecommendationCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_talent_recommendation(
    job_id: uuid.UUID,
    payload: TalentRecommendationCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentRecommendationCreateResponse:
    job = get_visible_job(db, job_id, current_user)
    _ensure_read_role(current_user)
    if not _can_write(job, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色只能查看该职位的推荐任务",
        )
    try:
        outcome = create_recommendation_run(
            db,
            job_id=job_id,
            group_ids=payload.group_ids,
            ai_input_mode=payload.ai_input_mode,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except TalentRecommendationServiceError as error:
        db.rollback()
        _raise_service_error(error)

    if outcome.should_dispatch:
        _dispatch(
            db,
            job_id=job_id,
            run_id=outcome.run.id,
            operation_key=payload.idempotency_key,
            actor=current_user,
            retry_failed_only=False,
        )
    run = _load_run(db, job_id=job_id, run_id=outcome.run.id)
    return TalentRecommendationCreateResponse(
        run=_run_response(run, can_write=True),
        replayed=outcome.replayed,
        reused_active_run=outcome.reused_active_run,
    )


@router.get(
    "/{job_id:uuid}/recommendations",
    response_model=TalentRecommendationRunListResponse,
)
def list_talent_recommendations(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    run_status: Annotated[
        TalentRecommendationRunStatus | None,
        Query(alias="status"),
    ] = None,
    created_by_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TalentRecommendationRunListResponse:
    job = get_visible_job(db, job_id, current_user)
    _ensure_read_role(current_user)
    if created_from and created_to and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="开始时间不能晚于结束时间",
        )
    filters = [TalentRecommendationRun.job_id == job.id]
    if run_status is not None:
        filters.append(TalentRecommendationRun.status == run_status)
    if created_by_id is not None:
        filters.append(TalentRecommendationRun.created_by_id == created_by_id)
    if created_from is not None:
        filters.append(TalentRecommendationRun.created_at >= created_from)
    if created_to is not None:
        filters.append(TalentRecommendationRun.created_at <= created_to)

    total = db.scalar(select(func.count(TalentRecommendationRun.id)).where(*filters)) or 0
    runs = list(
        db.scalars(
            select(TalentRecommendationRun)
            .where(*filters)
            .options(*recommendation_run_options())
            .order_by(
                TalentRecommendationRun.created_at.desc(),
                TalentRecommendationRun.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
    )
    can_write = _can_write(job, current_user)
    return TalentRecommendationRunListResponse(
        items=[_run_response(run, can_write=can_write) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{job_id:uuid}/recommendations/{run_id:uuid}",
    response_model=TalentRecommendationRunDetailResponse,
)
def get_talent_recommendation(
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentRecommendationRunDetailResponse:
    job = get_visible_job(db, job_id, current_user)
    _ensure_read_role(current_user)
    run = _load_run(db, job_id=job_id, run_id=run_id)
    return _detail_response(run, can_write=_can_write(job, current_user))


@router.post(
    "/{job_id:uuid}/recommendations/{run_id:uuid}/cancel",
    response_model=TalentRecommendationRunResponse,
)
def cancel_talent_recommendation(
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: TalentRecommendationActionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentRecommendationRunResponse:
    job = get_visible_job(db, job_id, current_user)
    _ensure_read_role(current_user)
    if not _can_write(job, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色只能查看该职位的推荐任务",
        )
    try:
        outcome = cancel_recommendation_run(
            db,
            job_id=job_id,
            run_id=run_id,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except TalentRecommendationServiceError as error:
        db.rollback()
        _raise_service_error(error)
    if outcome.task_id_to_revoke:
        try:
            revoke_task(outcome.task_id_to_revoke)
        except Exception:
            logger.exception(
                "撤销 Celery 推荐任务失败，run_id=%s，采用数据库取消状态兜底",
                run_id,
            )
    run = _load_run(db, job_id=job_id, run_id=run_id)
    return _run_response(run, can_write=True)


@router.post(
    "/{job_id:uuid}/recommendations/{run_id:uuid}/retry-failures",
    response_model=TalentRecommendationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_talent_recommendation_failures(
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: TalentRecommendationActionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentRecommendationRunResponse:
    job = get_visible_job(db, job_id, current_user)
    _ensure_read_role(current_user)
    if not _can_write(job, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色只能查看该职位的推荐任务",
        )
    try:
        outcome = retry_failed_recommendation_results(
            db,
            job_id=job_id,
            run_id=run_id,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except TalentRecommendationServiceError as error:
        db.rollback()
        _raise_service_error(error)
    if outcome.should_dispatch:
        _dispatch(
            db,
            job_id=job_id,
            run_id=run_id,
            operation_key=payload.idempotency_key,
            actor=current_user,
            retry_failed_only=True,
        )
    run = _load_run(db, job_id=job_id, run_id=run_id)
    return _run_response(run, can_write=True)


@router.post(
    "/{job_id:uuid}/recommendations/{run_id:uuid}/select",
    response_model=TalentRecommendationSelectionResponse,
)
def select_talent_recommendation_candidates(
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: TalentRecommendationSelectionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> TalentRecommendationSelectionResponse:
    job = get_visible_job(db, job_id, current_user)
    _ensure_read_role(current_user)
    if not _can_write(job, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色只能查看该职位的推荐任务",
        )
    try:
        outcomes = select_recommended_candidates(
            db,
            job_id=job_id,
            run_id=run_id,
            result_ids=payload.result_ids,
            confirmed_stale_result_ids=set(payload.confirmed_stale_result_ids),
            idempotency_key=payload.idempotency_key,
            actor=current_user,
        )
        db.commit()
    except TalentRecommendationSelectionError as error:
        db.rollback()
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

    items = [
        TalentRecommendationSelectionItemResponse(
            result_id=item.result_id,
            status=item.status,  # type: ignore[arg-type]
            application_id=item.application_id,
            screening_result_id=item.screening_result_id,
            failure_code=item.failure_code,
            failure_message=item.failure_message,
        )
        for item in outcomes
    ]
    return TalentRecommendationSelectionResponse(
        created_count=sum(item.status == "created" for item in outcomes),
        existing_count=sum(item.status == "existing" for item in outcomes),
        failed_count=sum(item.status == "failed" for item in outcomes),
        items=items,
    )
