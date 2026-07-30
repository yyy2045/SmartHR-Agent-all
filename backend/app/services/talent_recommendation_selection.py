from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    ApplicationResumeDocument,
    Candidate,
    CandidateProcess,
    CandidateProcessEvent,
    DimensionScore,
    EvidenceCitation,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeTextSegment,
    ScreeningResult,
    TalentPoolGroup,
    TalentPoolMembership,
    TalentRecommendationResult,
    TalentRecommendationRun,
    User,
)
from app.services.audit import record_audit


class TalentRecommendationSelectionError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class RecommendationSnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class TalentRecommendationSelectionItem:
    result_id: uuid.UUID
    status: str
    application_id: uuid.UUID | None = None
    screening_result_id: uuid.UUID | None = None
    failure_code: str | None = None
    failure_message: str | None = None


def _failed(
    result_id: uuid.UUID,
    code: str,
    message: str,
) -> TalentRecommendationSelectionItem:
    return TalentRecommendationSelectionItem(
        result_id=result_id,
        status="failed",
        failure_code=code,
        failure_message=message,
    )


def _resolve_candidate(db: Session, candidate_id: uuid.UUID) -> Candidate | None:
    current_id = candidate_id
    visited: set[uuid.UUID] = set()
    for _ in range(20):
        if current_id in visited:
            return None
        visited.add(current_id)
        candidate = db.get(Candidate, current_id)
        if candidate is None:
            return None
        if candidate.status == "active":
            return candidate
        if candidate.merged_into_candidate_id is None:
            return None
        current_id = candidate.merged_into_candidate_id
    return None


def _latest_screening_result_id(
    db: Session,
    application_id: uuid.UUID,
) -> uuid.UUID | None:
    return db.scalar(
        select(ScreeningResult.id)
        .where(ScreeningResult.application_id == application_id)
        .order_by(
            ScreeningResult.analysis_version.desc(),
            ScreeningResult.created_at.desc(),
            ScreeningResult.id.desc(),
        )
        .limit(1)
    )


def _existing_application(
    db: Session,
    *,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> JobApplication | None:
    return db.scalar(
        select(JobApplication)
        .where(
            JobApplication.job_id == job_id,
            JobApplication.candidate_id == candidate_id,
            JobApplication.status == "active",
        )
        .order_by(JobApplication.created_at, JobApplication.id)
        .limit(1)
        .with_for_update()
    )


def _current_primary_document_id(
    db: Session,
    candidate_id: uuid.UUID,
) -> uuid.UUID | None:
    return db.scalar(
        select(JobApplication.primary_document_id)
        .where(
            JobApplication.candidate_id == candidate_id,
            JobApplication.status == "active",
            JobApplication.primary_document_id.is_not(None),
        )
        .order_by(JobApplication.updated_at.desc(), JobApplication.id.desc())
        .limit(1)
    )


def _has_active_matched_membership(
    db: Session,
    *,
    candidate_id: uuid.UUID,
    matched_group_ids: list[str],
) -> bool:
    try:
        group_ids = {uuid.UUID(value) for value in matched_group_ids}
    except (TypeError, ValueError) as error:
        raise RecommendationSnapshotError("推荐结果的人才组快照不合法") from error
    if not group_ids:
        return False
    return bool(
        db.scalar(
            select(
                exists().where(
                    TalentPoolMembership.candidate_id == candidate_id,
                    TalentPoolMembership.group_id.in_(group_ids),
                    TalentPoolMembership.status == "active",
                    TalentPoolGroup.id == TalentPoolMembership.group_id,
                    TalentPoolGroup.archived_at.is_(None),
                )
            )
        )
    )


def _snapshot_int(value: object, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise RecommendationSnapshotError(f"{field} 不合法")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise RecommendationSnapshotError(f"{field} 不合法") from error
    if parsed < minimum:
        raise RecommendationSnapshotError(f"{field} 不合法")
    return parsed


def _snapshot_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise RecommendationSnapshotError(f"{field} 不合法") from error
    if not parsed.is_finite():
        raise RecommendationSnapshotError(f"{field} 不合法")
    return parsed


def _snapshot_uuid(value: object, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise RecommendationSnapshotError(f"{field} 不合法") from error


def _snapshot_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecommendationSnapshotError(f"{field} 不合法")
    return value.strip()


def _snapshot_list(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise RecommendationSnapshotError(f"{field} 不合法")
    return value


def _build_screening_result(
    db: Session,
    *,
    application: JobApplication,
    run: TalentRecommendationRun,
    result: TalentRecommendationResult,
    document: ResumeDocument,
) -> ScreeningResult:
    if result.ai_score is None or result.ai_group is None:
        raise RecommendationSnapshotError("AI 评分快照不完整")
    if result.ai_model_snapshot is None or result.prompt_version_snapshot is None:
        raise RecommendationSnapshotError("AI 模型快照不完整")
    pass_threshold = _snapshot_int(
        run.criteria_snapshot.get("pass_threshold"),
        field="通过分数",
    )
    if pass_threshold > 100:
        raise RecommendationSnapshotError("通过分数不合法")
    total_score = _snapshot_decimal(result.ai_score, field="AI 总分")
    if total_score < 0 or total_score > 100:
        raise RecommendationSnapshotError("AI 总分不合法")

    completed_at = result.completed_at or datetime.now(UTC)
    screening = ScreeningResult(
        application_id=application.id,
        document_id=document.id,
        candidate_profile_id=result.candidate_profile_id,
        criteria_version_id=run.criteria_version_id,
        analysis_version=1,
        status="completed",
        ai_group=result.ai_group,
        total_score=total_score,
        pass_threshold=pass_threshold,
        hard_requirement_results=list(result.ai_hard_requirement_results),
        strengths=list(result.ai_strengths),
        gaps=list(result.ai_gaps),
        missing_items=list(result.ai_missing_items),
        interview_questions=list(result.ai_interview_questions),
        model_name=result.ai_model_snapshot,
        prompt_version=result.prompt_version_snapshot,
        started_at=completed_at,
        completed_at=completed_at,
    )
    application.screening_results.append(screening)

    dimension_rows: dict[uuid.UUID, DimensionScore] = {}
    raw_dimensions = _snapshot_list(
        result.ai_dimension_scores,
        field="评分维度快照",
    )
    ordered_dimensions: list[tuple[int, dict[str, object]]] = []
    for raw in raw_dimensions:
        if not isinstance(raw, dict):
            raise RecommendationSnapshotError("评分维度快照不合法")
        ordered_dimensions.append(
            (
                _snapshot_int(raw.get("sort_order"), field="评分维度顺序"),
                raw,
            )
        )
    ordered_dimensions.sort(key=lambda item: (item[0], str(item[1].get("dimension_id"))))
    for index, (_, raw) in enumerate(ordered_dimensions):
        dimension_id = _snapshot_uuid(raw.get("dimension_id"), field="评分维度 ID")
        if dimension_id in dimension_rows:
            raise RecommendationSnapshotError("评分维度快照存在重复 ID")
        score = _snapshot_int(raw.get("score"), field="维度分数")
        weight = _snapshot_int(raw.get("weight_percent"), field="维度权重")
        weighted_score = _snapshot_decimal(
            raw.get("weighted_score"),
            field="维度加权分",
        )
        if score > 100 or weight > 100 or weighted_score < 0 or weighted_score > 100:
            raise RecommendationSnapshotError("评分维度快照超出允许范围")
        missing_items = _snapshot_list(raw.get("missing_items", []), field="维度缺失项")
        if not all(isinstance(item, str) for item in missing_items):
            raise RecommendationSnapshotError("维度缺失项不合法")
        row = DimensionScore(
            scoring_dimension_id=dimension_id,
            dimension_name=_snapshot_text(raw.get("name"), field="评分维度名称"),
            score=score,
            weight_percent=weight,
            weighted_score=weighted_score,
            rationale=_snapshot_text(raw.get("rationale"), field="评分理由"),
            missing_items=list(missing_items),
            sort_order=index,
        )
        screening.dimension_scores.append(row)
        dimension_rows[dimension_id] = row

    segment_map = {
        segment.segment_key: segment
        for segment in db.scalars(
            select(ResumeTextSegment).where(ResumeTextSegment.document_id == document.id)
        ).all()
    }
    raw_evidence = _snapshot_list(result.ai_evidence, field="证据快照")
    ordered_evidence: list[tuple[int, dict[str, object]]] = []
    for raw in raw_evidence:
        if not isinstance(raw, dict):
            raise RecommendationSnapshotError("证据快照不合法")
        ordered_evidence.append(
            (_snapshot_int(raw.get("sort_order"), field="证据顺序"), raw)
        )
    ordered_evidence.sort(key=lambda item: item[0])
    for index, (_, raw) in enumerate(ordered_evidence):
        subject_type = _snapshot_text(raw.get("subject_type"), field="证据主题类型")
        if subject_type not in {"profile", "hard_requirement", "dimension"}:
            raise RecommendationSnapshotError("证据主题类型不合法")
        subject_key = _snapshot_text(raw.get("subject_key"), field="证据主题")
        segment_key = _snapshot_text(raw.get("segment_key"), field="证据片段")
        segment = segment_map.get(segment_key)
        if segment is None:
            raise RecommendationSnapshotError("证据引用的简历片段不存在")
        dimension_score = None
        if subject_type == "dimension":
            dimension_score = dimension_rows.get(
                _snapshot_uuid(subject_key, field="证据评分维度 ID")
            )
            if dimension_score is None:
                raise RecommendationSnapshotError("证据引用的评分维度不存在")
        screening.evidence_citations.append(
            EvidenceCitation(
                dimension_score=dimension_score,
                segment=segment,
                subject_type=subject_type,
                subject_key=subject_key,
                segment_key=segment_key,
                quote=_snapshot_text(raw.get("quote"), field="证据原文"),
                source_type=_snapshot_text(raw.get("source_type"), field="证据来源"),
                page_number=raw.get("page_number"),
                paragraph_index=raw.get("paragraph_index"),
                sort_order=index,
            )
        )
    return screening


def _create_application(
    db: Session,
    *,
    run: TalentRecommendationRun,
    result: TalentRecommendationResult,
    candidate: Candidate,
    actor: User,
    idempotency_key: uuid.UUID,
    used_locked_stale_document: bool,
) -> TalentRecommendationSelectionItem:
    document = db.get(ResumeDocument, result.document_id)
    if document is None or document.candidate_id != candidate.id:
        return _failed(
            result.id,
            "locked_document_unavailable",
            "推荐任务锁定的共享简历已不可用",
        )
    application = JobApplication(
        candidate_id=candidate.id,
        job_id=run.job_id,
        source_type="talent_recommendation",
        talent_recommendation_run_id=run.id,
        talent_recommendation_result_id=result.id,
        primary_document_id=document.id,
    )
    application.document_links.append(
        ApplicationResumeDocument(document_id=document.id)
    )
    process = CandidateProcess(
        application=application,
        current_stage="unprocessed",
        stage_entered_at=datetime.now(UTC),
        updated_by_id=actor.id,
    )
    process.events.append(
        CandidateProcessEvent(
            sequence_number=1,
            from_stage="unprocessed",
            to_stage="unprocessed",
            reason="由人才推荐转为应聘",
            operator_id=actor.id,
        )
    )
    screening = _build_screening_result(
        db,
        application=application,
        run=run,
        result=result,
        document=document,
    )
    db.add(application)
    db.flush()
    record_audit(
        db,
        action="talent_recommendation.application_created",
        target_type="job_application",
        target_id=application.id,
        job_id=run.job_id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(idempotency_key),
            "recommendation_run_id": str(run.id),
            "recommendation_result_id": str(result.id),
            "screening_result_id": str(screening.id),
            "used_locked_stale_document": used_locked_stale_document,
        },
    )
    return TalentRecommendationSelectionItem(
        result_id=result.id,
        status="created",
        application_id=application.id,
        screening_result_id=screening.id,
    )


def select_recommended_candidates(
    db: Session,
    *,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    result_ids: list[uuid.UUID],
    confirmed_stale_result_ids: set[uuid.UUID],
    idempotency_key: uuid.UUID,
    actor: User,
) -> list[TalentRecommendationSelectionItem]:
    run = db.scalar(
        select(TalentRecommendationRun)
        .where(
            TalentRecommendationRun.id == run_id,
            TalentRecommendationRun.job_id == job_id,
        )
        .with_for_update()
    )
    if run is None:
        raise TalentRecommendationSelectionError("推荐任务不存在", status_code=404)
    if run.job.status != "active":
        raise TalentRecommendationSelectionError("已归档职位不能接收推荐候选人")
    if run.status not in {"completed", "partial"}:
        raise TalentRecommendationSelectionError("当前推荐任务不能转为应聘")
    current_criteria_id = db.scalar(
        select(JobCriteriaVersion.id)
        .where(
            JobCriteriaVersion.job_id == job_id,
            JobCriteriaVersion.status == "confirmed",
        )
        .order_by(JobCriteriaVersion.version_number.desc())
        .limit(1)
    )
    if run.criteria_stale or current_criteria_id != run.criteria_version_id:
        raise TalentRecommendationSelectionError(
            "职位筛选标准已变化，请重新创建推荐任务"
        )

    loaded_results = list(
        db.scalars(
            select(TalentRecommendationResult)
            .where(
                TalentRecommendationResult.run_id == run.id,
                TalentRecommendationResult.id.in_(result_ids),
            )
            .order_by(
                TalentRecommendationResult.resolved_candidate_id,
                TalentRecommendationResult.id,
            )
            .with_for_update()
        ).all()
    )
    candidate_ids = sorted(
        {item.resolved_candidate_id for item in loaded_results},
        key=str,
    )
    if candidate_ids:
        list(
            db.scalars(
                select(Candidate)
                .where(Candidate.id.in_(candidate_ids))
                .order_by(Candidate.id)
                .with_for_update()
            ).all()
        )

    outcomes: dict[uuid.UUID, TalentRecommendationSelectionItem] = {}
    for result in loaded_results:
        if result.status != "completed":
            outcomes[result.id] = _failed(
                result.id,
                "result_not_completed",
                "只有 AI 重评成功的候选人可以转为应聘",
            )
            continue
        candidate = _resolve_candidate(db, result.resolved_candidate_id)
        if candidate is None:
            outcomes[result.id] = _failed(
                result.id,
                "candidate_unavailable",
                "候选人主档已不可用",
            )
            continue
        existing = _existing_application(
            db,
            job_id=job_id,
            candidate_id=candidate.id,
        )
        if existing is not None:
            outcomes[result.id] = TalentRecommendationSelectionItem(
                result_id=result.id,
                status="existing",
                application_id=existing.id,
                screening_result_id=_latest_screening_result_id(db, existing.id),
            )
            continue
        try:
            has_membership = _has_active_matched_membership(
                db,
                candidate_id=candidate.id,
                matched_group_ids=result.matched_group_ids,
            )
        except RecommendationSnapshotError:
            outcomes[result.id] = _failed(
                result.id,
                "matched_groups_invalid",
                "推荐结果的人才组快照不完整",
            )
            continue
        if not has_membership:
            outcomes[result.id] = _failed(
                result.id,
                "talent_pool_membership_inactive",
                "候选人已移出本次命中的人才组",
            )
            continue
        current_document_id = _current_primary_document_id(db, candidate.id)
        document_changed = current_document_id != result.document_id
        if document_changed and result.id not in confirmed_stale_result_ids:
            outcomes[result.id] = _failed(
                result.id,
                "primary_document_changed",
                "候选人当前主简历已变化，请确认后继续使用推荐任务锁定的简历",
            )
            continue

        try:
            with db.begin_nested():
                outcome = _create_application(
                    db,
                    run=run,
                    result=result,
                    candidate=candidate,
                    actor=actor,
                    idempotency_key=idempotency_key,
                    used_locked_stale_document=document_changed,
                )
            outcomes[result.id] = outcome
        except RecommendationSnapshotError:
            outcomes[result.id] = _failed(
                result.id,
                "screening_snapshot_invalid",
                "推荐评分快照不完整，不能生成正式筛选结果",
            )
        except IntegrityError:
            existing = _existing_application(
                db,
                job_id=job_id,
                candidate_id=candidate.id,
            )
            if existing is None:
                outcomes[result.id] = _failed(
                    result.id,
                    "application_conflict",
                    "候选人应聘创建发生并发冲突，请刷新后重试",
                )
            else:
                outcomes[result.id] = TalentRecommendationSelectionItem(
                    result_id=result.id,
                    status="existing",
                    application_id=existing.id,
                    screening_result_id=_latest_screening_result_id(db, existing.id),
                )

    return [
        outcomes.get(
            result_id,
            _failed(
                result_id,
                "result_not_selectable",
                "推荐结果不存在或不属于当前任务",
            ),
        )
        for result_id in result_ids
    ]
