from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.database import SessionLocal
from app.models import (
    CandidateProfile,
    ResumeDocument,
    ResumeTextSegment,
    TalentRecommendationResult,
    TalentRecommendationRun,
)
from app.schemas.screening import CandidateProfileDraft, EvidenceReference, ResumeAnalysisDraft
from app.services.ai_client import (
    RESUME_MATCH_PROMPT_VERSION,
    AIConfigurationError,
    AIRequestTimeout,
    AIResponseValidationError,
    AIUpstreamError,
    OpenAICompatibleClient,
    get_ai_client,
)
from app.services.audit import record_audit
from app.services.model_payload import (
    ModelPayloadSecurityError,
    build_resume_analysis_payload_from_snapshot,
)
from app.services.resume_analysis import (
    AnalysisContractError,
    _find_source_quote,
    _profile_draft,
    _profile_evidence,
)
from app.services.talent_recommendation import (
    _append_event,
    _find_event,
    get_run_for_update,
)

logger = logging.getLogger(__name__)
SessionFactory = sessionmaker[Session]


class TalentRecommendationRescoringError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _load_document(db: Session, document_id: uuid.UUID) -> ResumeDocument | None:
    return db.scalar(
        select(ResumeDocument)
        .where(ResumeDocument.id == document_id)
        .options(
            selectinload(ResumeDocument.text_segments).selectinload(
                ResumeTextSegment.redactions
            )
        )
    )


def _criteria_contract(
    criteria_snapshot: dict[str, object],
) -> tuple[
    int,
    dict[uuid.UUID, dict[str, object]],
    dict[uuid.UUID, dict[str, object]],
]:
    try:
        pass_threshold = int(criteria_snapshot["pass_threshold"])
        hard_items = criteria_snapshot["hard_requirements"]
        dimension_items = criteria_snapshot["scoring_dimensions"]
    except (KeyError, TypeError, ValueError) as error:
        raise AnalysisContractError("推荐运行的筛选标准快照不完整") from error
    if not 0 <= pass_threshold <= 100:
        raise AnalysisContractError("推荐运行的通过分数不合法")
    if not isinstance(hard_items, list) or not isinstance(dimension_items, list):
        raise AnalysisContractError("推荐运行的筛选标准快照格式不合法")

    requirements: dict[uuid.UUID, dict[str, object]] = {}
    for raw_item in hard_items:
        if not isinstance(raw_item, dict):
            raise AnalysisContractError("推荐运行的硬性条件快照格式不合法")
        try:
            item_id = uuid.UUID(str(raw_item["requirement_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise AnalysisContractError("推荐运行的硬性条件 ID 不合法") from error
        if item_id in requirements:
            raise AnalysisContractError("推荐运行的硬性条件快照存在重复 ID")
        requirements[item_id] = raw_item

    dimensions: dict[uuid.UUID, dict[str, object]] = {}
    weight_total = 0
    for raw_item in dimension_items:
        if not isinstance(raw_item, dict):
            raise AnalysisContractError("推荐运行的评分维度快照格式不合法")
        try:
            item_id = uuid.UUID(str(raw_item["dimension_id"]))
            weight = int(raw_item["weight_percent"])
        except (KeyError, TypeError, ValueError) as error:
            raise AnalysisContractError("推荐运行的评分维度快照不完整") from error
        if item_id in dimensions:
            raise AnalysisContractError("推荐运行的评分维度快照存在重复 ID")
        dimensions[item_id] = raw_item
        weight_total += weight
    if not dimensions or weight_total != 100:
        raise AnalysisContractError("推荐运行的评分维度权重总和不是 100%")
    return pass_threshold, requirements, dimensions


def _segment_map_for_mode(
    document: ResumeDocument,
    ai_input_mode: str,
) -> dict[str, tuple[ResumeTextSegment, str]]:
    result: dict[str, tuple[ResumeTextSegment, str]] = {}
    for segment in document.text_segments:
        text = segment.redacted_text if ai_input_mode == "redacted" else segment.normalized_text
        if text is None:
            raise ModelPayloadSecurityError(f"片段 {segment.segment_key} 缺少可用文本")
        result[segment.segment_key] = (segment, text)
    return result


def _validate_evidence(
    evidence: Iterable[EvidenceReference],
    segment_map: dict[str, tuple[ResumeTextSegment, str]],
) -> None:
    for citation in evidence:
        segment_entry = segment_map.get(citation.segment_key)
        if segment_entry is None:
            raise AnalysisContractError(f"证据片段不存在：{citation.segment_key}")
        source_quote = _find_source_quote(segment_entry[1], citation.quote.strip())
        if source_quote is None:
            raise AnalysisContractError(
                f"证据引用不属于对应简历片段：{citation.segment_key}"
            )
        citation.quote = source_quote


def _validate_analysis(
    analysis: ResumeAnalysisDraft,
    *,
    criteria_snapshot: dict[str, object],
    document: ResumeDocument,
    profile: CandidateProfile,
    ai_input_mode: str,
) -> tuple[
    int,
    dict[uuid.UUID, dict[str, object]],
    dict[uuid.UUID, dict[str, object]],
    CandidateProfileDraft,
    dict[str, tuple[ResumeTextSegment, str]],
]:
    pass_threshold, requirements, dimensions = _criteria_contract(criteria_snapshot)
    if {item.requirement_id for item in analysis.hard_requirements} != set(requirements):
        raise AnalysisContractError("模型没有完整返回推荐任务的硬性条件判断")
    if {item.dimension_id for item in analysis.dimension_scores} != set(dimensions):
        raise AnalysisContractError("模型没有完整返回推荐任务的评分维度")

    profile_data = _profile_draft(profile)
    segment_map = _segment_map_for_mode(document, ai_input_mode)
    for _, evidence in _profile_evidence(profile_data):
        _validate_evidence(evidence, segment_map)
    for judgment in analysis.hard_requirements:
        _validate_evidence(judgment.evidence, segment_map)
    for dimension in analysis.dimension_scores:
        _validate_evidence(dimension.evidence, segment_map)
    return pass_threshold, requirements, dimensions, profile_data, segment_map


def _evidence_snapshot(
    *,
    analysis: ResumeAnalysisDraft,
    profile_data: CandidateProfileDraft,
    segment_map: dict[str, tuple[ResumeTextSegment, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    def append_rows(
        subject_type: str,
        subject_key: str,
        evidence: Iterable[EvidenceReference],
    ) -> None:
        for reference in evidence:
            segment = segment_map[reference.segment_key][0]
            rows.append(
                {
                    "subject_type": subject_type,
                    "subject_key": subject_key,
                    "segment_key": reference.segment_key,
                    "quote": reference.quote,
                    "source_type": segment.source_type,
                    "page_number": segment.page_number,
                    "paragraph_index": segment.paragraph_index,
                    "sort_order": len(rows),
                }
            )

    for subject_key, evidence in _profile_evidence(profile_data):
        append_rows("profile", subject_key, evidence)
    for judgment in analysis.hard_requirements:
        append_rows("hard_requirement", str(judgment.requirement_id), judgment.evidence)
    for dimension in analysis.dimension_scores:
        append_rows("dimension", str(dimension.dimension_id), dimension.evidence)
    return rows


def _analysis_snapshot(
    analysis: ResumeAnalysisDraft,
    *,
    pass_threshold: int,
    requirements: dict[uuid.UUID, dict[str, object]],
    dimensions: dict[uuid.UUID, dict[str, object]],
    profile_data: CandidateProfileDraft,
    segment_map: dict[str, tuple[ResumeTextSegment, str]],
) -> dict[str, object]:
    hard_results: list[dict[str, object]] = []
    auto_rejected = False
    for judgment in analysis.hard_requirements:
        requirement = requirements[judgment.requirement_id]
        auto_reject = bool(requirement.get("auto_reject"))
        auto_rejected = auto_rejected or (
            auto_reject and judgment.status == "failed"
        )
        hard_results.append(
            {
                "requirement_id": str(judgment.requirement_id),
                "requirement_type": str(requirement.get("requirement_type") or ""),
                "title": str(requirement.get("title") or ""),
                "expected_value": str(requirement.get("expected_value") or ""),
                "auto_reject": auto_reject,
                "status": judgment.status,
                "rationale": judgment.rationale,
                "evidence_segment_keys": [
                    item.segment_key for item in judgment.evidence
                ],
            }
        )

    dimension_rows: list[dict[str, object]] = []
    total_score = Decimal("0")
    for score in analysis.dimension_scores:
        dimension = dimensions[score.dimension_id]
        weight = int(dimension["weight_percent"])
        weighted_score = (
            Decimal(score.score) * Decimal(weight) / Decimal(100)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_score += weighted_score
        dimension_rows.append(
            {
                "dimension_id": str(score.dimension_id),
                "name": str(dimension.get("name") or ""),
                "score": score.score,
                "weight_percent": weight,
                "weighted_score": float(weighted_score),
                "rationale": score.rationale,
                "missing_items": score.missing_items,
                "sort_order": int(dimension.get("sort_order") or 0),
            }
        )
    total_score = total_score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if auto_rejected:
        ai_group = "auto_rejected"
    elif total_score < Decimal(pass_threshold):
        ai_group = "low_match"
    else:
        ai_group = "passed"

    return {
        "ai_score": total_score,
        "ai_group": ai_group,
        "ai_dimension_scores": dimension_rows,
        "ai_hard_requirement_results": hard_results,
        "ai_strengths": analysis.strengths,
        "ai_gaps": analysis.gaps,
        "ai_missing_items": analysis.missing_items,
        "ai_interview_questions": analysis.interview_questions,
        "ai_evidence": _evidence_snapshot(
            analysis=analysis,
            profile_data=profile_data,
            segment_map=segment_map,
        ),
    }


def _failure_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, TalentRecommendationRescoringError):
        return error.code, error.message
    if isinstance(error, ModelPayloadSecurityError):
        return "unsafe_model_payload", str(error)
    if isinstance(error, AIConfigurationError):
        return "ai_not_configured", str(error)
    if isinstance(error, AIRequestTimeout):
        return "ai_timeout", str(error)
    if isinstance(error, AIResponseValidationError | AnalysisContractError):
        return "ai_invalid_response", str(error)
    if isinstance(error, AIUpstreamError):
        return "ai_upstream_failed", str(error)
    return "ai_rescoring_failed", "人才推荐 AI 重评失败，请稍后重试"


def _prepare_results(
    run_id: uuid.UUID,
    *,
    task_id: str,
    retry_failed_only: bool,
    client: OpenAICompatibleClient,
    session_factory: SessionFactory,
) -> tuple[str, list[uuid.UUID]]:
    with session_factory() as db:
        initial = db.get(TalentRecommendationRun, run_id)
        if initial is None:
            return "missing", []
        run = get_run_for_update(db, job_id=initial.job_id, run_id=run_id)
        if run.celery_task_id != task_id:
            return "superseded", []
        if run.status == "cancelled":
            return "cancelled", []
        expected_status = "partial" if retry_failed_only else "rescoring"
        if run.status != expected_status:
            return run.status, []
        if run.criteria_stale:
            raise TalentRecommendationRescoringError(
                "criteria_stale_before_rescoring",
                "职位筛选标准已经变化，请创建新的推荐任务",
            )
        if run.ai_model_snapshot != client.model:
            raise TalentRecommendationRescoringError(
                "ai_configuration_changed",
                "AI 模型配置与推荐运行快照不一致，请创建新的推荐任务",
            )
        if run.prompt_version_snapshot != RESUME_MATCH_PROMPT_VERSION:
            raise TalentRecommendationRescoringError(
                "prompt_configuration_changed",
                "AI Prompt 版本与推荐运行快照不一致，请创建新的推荐任务",
            )

        status_filter = (
            ("failed",) if retry_failed_only else ("retrieved", "rescoring")
        )
        selected = list(
            db.scalars(
                select(TalentRecommendationResult)
                .where(
                    TalentRecommendationResult.run_id == run.id,
                    TalentRecommendationResult.vector_rank <= run.rescore_limit,
                    TalentRecommendationResult.status.in_(status_filter),
                )
                .order_by(TalentRecommendationResult.vector_rank)
                .with_for_update()
            ).all()
        )
        previous_status = run.status
        if retry_failed_only:
            run.status = "rescoring"
            run.completed_at = None
            run.failure_code = None
            run.failure_summary = None
        for result in selected:
            result.status = "rescoring"
            result.processing_attempt_count += 1
            result.failure_code = None
            result.failure_message = None
            result.completed_at = None
        event_key = uuid.uuid5(run.id, f"rescoring-started:{task_id}")
        if _find_event(db, run.id, event_key) is None:
            _append_event(
                db,
                run=run,
                idempotency_key=event_key,
                event_type="rescoring_started",
                from_status=previous_status,
                to_status="rescoring",
                details={
                    "retry_failed_only": retry_failed_only,
                    "selected_count": len(selected),
                },
                actor=None,
            )
        run.resource_version += 1
        record_audit(
            db,
            action="talent_recommendation.rescoring_started",
            target_type="talent_recommendation_run",
            target_id=run.id,
            job_id=run.job_id,
            result="success",
            actor_username="celery-worker",
            details={
                "retry_failed_only": retry_failed_only,
                "selected_count": len(selected),
            },
        )
        result_ids = [item.id for item in selected]
        db.commit()
        return "rescoring", result_ids


def _mark_result_failed(
    result_id: uuid.UUID,
    *,
    task_id: str,
    error: Exception,
    session_factory: SessionFactory,
) -> str:
    failure_code, failure_message = _failure_details(error)
    with session_factory() as db:
        result = db.get(TalentRecommendationResult, result_id)
        if result is None:
            return "missing"
        run = get_run_for_update(db, job_id=result.run.job_id, run_id=result.run_id)
        if run.celery_task_id != task_id:
            return "superseded"
        if run.status == "cancelled":
            if result.status == "rescoring":
                result.status = "retrieved"
                result.completed_at = None
                db.commit()
            return "cancelled"
        if result.status == "completed":
            return "completed"
        result.status = "failed"
        result.failure_code = failure_code
        result.failure_message = failure_message[:2_000]
        result.completed_at = datetime.now(UTC)
        record_audit(
            db,
            action="talent_recommendation.result_rescoring_failed",
            target_type="talent_recommendation_result",
            target_id=result.id,
            job_id=run.job_id,
            result="failure",
            actor_username="celery-worker",
            details={"failure_code": failure_code, "vector_rank": result.vector_rank},
        )
        db.commit()
    return "failed"


def _mark_preparation_failed(
    run_id: uuid.UUID,
    *,
    task_id: str,
    retry_failed_only: bool,
    error: Exception,
    session_factory: SessionFactory,
) -> dict[str, Any]:
    failure_code, failure_message = _failure_details(error)
    with session_factory() as db:
        initial = db.get(TalentRecommendationRun, run_id)
        if initial is None:
            return {"status": "missing", "run_id": str(run_id)}
        run = get_run_for_update(db, job_id=initial.job_id, run_id=run_id)
        if run.celery_task_id != task_id:
            return {"status": "superseded", "run_id": str(run.id)}
        if run.status == "cancelled":
            return {"status": "cancelled", "run_id": str(run.id)}
        status_filter = (
            ("failed", "rescoring")
            if retry_failed_only
            else ("retrieved", "rescoring")
        )
        results = list(
            db.scalars(
                select(TalentRecommendationResult)
                .where(
                    TalentRecommendationResult.run_id == run.id,
                    TalentRecommendationResult.vector_rank <= run.rescore_limit,
                    TalentRecommendationResult.status.in_(status_filter),
                )
                .with_for_update()
            ).all()
        )
        now = datetime.now(UTC)
        for result in results:
            result.status = "failed"
            result.processing_attempt_count += 1
            result.failure_code = failure_code
            result.failure_message = failure_message[:2_000]
            result.completed_at = now
        db.commit()
    return _finalize_run(
        run_id,
        task_id=task_id,
        session_factory=session_factory,
    )


def _cleanup_cancelled_results(
    run_id: uuid.UUID,
    *,
    task_id: str,
    session_factory: SessionFactory,
) -> None:
    with session_factory() as db:
        run = db.get(TalentRecommendationRun, run_id)
        if (
            run is None
            or run.celery_task_id != task_id
            or run.status != "cancelled"
        ):
            return
        pending = list(
            db.scalars(
                select(TalentRecommendationResult).where(
                    TalentRecommendationResult.run_id == run.id,
                    TalentRecommendationResult.status == "rescoring",
                )
            ).all()
        )
        for result in pending:
            result.status = "retrieved"
            result.completed_at = None
        db.commit()


async def _process_result(
    result_id: uuid.UUID,
    *,
    run_id: uuid.UUID,
    task_id: str,
    client: OpenAICompatibleClient,
    session_factory: SessionFactory,
) -> str:
    try:
        with session_factory() as db:
            result = db.get(TalentRecommendationResult, result_id)
            run = db.get(TalentRecommendationRun, run_id)
            if result is None or run is None:
                return "missing"
            if run.celery_task_id != task_id:
                return "superseded"
            if run.status == "cancelled":
                return "cancelled"
            document = _load_document(db, result.document_id)
            profile = db.get(CandidateProfile, result.candidate_profile_id)
            if document is None or profile is None:
                raise TalentRecommendationRescoringError(
                    "locked_input_missing",
                    "推荐运行锁定的简历或候选人档案不存在",
                )
            payload = build_resume_analysis_payload_from_snapshot(
                document,
                run.criteria_snapshot,
                profile,
                ai_input_mode=run.ai_input_mode,
                candidate_code=result.candidate_code_snapshot,
            )
            criteria_snapshot = dict(run.criteria_snapshot)
            ai_input_mode = run.ai_input_mode

        analysis = await client.analyze_resume(payload)
        try:
            with session_factory() as db:
                document = _load_document(db, result.document_id)
                profile = db.get(CandidateProfile, result.candidate_profile_id)
                if document is None or profile is None:
                    raise TalentRecommendationRescoringError(
                        "locked_input_missing",
                        "推荐运行锁定的简历或候选人档案不存在",
                    )
                _validate_analysis(
                    analysis,
                    criteria_snapshot=criteria_snapshot,
                    document=document,
                    profile=profile,
                    ai_input_mode=ai_input_mode,
                )
        except AnalysisContractError as error:
            logger.warning(
                "人才推荐 AI 合同校验失败，准备纠正重试，run_id=%s result_id=%s",
                run_id,
                result_id,
            )
            analysis = await client.analyze_resume(
                payload,
                validation_feedback=str(error),
                previous_analysis=analysis.model_dump(mode="json"),
            )

        with session_factory() as db:
            current = db.get(TalentRecommendationResult, result_id)
            if current is None:
                return "missing"
            run = get_run_for_update(db, job_id=current.run.job_id, run_id=run_id)
            if run.celery_task_id != task_id:
                return "superseded"
            if run.status == "cancelled":
                current.status = "retrieved"
                current.completed_at = None
                db.commit()
                return "cancelled"
            if run.criteria_stale:
                raise TalentRecommendationRescoringError(
                    "criteria_stale_during_rescoring",
                    "职位筛选标准在 AI 重评期间发生变化，请创建新的推荐任务",
                )
            if current.status == "completed":
                return "completed"
            document = _load_document(db, current.document_id)
            profile = db.get(CandidateProfile, current.candidate_profile_id)
            if document is None or profile is None:
                raise TalentRecommendationRescoringError(
                    "locked_input_missing",
                    "推荐运行锁定的简历或候选人档案不存在",
                )
            (
                pass_threshold,
                requirements,
                dimensions,
                profile_data,
                segment_map,
            ) = _validate_analysis(
                analysis,
                criteria_snapshot=run.criteria_snapshot,
                document=document,
                profile=profile,
                ai_input_mode=run.ai_input_mode,
            )
            snapshot = _analysis_snapshot(
                analysis,
                pass_threshold=pass_threshold,
                requirements=requirements,
                dimensions=dimensions,
                profile_data=profile_data,
                segment_map=segment_map,
            )
            current.status = "completed"
            current.ai_score = snapshot["ai_score"]  # type: ignore[assignment]
            current.ai_group = str(snapshot["ai_group"])
            current.ai_dimension_scores = snapshot["ai_dimension_scores"]  # type: ignore[assignment]
            current.ai_hard_requirement_results = snapshot[
                "ai_hard_requirement_results"
            ]  # type: ignore[assignment]
            current.ai_strengths = snapshot["ai_strengths"]  # type: ignore[assignment]
            current.ai_gaps = snapshot["ai_gaps"]  # type: ignore[assignment]
            current.ai_missing_items = snapshot["ai_missing_items"]  # type: ignore[assignment]
            current.ai_interview_questions = snapshot[
                "ai_interview_questions"
            ]  # type: ignore[assignment]
            current.ai_evidence = snapshot["ai_evidence"]  # type: ignore[assignment]
            current.ai_model_snapshot = run.ai_model_snapshot
            current.prompt_version_snapshot = run.prompt_version_snapshot
            current.failure_code = None
            current.failure_message = None
            current.completed_at = datetime.now(UTC)
            record_audit(
                db,
                action="talent_recommendation.result_rescored",
                target_type="talent_recommendation_result",
                target_id=current.id,
                job_id=run.job_id,
                result="success",
                actor_username="celery-worker",
                details={
                    "vector_rank": current.vector_rank,
                    "ai_group": current.ai_group,
                    "ai_score": float(current.ai_score),
                },
            )
            db.commit()
            return "completed"
    except (
        TalentRecommendationRescoringError,
        ModelPayloadSecurityError,
        AIConfigurationError,
        AIRequestTimeout,
        AIResponseValidationError,
        AIUpstreamError,
        AnalysisContractError,
    ) as error:
        return _mark_result_failed(
            result_id,
            task_id=task_id,
            error=error,
            session_factory=session_factory,
        )
    except Exception as error:
        logger.exception(
            "人才推荐 AI 重评出现未预期错误，run_id=%s result_id=%s",
            run_id,
            result_id,
        )
        return _mark_result_failed(
            result_id,
            task_id=task_id,
            error=error,
            session_factory=session_factory,
        )


def _finalize_run(
    run_id: uuid.UUID,
    *,
    task_id: str,
    session_factory: SessionFactory,
) -> dict[str, Any]:
    with session_factory() as db:
        initial = db.get(TalentRecommendationRun, run_id)
        if initial is None:
            return {"status": "missing", "run_id": str(run_id)}
        run = get_run_for_update(db, job_id=initial.job_id, run_id=run_id)
        if run.celery_task_id != task_id:
            return {"status": "superseded", "run_id": str(run.id)}
        if run.status == "cancelled":
            return {"status": "cancelled", "run_id": str(run.id)}

        selected_results = list(
            db.scalars(
                select(TalentRecommendationResult).where(
                    TalentRecommendationResult.run_id == run.id,
                    TalentRecommendationResult.vector_rank <= run.rescore_limit,
                )
            ).all()
        )
        completed_count = sum(item.status == "completed" for item in selected_results)
        failed_count = sum(item.status == "failed" for item in selected_results)
        rescored_count = completed_count + failed_count
        run.rescored_count = rescored_count
        run.completed_count = completed_count
        run.failed_count = failed_count
        previous_status = run.status
        if failed_count == 0:
            run.status = "completed"
            run.failure_code = None
            run.failure_summary = None
        elif completed_count > 0:
            run.status = "partial"
            run.failure_code = "ai_rescoring_partial"
            run.failure_summary = f"{failed_count} 名候选人 AI 重评失败"
        else:
            run.status = "failed"
            run.failure_code = "ai_rescoring_failed"
            run.failure_summary = "全部候选人 AI 重评失败"
        run.completed_at = datetime.now(UTC)
        run.resource_version += 1
        event_key = uuid.uuid5(run.id, f"rescoring-finished:{task_id}")
        if _find_event(db, run.id, event_key) is None:
            _append_event(
                db,
                run=run,
                idempotency_key=event_key,
                event_type=run.status,
                from_status=previous_status,
                to_status=run.status,
                details={
                    "rescored_count": rescored_count,
                    "completed_count": completed_count,
                    "failed_count": failed_count,
                },
                actor=None,
            )
        record_audit(
            db,
            action="talent_recommendation.rescoring_finished",
            target_type="talent_recommendation_run",
            target_id=run.id,
            job_id=run.job_id,
            result="success" if run.status == "completed" else "failure",
            actor_username="celery-worker",
            details={
                "status": run.status,
                "rescored_count": rescored_count,
                "completed_count": completed_count,
                "failed_count": failed_count,
            },
        )
        db.commit()
        return {
            "status": run.status,
            "run_id": str(run.id),
            "rescored_count": rescored_count,
            "completed_count": completed_count,
            "failed_count": failed_count,
        }


async def rescore_talent_recommendations(
    run_id: uuid.UUID,
    *,
    task_id: str,
    retry_failed_only: bool = False,
    session_factory: SessionFactory = SessionLocal,
    ai_client: OpenAICompatibleClient | None = None,
) -> dict[str, Any]:
    client = ai_client or get_ai_client()
    try:
        status, result_ids = _prepare_results(
            run_id,
            task_id=task_id,
            retry_failed_only=retry_failed_only,
            client=client,
            session_factory=session_factory,
        )
    except Exception as error:
        logger.warning(
            "人才推荐 AI 重评准备失败，run_id=%s failure_code=%s",
            run_id,
            _failure_details(error)[0],
        )
        return _mark_preparation_failed(
            run_id,
            task_id=task_id,
            retry_failed_only=retry_failed_only,
            error=error,
            session_factory=session_factory,
        )
    if status != "rescoring":
        return {"status": status, "run_id": str(run_id)}

    for result_id in result_ids:
        outcome = await _process_result(
            result_id,
            run_id=run_id,
            task_id=task_id,
            client=client,
            session_factory=session_factory,
        )
        if outcome in {"cancelled", "superseded"}:
            if outcome == "cancelled":
                _cleanup_cancelled_results(
                    run_id,
                    task_id=task_id,
                    session_factory=session_factory,
                )
            return {"status": outcome, "run_id": str(run_id)}
    return _finalize_run(
        run_id,
        task_id=task_id,
        session_factory=session_factory,
    )
