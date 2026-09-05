from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.evaluation.mvp import JobSpec, ResumeSpec, load_dataset
from app.models import (
    AiEvaluationDataset,
    AiEvaluationErrorCase,
    AiEvaluationResult,
    AiEvaluationRun,
    AiEvaluationSample,
    User,
)

DEFAULT_RESUME_EVALUATION_DATASET_CODE = "resume-analysis-synthetic-v1"


@dataclass(frozen=True)
class OfflineEvaluationOptions:
    model_name: str = "deterministic-evaluator"
    prompt_version: str = "synthetic-baseline-v1"
    provider: str = "local_deterministic"
    forced_error_case_keys: frozenset[str] = frozenset()


def ensure_default_resume_evaluation_dataset(
    db: Session,
    *,
    created_by: User | None = None,
) -> AiEvaluationDataset:
    """Create the fixed F13 synthetic resume evaluation dataset if it is missing."""

    source_dataset = load_dataset()
    dataset = db.scalar(
        select(AiEvaluationDataset)
        .where(AiEvaluationDataset.code == DEFAULT_RESUME_EVALUATION_DATASET_CODE)
        .options(selectinload(AiEvaluationDataset.samples))
    )
    if dataset is None:
        dataset = AiEvaluationDataset(
            code=DEFAULT_RESUME_EVALUATION_DATASET_CODE,
            name="简历评分固定合成评测集",
            scenario="resume_analysis",
            description="基于 F13 的 30 条完全合成简历，用于回归验证推荐结论、证据和格式。",
            version_number=_dataset_version_number(source_dataset.version),
            created_by=created_by,
        )
        db.add(dataset)
        db.flush()

    existing_case_keys = {sample.case_key for sample in dataset.samples}
    jobs_by_key = {job.key: job for job in source_dataset.jobs}
    for resume in source_dataset.resumes:
        if resume.id in existing_case_keys:
            continue
        job = jobs_by_key[resume.job_key]
        dataset.samples.append(
            AiEvaluationSample(
                case_key=resume.id,
                title=f"{job.title} / {resume.id}",
                scenario="resume_analysis",
                difficulty=_difficulty_for_resume(resume),
                input_payload=_sample_input_payload(job, resume),
                expected_output=_sample_expected_output(job, resume),
                expected_recommendation=_recommendation_for_expected_group(
                    resume.expected_group
                ),
                expected_evidence_keywords=[job.evidence_zh, job.evidence_en],
                tags=[resume.job_key, resume.language, resume.format, resume.scenario],
            )
        )

    db.commit()
    db.refresh(dataset)
    return dataset


async def run_offline_resume_evaluation(
    db: Session,
    *,
    dataset_id: Any | None = None,
    options: OfflineEvaluationOptions | None = None,
    created_by: User | None = None,
) -> AiEvaluationRun:
    """Run a local deterministic or live model-backed evaluation."""

    options = options or OfflineEvaluationOptions()
    if options.provider not in {"local_deterministic", "live"}:
        raise ValueError("评测 provider 仅支持 local_deterministic 或 live")
    dataset = _load_dataset_for_run(db, dataset_id=dataset_id, created_by=created_by)
    samples = [sample for sample in dataset.samples if sample.is_active]
    started_at = datetime.now(UTC)
    run = AiEvaluationRun(
        dataset=dataset,
        name=f"{dataset.name} / {options.prompt_version}",
        scenario=dataset.scenario,
        status="running",
        provider=options.provider,
        model_name=options.model_name,
        prompt_version=options.prompt_version,
        run_config={
            "mode": options.provider,
            "forced_error_case_keys": sorted(options.forced_error_case_keys),
        },
        metrics_summary={},
        total_samples=len(samples),
        started_at=started_at,
        created_by=created_by,
    )
    db.add(run)
    db.flush()

    ai_client: Any | None = None
    client_error: Exception | None = None
    if options.provider == "live":
        # Keep the import and configuration access out of module import time so that
        # local_deterministic evaluation never depends on AI settings.
        try:
            from app.services.ai_client import get_ai_client

            ai_client = get_ai_client()
            run.model_name = getattr(ai_client, "model", None) or options.model_name
        except Exception as error:  # configuration errors must be sample-level failures
            client_error = error

    error_counter: Counter[str] = Counter()
    passed_count = 0
    failed_count = 0
    error_count = 0
    score_sum = 0.0
    total_tokens = 0

    for sample in samples:
        if options.provider == "live":
            result = await _evaluate_sample_live(
                sample,
                ai_client,
                client_error=client_error,
            )
        else:
            result = await _evaluate_sample(
                sample,
                forced_error=sample.case_key in options.forced_error_case_keys,
            )
        score_sum += result.score or 0.0
        total_tokens += result.total_tokens
        if result.status == "passed":
            passed_count += 1
        elif result.status == "failed":
            failed_count += 1
            error_counter.update(result.error_types)
        else:
            error_count += 1
            error_counter.update(result.error_types or ["other"])
        stored_result = AiEvaluationResult(
            run=run,
            sample=sample,
            status=result.status,
            score=result.score,
            actual_output=result.actual_output,
            expected_snapshot=result.expected_snapshot,
            error_types=result.error_types,
            evidence_coverage_score=result.evidence_coverage_score,
            format_valid=result.format_valid,
            recommendation_matched=result.recommendation_matched,
            duration_ms=result.duration_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            failure_code=result.failure_code,
            failure_message=result.failure_message,
        )
        db.add(stored_result)
        db.flush()
        for error_type in result.error_types:
            db.add(
                AiEvaluationErrorCase(
                    result=stored_result,
                    dataset=dataset,
                    run=run,
                    sample=sample,
                    error_type=error_type,
                    severity=_severity_for_error_type(error_type),
                    title=f"{sample.case_key}：{_error_type_label(error_type)}",
                    description=(
                        result.failure_message
                        if result.status == "error" and result.failure_message
                        else _error_description(error_type)
                    ),
                    expected_behavior=_expected_behavior(sample),
                    actual_behavior=str(result.actual_output),
                )
            )

    completed_at = datetime.now(UTC)
    run.status = "succeeded" if failed_count == 0 and error_count == 0 else "failed"
    run.completed_samples = len(samples)
    run.passed_samples = passed_count
    run.failed_samples = failed_count
    run.average_score = round(score_sum / len(samples), 4) if samples else None
    run.duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
    run.completed_at = completed_at
    run.metrics_summary = {
        "pass_rate": round(passed_count / len(samples), 4) if samples else None,
        "error_count": error_count,
        "error_counts": dict(sorted(error_counter.items())),
        "total_tokens": total_tokens,
    }
    db.commit()
    db.refresh(run)
    return run


@dataclass(frozen=True)
class SampleEvaluationResult:
    status: str
    score: float
    actual_output: dict[str, object]
    expected_snapshot: dict[str, object]
    error_types: list[str]
    evidence_coverage_score: float
    format_valid: bool
    recommendation_matched: bool
    duration_ms: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    failure_code: str | None = None
    failure_message: str | None = None


def _load_dataset_for_run(
    db: Session,
    *,
    dataset_id: Any | None,
    created_by: User | None,
) -> AiEvaluationDataset:
    if dataset_id is None:
        dataset = ensure_default_resume_evaluation_dataset(db, created_by=created_by)
    else:
        dataset = db.get(AiEvaluationDataset, dataset_id)
        if dataset is None:
            raise ValueError("评测数据集不存在")
    return db.scalars(
        select(AiEvaluationDataset)
        .where(AiEvaluationDataset.id == dataset.id)
        .options(selectinload(AiEvaluationDataset.samples))
    ).one()


async def _evaluate_sample(
    sample: AiEvaluationSample,
    *,
    forced_error: bool,
) -> SampleEvaluationResult:
    """Preserve the original deterministic evaluator behind an async interface."""

    expected_recommendation = sample.expected_recommendation or "hold"
    actual_recommendation = "reject" if forced_error else expected_recommendation
    recommendation_matched = actual_recommendation == expected_recommendation
    evidence_coverage_score = 0.0 if forced_error else 1.0
    error_types: list[str] = []
    if not recommendation_matched:
        error_types.append("wrong_recommendation")
    if evidence_coverage_score < 1:
        error_types.append("evidence_missing")
    score = 1.0 if not error_types else 0.35
    status = "passed" if not error_types else "failed"
    actual_output = {
        "recommendation": actual_recommendation,
        "summary": "候选人与岗位标准匹配。" if not forced_error else "输出缺少充分证据。",
        "evidence": [] if forced_error else sample.expected_evidence_keywords,
    }
    input_tokens = _rough_token_count(sample.input_payload)
    output_tokens = _rough_token_count(actual_output)
    return SampleEvaluationResult(
        status=status,
        score=score,
        actual_output=actual_output,
        expected_snapshot=sample.expected_output,
        error_types=error_types,
        evidence_coverage_score=evidence_coverage_score,
        format_valid=True,
        recommendation_matched=recommendation_matched,
        duration_ms=8,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


async def _evaluate_sample_live(
    sample: AiEvaluationSample,
    ai_client: Any | None,
    *,
    client_error: Exception | None = None,
) -> SampleEvaluationResult:
    """Evaluate one sample with the configured model without aborting the run."""

    from app.services.ai_client import AIRequestMetrics

    started = time.perf_counter()
    try:
        if client_error is not None:
            raise client_error
        if ai_client is None:
            raise RuntimeError("未获得可用的 AI 客户端")
        payload = _live_resume_analysis_payload(sample)
        analyze_with_metrics = getattr(ai_client, "analyze_resume_with_metrics", None)
        if callable(analyze_with_metrics):
            draft, metrics = await analyze_with_metrics(payload)
        else:
            draft = await ai_client.analyze_resume(payload)
            from app.schemas.screening import ResumeAnalysisDraft

            if not isinstance(draft, ResumeAnalysisDraft):
                draft = ResumeAnalysisDraft.model_validate(draft)
            metrics = AIRequestMetrics(
                model_name=str(getattr(ai_client, "model", "unknown")),
                retry_count=0,
                duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                input_tokens=_rough_token_count(payload),
                output_tokens=_rough_token_count(draft.model_dump(mode="json")),
                total_tokens=None,
            )
        return _live_result_from_draft(sample, draft, metrics)
    except Exception as error:
        failure_code, error_type = _live_failure_details(error)
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        return SampleEvaluationResult(
            status="error",
            score=0.0,
            actual_output={"error": str(error)},
            expected_snapshot=sample.expected_output,
            error_types=[error_type],
            evidence_coverage_score=0.0,
            format_valid=False,
            recommendation_matched=False,
            duration_ms=duration_ms,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            failure_code=failure_code,
            failure_message=str(error) or "AI 评测样本调用失败",
        )


def _live_resume_analysis_payload(sample: AiEvaluationSample) -> dict[str, object]:
    """Adapt the stored {job, resume} spec to the normal resume-analysis contract."""

    job = sample.input_payload.get("job")
    resume = sample.input_payload.get("resume")
    if not isinstance(job, dict) or not isinstance(resume, dict):
        raise ValueError("评测样本 input_payload 缺少 job/resume spec")
    candidate_code = str(resume.get("id") or sample.case_key)
    job_key = str(job.get("key") or sample.case_key)
    requirement_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"smarthr-evaluation:{job_key}:hard"))
    dimension_specs = job.get("dimensions")
    if not isinstance(dimension_specs, list):
        dimension_specs = []
    scoring_dimensions: list[dict[str, object]] = []
    for index, dimension in enumerate(dimension_specs):
        if not isinstance(dimension, dict):
            continue
        dimension_id = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"smarthr-evaluation:{job_key}:dimension:{index}")
        )
        scoring_dimensions.append(
            {
                "dimension_id": dimension_id,
                "name": str(dimension.get("name") or f"维度 {index + 1}"),
                "description": str(dimension.get("description") or "根据简历内容评估"),
                "weight_percent": int(dimension.get("weight_percent") or 0),
            }
        )
    hard_status = str(resume.get("hard_status") or "unknown")
    hard_value = str(job.get("hard_requirement_value") or "未提供")
    status_statement = {
        "passed": "候选人明确满足该硬性要求。",
        "failed": "候选人明确不满足该硬性要求。",
        "unknown": "简历未提供足以确认该硬性要求的信息。",
    }.get(hard_status, "简历未提供足以确认该硬性要求的信息。")
    evidence = "；".join(
        value
        for value in (
            str(job.get("evidence_zh") or ""),
            str(job.get("evidence_en") or ""),
        )
        if value
    )
    resume_text = (
        f"合成候选人 {candidate_code} 应聘 {job.get('title', '未命名岗位')}。"
        f"{status_statement}岗位要求：{job.get('hard_requirement_title', '硬性要求')}，"
        f"{hard_value}。评测场景：{resume.get('scenario', '未提供')}；"
        f"参考匹配分数：{resume.get('score', 0)}。"
        f"关键岗位证据提示：{evidence or '未提供'}。"
    )
    return {
        "candidate_code": candidate_code,
        "segments": [{"segment_key": "SEG-0001", "text": resume_text}],
        "criteria": {
            "criteria_version_id": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"smarthr-evaluation:{job_key}:criteria")
            ),
            "pass_threshold": 70,
            "hard_requirements": [
                {
                    "requirement_id": requirement_id,
                    "requirement_type": "other",
                    "title": str(job.get("hard_requirement_title") or "硬性要求"),
                    "description": hard_value,
                    "expected_value": hard_value,
                    "auto_reject": True,
                }
            ],
            "scoring_dimensions": scoring_dimensions,
        },
    }


def _live_result_from_draft(
    sample: AiEvaluationSample,
    draft: Any,
    metrics: Any,
) -> SampleEvaluationResult:
    output = draft.model_dump(mode="json")
    job = sample.input_payload.get("job")
    dimensions = job.get("dimensions", []) if isinstance(job, dict) else []
    job_key = str(job.get("key", sample.case_key)) if isinstance(job, dict) else sample.case_key
    weights = {
        str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"smarthr-evaluation:{job_key}:dimension:{index}",
            )
        ): int(item.get("weight_percent") or 0)
        for index, item in enumerate(dimensions)
        if isinstance(item, dict)
    }
    hard_statuses = [item.status for item in draft.hard_requirements]
    weighted_score: float | None = None
    if "failed" in hard_statuses:
        recommendation = "reject"
    else:
        weight_total = sum(
            weights.get(str(item.dimension_id), 0) for item in draft.dimension_scores
        )
        if weight_total:
            weighted_score = sum(
                item.score * weights.get(str(item.dimension_id), 0)
                for item in draft.dimension_scores
            ) / weight_total
        else:
            weighted_score = sum(item.score for item in draft.dimension_scores) / len(
                draft.dimension_scores
            )
        recommendation = "recommend" if weighted_score >= 70 else "hold"
    output["recommendation"] = recommendation
    output["weighted_score"] = round(weighted_score, 2) if weighted_score is not None else None
    evidence_count = sum(len(item.evidence) for item in draft.hard_requirements) + sum(
        len(item.evidence) for item in draft.dimension_scores
    )
    evidence_coverage_score = 1.0 if evidence_count or draft.gaps else 0.0
    expected_recommendation = sample.expected_recommendation or "hold"
    recommendation_matched = recommendation == expected_recommendation
    error_types: list[str] = []
    if not recommendation_matched:
        error_types.append("wrong_recommendation")
    if evidence_coverage_score < 1:
        error_types.append("evidence_missing")
    score = 1.0 if not error_types else 0.35
    return SampleEvaluationResult(
        status="passed" if not error_types else "failed",
        score=score,
        actual_output=output,
        expected_snapshot=sample.expected_output,
        error_types=error_types,
        evidence_coverage_score=evidence_coverage_score,
        format_valid=True,
        recommendation_matched=recommendation_matched,
        duration_ms=int(getattr(metrics, "duration_ms", 0) or 0),
        input_tokens=int(getattr(metrics, "input_tokens", 0) or 0),
        output_tokens=int(getattr(metrics, "output_tokens", 0) or 0),
        total_tokens=(
            int(getattr(metrics, "total_tokens", 0) or 0)
            or int(getattr(metrics, "input_tokens", 0) or 0)
            + int(getattr(metrics, "output_tokens", 0) or 0)
        ),
    )


def _live_failure_details(error: Exception) -> tuple[str, str]:
    from app.services.ai_client import (
        AIClientError,
        AIConfigurationError,
        AIRequestTimeout,
        AIResponseValidationError,
    )

    if isinstance(error, AIConfigurationError):
        return "ai_configuration_error", "other"
    if isinstance(error, AIRequestTimeout):
        return "ai_request_timeout", "timeout"
    if isinstance(error, AIResponseValidationError):
        return "ai_response_validation_error", "format_error"
    if isinstance(error, ValidationError):
        return "validation_error", "format_error"
    if isinstance(error, AIClientError):
        return "ai_client_error", "other"
    if isinstance(error, ValueError):
        return "invalid_evaluation_payload", "format_error"
    return "unexpected_error", "other"


def _dataset_version_number(version: str) -> int:
    digits = "".join(character for character in version if character.isdigit())
    return int(digits or "1")


def _difficulty_for_resume(resume: ResumeSpec) -> str:
    if resume.scenario in {"hard_failure", "ambiguous_context"}:
        return "hard"
    if resume.scenario == "missing_information":
        return "medium"
    return "easy"


def _sample_input_payload(job: JobSpec, resume: ResumeSpec) -> dict[str, object]:
    return {
        "job": job.model_dump(mode="json"),
        "resume": resume.model_dump(mode="json"),
    }


def _sample_expected_output(job: JobSpec, resume: ResumeSpec) -> dict[str, object]:
    return {
        "expected_group": resume.expected_group,
        "expected_recommendation": _recommendation_for_expected_group(resume.expected_group),
        "expected_score": resume.score,
        "hard_status": resume.hard_status,
        "required_evidence": [job.evidence_zh, job.evidence_en],
    }


def _recommendation_for_expected_group(expected_group: str) -> str:
    if expected_group == "passed":
        return "recommend"
    if expected_group == "auto_rejected":
        return "reject"
    return "hold"


def _severity_for_error_type(error_type: str) -> str:
    if error_type in {"hallucination", "wrong_recommendation"}:
        return "high"
    if error_type in {"format_error", "evidence_missing", "risk_omission"}:
        return "medium"
    return "low"


def _error_type_label(error_type: str) -> str:
    labels = {
        "wrong_recommendation": "推荐结论错误",
        "evidence_missing": "证据不足",
        "hallucination": "幻觉",
        "format_error": "格式错误",
        "risk_omission": "风险遗漏",
        "timeout": "超时",
        "other": "其他错误",
    }
    return labels.get(error_type, "未知错误")


def _error_description(error_type: str) -> str:
    descriptions = {
        "wrong_recommendation": "实际推荐结论与评测期望不一致，需要复盘 Prompt 或模型行为。",
        "evidence_missing": "输出没有覆盖评测样本要求的关键证据。",
        "hallucination": "输出包含输入中不存在的信息。",
        "format_error": "输出没有满足结构化格式要求。",
        "risk_omission": "输出遗漏了应提示的候选人风险。",
        "timeout": "模型调用或任务执行超时。",
        "other": "未归类错误，需要人工复盘。",
    }
    return descriptions.get(error_type, descriptions["other"])


def _expected_behavior(sample: AiEvaluationSample) -> str:
    expected = sample.expected_output
    return (
        f"应输出 {expected.get('expected_recommendation')}，"
        f"并引用 {', '.join(sample.expected_evidence_keywords)}。"
    )


def _rough_token_count(payload: object) -> int:
    return max(1, len(str(payload)) // 4)
