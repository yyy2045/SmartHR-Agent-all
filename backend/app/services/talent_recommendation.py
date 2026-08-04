from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    Candidate,
    CandidateProfile,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    TalentPoolGroup,
    TalentPoolMembership,
    TalentRecommendationRun,
    TalentRecommendationRunCandidate,
    TalentRecommendationRunEvent,
    TalentRecommendationRunGroup,
    User,
)
from app.services.ai_client import RESUME_MATCH_PROMPT_VERSION
from app.services.audit import record_audit
from app.services.prompt_templates import get_published_prompt_snapshot

ACTIVE_RUN_STATUSES = ("queued", "retrieving", "rescoring")


class TalentRecommendationServiceError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class CreateRunOutcome:
    run: TalentRecommendationRun
    replayed: bool
    reused_active_run: bool
    should_dispatch: bool


@dataclass(frozen=True)
class RunActionOutcome:
    run: TalentRecommendationRun
    replayed: bool
    should_dispatch: bool = False
    task_id_to_revoke: str | None = None


def recommendation_run_options(*, include_results: bool = False) -> tuple[object, ...]:
    options: list[object] = [
        selectinload(TalentRecommendationRun.job),
        selectinload(TalentRecommendationRun.criteria_version),
        selectinload(TalentRecommendationRun.group_snapshots),
        selectinload(TalentRecommendationRun.candidate_snapshots),
    ]
    if include_results:
        options.append(selectinload(TalentRecommendationRun.results))
    return tuple(options)


def _criteria_snapshot(criteria: JobCriteriaVersion) -> dict[str, object]:
    return {
        "criteria_version_id": str(criteria.id),
        "version_number": criteria.version_number,
        "pass_threshold": criteria.pass_threshold,
        "hard_requirements": [
            {
                "requirement_id": str(item.id),
                "requirement_type": item.requirement_type,
                "title": item.title,
                "description": item.description,
                "expected_value": item.expected_value,
                "auto_reject": item.auto_reject,
                "sort_order": item.sort_order,
            }
            for item in sorted(criteria.hard_requirements, key=lambda value: value.sort_order)
        ],
        "scoring_dimensions": [
            {
                "dimension_id": str(item.id),
                "name": item.name,
                "description": item.description,
                "weight_percent": item.weight_percent,
                "sort_order": item.sort_order,
            }
            for item in sorted(criteria.scoring_dimensions, key=lambda value: value.sort_order)
        ],
    }


def _latest_confirmed_criteria(db: Session, job_id: uuid.UUID) -> JobCriteriaVersion:
    criteria = db.scalar(
        select(JobCriteriaVersion)
        .where(
            JobCriteriaVersion.job_id == job_id,
            JobCriteriaVersion.status == "confirmed",
        )
        .options(
            selectinload(JobCriteriaVersion.hard_requirements),
            selectinload(JobCriteriaVersion.scoring_dimensions),
        )
        .order_by(JobCriteriaVersion.version_number.desc())
        .limit(1)
    )
    if criteria is None:
        raise TalentRecommendationServiceError(
            "职位尚未确认筛选标准",
            status_code=409,
        )
    return criteria


def _load_groups(
    db: Session,
    group_ids: list[uuid.UUID],
) -> list[TalentPoolGroup]:
    groups = list(
        db.scalars(
            select(TalentPoolGroup).where(TalentPoolGroup.id.in_(group_ids)).with_for_update()
        ).all()
    )
    by_id = {group.id: group for group in groups}
    if len(by_id) != len(group_ids):
        raise TalentRecommendationServiceError("所选人才分组不存在", status_code=404)
    ordered = [by_id[group_id] for group_id in group_ids]
    if any(group.is_archived for group in ordered):
        raise TalentRecommendationServiceError("归档人才组不能参与推荐", status_code=409)
    return ordered


def _candidate_scope_snapshots(
    db: Session,
    group_ids: list[uuid.UUID],
    *,
    job_id: uuid.UUID,
) -> tuple[list[TalentRecommendationRunCandidate], int]:
    membership_rows = db.execute(
        select(TalentPoolMembership.candidate_id, TalentPoolMembership.group_id)
        .join(Candidate, Candidate.id == TalentPoolMembership.candidate_id)
        .where(
            TalentPoolMembership.group_id.in_(group_ids),
            TalentPoolMembership.status == "active",
            Candidate.status == "active",
        )
    ).all()
    groups_by_candidate: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for candidate_id, group_id in membership_rows:
        groups_by_candidate[candidate_id].add(group_id)
    if not groups_by_candidate:
        return [], 0

    target_application_exists = exists(
        select(JobApplication.id).where(
            JobApplication.candidate_id == Candidate.id,
            JobApplication.job_id == job_id,
            JobApplication.status == "active",
        )
    )
    candidate_ids = set(
        db.scalars(
            select(Candidate.id).where(
                Candidate.id.in_(groups_by_candidate),
                Candidate.status == "active",
                ~target_application_exists,
            )
        ).all()
    )
    if not candidate_ids:
        return [], len(groups_by_candidate)

    application_rows = db.execute(
        select(JobApplication.candidate_id, ResumeDocument)
        .join(
            ResumeDocument,
            ResumeDocument.id == JobApplication.primary_document_id,
        )
        .where(
            JobApplication.candidate_id.in_(candidate_ids),
            JobApplication.status == "active",
            JobApplication.primary_document_id.is_not(None),
            ResumeDocument.status == "completed",
        )
        .order_by(
            JobApplication.candidate_id,
            JobApplication.updated_at.desc(),
            ResumeDocument.updated_at.desc(),
            JobApplication.id.desc(),
        )
    ).all()
    document_by_candidate: dict[uuid.UUID, ResumeDocument] = {}
    for candidate_id, document in application_rows:
        document_by_candidate.setdefault(candidate_id, document)

    document_ids = {document.id for document in document_by_candidate.values()}
    profile_by_document: dict[uuid.UUID, CandidateProfile] = {}
    if document_ids:
        profiles = db.scalars(
            select(CandidateProfile)
            .where(CandidateProfile.document_id.in_(document_ids))
            .order_by(
                CandidateProfile.document_id,
                CandidateProfile.version_number.desc(),
                CandidateProfile.created_at.desc(),
            )
        ).all()
        for profile in profiles:
            profile_by_document.setdefault(profile.document_id, profile)

    candidates = {
        candidate.id: candidate
        for candidate in db.scalars(
            select(Candidate).where(Candidate.id.in_(candidate_ids))
        ).all()
    }
    snapshots: list[TalentRecommendationRunCandidate] = []
    for candidate_id in sorted(candidate_ids, key=str):
        candidate = candidates.get(candidate_id)
        document = document_by_candidate.get(candidate_id)
        profile = profile_by_document.get(document.id) if document is not None else None
        if (
            candidate is None
            or document is None
            or profile is None
            or not document.sha256
            or document.updated_at is None
        ):
            continue
        snapshots.append(
            TalentRecommendationRunCandidate(
                candidate_id=candidate.id,
                candidate_code_snapshot=candidate.candidate_code,
                candidate_name_snapshot=candidate.full_name,
                document_id=document.id,
                document_sha256_snapshot=document.sha256,
                document_updated_at_snapshot=document.updated_at,
                candidate_profile_id=profile.id,
                profile_version_snapshot=profile.version_number,
                embedding_model_snapshot=settings.embedding_model or "unconfigured",
                embedding_version_snapshot=settings.embedding_version,
                embedding_dimension_snapshot=settings.embedding_dimension,
                matched_group_ids=[
                    str(group_id)
                    for group_id in sorted(groups_by_candidate[candidate.id], key=str)
                ],
            )
        )
    excluded_count = len(groups_by_candidate) - len(snapshots)
    return snapshots, excluded_count


def _next_event_sequence(db: Session, run_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(
                func.coalesce(func.max(TalentRecommendationRunEvent.sequence_number), 0) + 1
            ).where(TalentRecommendationRunEvent.run_id == run_id)
        )
        or 1
    )


def _append_event(
    db: Session,
    *,
    run: TalentRecommendationRun,
    idempotency_key: uuid.UUID,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    details: dict[str, object],
    actor: User | None,
) -> TalentRecommendationRunEvent:
    event = TalentRecommendationRunEvent(
        run_id=run.id,
        sequence_number=_next_event_sequence(db, run.id),
        idempotency_key=idempotency_key,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        details=details,
        actor_user_id=actor.id if actor else None,
        actor_username_snapshot=actor.username if actor else None,
        actor_display_name_snapshot=actor.display_name if actor else None,
    )
    db.add(event)
    return event


def _find_event(
    db: Session,
    run_id: uuid.UUID,
    idempotency_key: uuid.UUID,
) -> TalentRecommendationRunEvent | None:
    return db.scalar(
        select(TalentRecommendationRunEvent).where(
            TalentRecommendationRunEvent.run_id == run_id,
            TalentRecommendationRunEvent.idempotency_key == idempotency_key,
        )
    )


def _lock_job(db: Session, job_id: uuid.UUID) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise TalentRecommendationServiceError("职位不存在", status_code=404)
    return job


def _ensure_write_access(job: Job, actor: User) -> None:
    if actor.has_role("administrator") or (
        actor.has_role("recruiter") and job.owner_id == actor.id
    ):
        return
    raise TalentRecommendationServiceError(
        "当前角色只能查看该职位的推荐任务",
        status_code=403,
    )


def _ensure_job_ready(job: Job) -> None:
    if job.status != "active":
        raise TalentRecommendationServiceError("归档职位不能创建推荐任务", status_code=409)
    owner = job.owner
    if owner is None or not owner.is_active or not owner.has_role("recruiter"):
        raise TalentRecommendationServiceError(
            "职位当前招聘专员不可用，请先重新分配",
            status_code=409,
        )


def _same_create_request(
    run: TalentRecommendationRun,
    *,
    group_ids: list[uuid.UUID],
    ai_input_mode: str,
) -> bool:
    return run.ai_input_mode == ai_input_mode and {
        item.group_id for item in run.group_snapshots
    } == set(group_ids)


def create_recommendation_run(
    db: Session,
    *,
    job_id: uuid.UUID,
    group_ids: list[uuid.UUID],
    ai_input_mode: str,
    idempotency_key: uuid.UUID,
    actor: User,
) -> CreateRunOutcome:
    job = _lock_job(db, job_id)
    _ensure_write_access(job, actor)

    existing = db.scalar(
        select(TalentRecommendationRun)
        .where(
            TalentRecommendationRun.job_id == job.id,
            TalentRecommendationRun.idempotency_key == idempotency_key,
        )
        .options(*recommendation_run_options())
    )
    if existing is not None:
        if not _same_create_request(
            existing,
            group_ids=group_ids,
            ai_input_mode=ai_input_mode,
        ):
            raise TalentRecommendationServiceError(
                "推荐任务幂等标识已用于不同参数",
                status_code=409,
            )
        return CreateRunOutcome(
            run=existing,
            replayed=True,
            reused_active_run=False,
            should_dispatch=existing.status == "queued" and not existing.celery_task_id,
        )

    _ensure_job_ready(job)
    criteria = _latest_confirmed_criteria(db, job.id)
    active = db.scalar(
        select(TalentRecommendationRun)
        .where(
            TalentRecommendationRun.job_id == job.id,
            TalentRecommendationRun.criteria_version_id == criteria.id,
            TalentRecommendationRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .options(*recommendation_run_options())
        .order_by(TalentRecommendationRun.created_at.desc())
        .limit(1)
    )
    if active is not None:
        return CreateRunOutcome(
            run=active,
            replayed=False,
            reused_active_run=True,
            should_dispatch=active.status == "queued" and not active.celery_task_id,
        )

    groups = _load_groups(db, group_ids)
    candidate_snapshots, excluded_count = _candidate_scope_snapshots(
        db,
        group_ids,
        job_id=job.id,
    )
    scope_candidate_count = len(candidate_snapshots)
    prompt_template = get_published_prompt_snapshot(db, "resume_analysis")
    prompt_version = (
        prompt_template.prompt_version
        if prompt_template is not None
        else RESUME_MATCH_PROMPT_VERSION
    )
    run = TalentRecommendationRun(
        job=job,
        criteria_version=criteria,
        created_by=actor,
        created_by_username_snapshot=actor.username,
        created_by_display_name_snapshot=actor.display_name,
        idempotency_key=idempotency_key,
        status="queued",
        ai_input_mode=ai_input_mode,
        criteria_snapshot=_criteria_snapshot(criteria),
        embedding_model_snapshot=settings.embedding_model or "unconfigured",
        ai_model_snapshot=settings.ai_model or "unconfigured",
        prompt_version_snapshot=prompt_version,
        scope_candidate_count=scope_candidate_count,
        excluded_count=excluded_count,
        group_snapshots=[
            TalentRecommendationRunGroup(
                group=group,
                group_name_snapshot=group.name,
                group_version_snapshot=group.version,
            )
            for group in groups
        ],
        candidate_snapshots=candidate_snapshots,
    )
    db.add(run)
    db.flush()
    _append_event(
        db,
        run=run,
        idempotency_key=uuid.uuid5(idempotency_key, "created"),
        event_type="created",
        from_status=None,
        to_status="queued",
        details={
            "group_ids": [str(group.id) for group in groups],
            "ai_input_mode": ai_input_mode,
            "scope_candidate_count": scope_candidate_count,
            "excluded_count": excluded_count,
        },
        actor=actor,
    )
    record_audit(
        db,
        action="talent_recommendation.created",
        target_type="talent_recommendation_run",
        target_id=run.id,
        job_id=job.id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "criteria_version_id": str(criteria.id),
            "group_ids": [str(group.id) for group in groups],
            "ai_input_mode": ai_input_mode,
            "scope_candidate_count": scope_candidate_count,
            "excluded_count": excluded_count,
        },
    )
    return CreateRunOutcome(
        run=run,
        replayed=False,
        reused_active_run=False,
        should_dispatch=True,
    )


def get_run_for_update(
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
        .options(*recommendation_run_options())
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if run is None:
        raise TalentRecommendationServiceError("推荐任务不存在", status_code=404)
    return run


def attach_task_id(
    db: Session,
    *,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    task_id: str,
) -> bool:
    run = get_run_for_update(db, job_id=job_id, run_id=run_id)
    if run.status not in ACTIVE_RUN_STATUSES:
        return False
    if run.celery_task_id is not None:
        return run.celery_task_id == task_id
    run.celery_task_id = task_id
    run.resource_version += 1
    return True


def mark_dispatch_failed(
    db: Session,
    *,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    operation_key: uuid.UUID,
    error_message: str,
    actor: User,
) -> TalentRecommendationRun:
    run = get_run_for_update(db, job_id=job_id, run_id=run_id)
    previous_status = run.status
    if previous_status == "queued":
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
    run.failure_code = "recommendation_dispatch_failed"
    run.failure_summary = error_message[:2_000]
    run.resource_version += 1
    failure_key = uuid.uuid5(operation_key, "dispatch-failed")
    if _find_event(db, run.id, failure_key) is None:
        _append_event(
            db,
            run=run,
            idempotency_key=failure_key,
            event_type="failed",
            from_status=previous_status,
            to_status=run.status,
            details={"failure_code": run.failure_code},
            actor=actor,
        )
    record_audit(
        db,
        action="talent_recommendation.dispatch_failed",
        target_type="talent_recommendation_run",
        target_id=run.id,
        job_id=run.job_id,
        result="failure",
        actor=actor,
        details={"failure_code": run.failure_code},
    )
    return run


def cancel_recommendation_run(
    db: Session,
    *,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    expected_version: int,
    idempotency_key: uuid.UUID,
    actor: User,
) -> RunActionOutcome:
    job = _lock_job(db, job_id)
    _ensure_write_access(job, actor)
    run = get_run_for_update(db, job_id=job_id, run_id=run_id)
    replay = _find_event(db, run.id, idempotency_key)
    if replay is not None:
        if replay.event_type != "cancel_requested":
            raise TalentRecommendationServiceError(
                "操作幂等标识已用于其他动作",
                status_code=409,
            )
        return RunActionOutcome(run=run, replayed=True)
    if run.resource_version != expected_version:
        raise TalentRecommendationServiceError(
            "推荐任务版本已变化，请刷新后重试",
            status_code=409,
        )
    if run.status not in ACTIVE_RUN_STATUSES:
        raise TalentRecommendationServiceError(
            "只有排队或运行中的推荐任务可以取消",
            status_code=409,
        )

    previous_status = run.status
    task_id = run.celery_task_id
    first_sequence = _next_event_sequence(db, run.id)
    db.add(
        TalentRecommendationRunEvent(
            run_id=run.id,
            sequence_number=first_sequence,
            idempotency_key=idempotency_key,
            event_type="cancel_requested",
            from_status=previous_status,
            to_status=previous_status,
            details={"task_id_present": task_id is not None},
            actor_user_id=actor.id,
            actor_username_snapshot=actor.username,
            actor_display_name_snapshot=actor.display_name,
        )
    )
    run.status = "cancelled"
    run.completed_at = datetime.now(UTC)
    run.resource_version += 1
    db.add(
        TalentRecommendationRunEvent(
            run_id=run.id,
            sequence_number=first_sequence + 1,
            idempotency_key=uuid.uuid5(idempotency_key, "cancelled"),
            event_type="cancelled",
            from_status=previous_status,
            to_status="cancelled",
            details={},
            actor_user_id=actor.id,
            actor_username_snapshot=actor.username,
            actor_display_name_snapshot=actor.display_name,
        )
    )
    record_audit(
        db,
        action="talent_recommendation.cancelled",
        target_type="talent_recommendation_run",
        target_id=run.id,
        job_id=run.job_id,
        result="success",
        actor=actor,
        details={"idempotency_key": str(idempotency_key), "from_status": previous_status},
    )
    return RunActionOutcome(
        run=run,
        replayed=False,
        task_id_to_revoke=task_id,
    )


def retry_failed_recommendation_results(
    db: Session,
    *,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    expected_version: int,
    idempotency_key: uuid.UUID,
    actor: User,
) -> RunActionOutcome:
    job = _lock_job(db, job_id)
    _ensure_write_access(job, actor)
    run = get_run_for_update(db, job_id=job_id, run_id=run_id)
    replay = _find_event(db, run.id, idempotency_key)
    if replay is not None:
        if replay.event_type != "retry_requested":
            raise TalentRecommendationServiceError(
                "操作幂等标识已用于其他动作",
                status_code=409,
            )
        return RunActionOutcome(run=run, replayed=True)
    if run.resource_version != expected_version:
        raise TalentRecommendationServiceError(
            "推荐任务版本已变化，请刷新后重试",
            status_code=409,
        )
    if run.criteria_stale:
        raise TalentRecommendationServiceError(
            "职位筛选标准已经变化，请创建新的推荐任务",
            status_code=409,
        )
    if run.status != "partial" or run.failed_count <= 0:
        raise TalentRecommendationServiceError(
            "只有部分完成且仍有失败项的推荐任务可以重试",
            status_code=409,
        )

    previous_task_id = run.celery_task_id
    run.celery_task_id = None
    run.failure_code = None
    run.failure_summary = None
    run.resource_version += 1
    _append_event(
        db,
        run=run,
        idempotency_key=idempotency_key,
        event_type="retry_requested",
        from_status="partial",
        to_status="partial",
        details={
            "failed_only": True,
            "failed_count": run.failed_count,
            "previous_task_id": previous_task_id,
        },
        actor=actor,
    )
    record_audit(
        db,
        action="talent_recommendation.retry_requested",
        target_type="talent_recommendation_run",
        target_id=run.id,
        job_id=run.job_id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "failed_count": run.failed_count,
        },
    )
    return RunActionOutcome(run=run, replayed=False, should_dispatch=True)


def mark_runs_stale_for_new_criteria(
    db: Session,
    *,
    job_id: uuid.UUID,
    criteria_version_id: uuid.UUID,
    actor: User,
) -> int:
    runs = list(
        db.scalars(
            select(TalentRecommendationRun)
            .where(
                TalentRecommendationRun.job_id == job_id,
                TalentRecommendationRun.criteria_version_id != criteria_version_id,
                TalentRecommendationRun.criteria_stale.is_(False),
            )
            .with_for_update()
        ).all()
    )
    stale_at = datetime.now(UTC)
    for run in runs:
        run.criteria_stale = True
        run.criteria_stale_at = stale_at
        run.resource_version += 1
        event_key = uuid.uuid5(criteria_version_id, f"stale:{run.id}")
        if _find_event(db, run.id, event_key) is None:
            _append_event(
                db,
                run=run,
                idempotency_key=event_key,
                event_type="stale_marked",
                from_status=run.status,
                to_status=run.status,
                details={"new_criteria_version_id": str(criteria_version_id)},
                actor=actor,
            )
    return len(runs)
