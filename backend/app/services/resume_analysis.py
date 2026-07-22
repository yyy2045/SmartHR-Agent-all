from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.database import SessionLocal
from app.models import (
    CandidateProfile,
    DimensionScore,
    EvidenceCitation,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeTextSegment,
    ScreeningBatch,
    ScreeningResult,
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
    build_resume_analysis_payload,
)

logger = logging.getLogger(__name__)
SessionFactory = sessionmaker[Session]
AI_GROUP_PRIORITY = {"passed": 0, "low_match": 1, "auto_rejected": 2}


class AnalysisContractError(RuntimeError):
    pass


def screening_result_sort_key(result: ScreeningResult) -> tuple[int, Decimal]:
    priority = AI_GROUP_PRIORITY.get(result.ai_group or "", 3)
    score = Decimal(str(result.total_score)) if result.total_score is not None else Decimal("-1")
    return priority, -score


def _document_options() -> tuple[object, ...]:
    criteria = selectinload(ResumeDocument.batch).selectinload(
        ScreeningBatch.criteria_version
    )
    return (
        selectinload(ResumeDocument.text_segments).selectinload(
            ResumeTextSegment.redactions
        ),
        criteria.selectinload(JobCriteriaVersion.hard_requirements),
        criteria.selectinload(JobCriteriaVersion.scoring_dimensions),
    )


def _load_document(db: Session, document_id: uuid.UUID) -> ResumeDocument | None:
    return db.scalar(
        select(ResumeDocument)
        .where(ResumeDocument.id == document_id)
        .options(*_document_options())
    )


def _load_criteria(
    db: Session,
    criteria_version_id: uuid.UUID,
) -> JobCriteriaVersion | None:
    return db.scalar(
        select(JobCriteriaVersion)
        .where(JobCriteriaVersion.id == criteria_version_id)
        .options(
            selectinload(JobCriteriaVersion.hard_requirements),
            selectinload(JobCriteriaVersion.scoring_dimensions),
        )
    )


def _load_profile(
    db: Session,
    candidate_profile_id: uuid.UUID,
) -> CandidateProfile | None:
    return db.get(CandidateProfile, candidate_profile_id)


def _latest_analysis_version(
    db: Session,
    *,
    document_id: uuid.UUID,
    criteria_version_id: uuid.UUID,
) -> int:
    latest = db.scalar(
        select(func.max(ScreeningResult.analysis_version)).where(
            ScreeningResult.document_id == document_id,
            ScreeningResult.criteria_version_id == criteria_version_id,
        )
    )
    return (latest or 0) + 1


def _latest_profile_version(db: Session, document_id: uuid.UUID) -> int:
    latest = db.scalar(
        select(func.max(CandidateProfile.version_number)).where(
            CandidateProfile.document_id == document_id
        )
    )
    return (latest or 0) + 1


def _validate_evidence(
    evidence: Iterable[EvidenceReference],
    segment_map: dict[str, ResumeTextSegment],
) -> None:
    for citation in evidence:
        segment = segment_map.get(citation.segment_key)
        if segment is None or segment.redacted_text is None:
            raise AnalysisContractError(f"证据片段不存在：{citation.segment_key}")
        quote = citation.quote.strip()
        if quote in segment.redacted_text:
            continue
        normalized_quote = " ".join(quote.split())
        normalized_segment = " ".join(segment.redacted_text.split())
        if normalized_quote not in normalized_segment:
            raise AnalysisContractError(
                f"证据引用不属于对应脱敏片段：{citation.segment_key}"
            )


def validate_profile_evidence(
    document: ResumeDocument,
    profile: CandidateProfileDraft,
) -> None:
    segment_map = {segment.segment_key: segment for segment in document.text_segments}
    for _, evidence in _profile_evidence(profile):
        _validate_evidence(evidence, segment_map)


def _profile_draft(profile: CandidateProfile) -> CandidateProfileDraft:
    return CandidateProfileDraft.model_validate(
        {
            "education": profile.education,
            "work_experiences": profile.work_experiences,
            "projects": profile.projects,
            "skills": profile.skills,
            "certifications": profile.certifications,
            "languages": profile.languages,
        }
    )


def _profile_evidence(
    profile: CandidateProfileDraft,
) -> Iterable[tuple[str, list[EvidenceReference]]]:
    collections = (
        ("education", profile.education),
        ("work_experience", profile.work_experiences),
        ("project", profile.projects),
        ("skill", profile.skills),
        ("certification", profile.certifications),
        ("language", profile.languages),
    )
    for item_type, items in collections:
        for index, item in enumerate(items):
            yield f"{item_type}:{index}", item.evidence


def _validate_analysis_contract(
    analysis: ResumeAnalysisDraft,
    criteria: JobCriteriaVersion,
    segment_map: dict[str, ResumeTextSegment],
    profile: CandidateProfileDraft,
) -> None:
    expected_requirements = {item.id for item in criteria.hard_requirements}
    returned_requirements = {item.requirement_id for item in analysis.hard_requirements}
    if returned_requirements != expected_requirements:
        raise AnalysisContractError("模型没有完整返回职位硬性条件判断")

    expected_dimensions = {item.id for item in criteria.scoring_dimensions}
    returned_dimensions = {item.dimension_id for item in analysis.dimension_scores}
    if returned_dimensions != expected_dimensions:
        raise AnalysisContractError("模型没有完整返回职位评分维度")

    if sum(item.weight_percent for item in criteria.scoring_dimensions) != 100:
        raise AnalysisContractError("已确认职位标准的评分权重总和不是 100%")

    for _, evidence in _profile_evidence(profile):
        _validate_evidence(evidence, segment_map)
    for judgment in analysis.hard_requirements:
        _validate_evidence(judgment.evidence, segment_map)
    for dimension in analysis.dimension_scores:
        _validate_evidence(dimension.evidence, segment_map)


def _add_citations(
    result: ScreeningResult,
    *,
    subject_type: str,
    subject_key: str,
    evidence: Iterable[EvidenceReference],
    segment_map: dict[str, ResumeTextSegment],
    dimension_score: DimensionScore | None,
    next_sort_order: list[int],
) -> None:
    for reference in evidence:
        segment = segment_map[reference.segment_key]
        result.evidence_citations.append(
            EvidenceCitation(
                dimension_score=dimension_score,
                segment=segment,
                subject_type=subject_type,
                subject_key=subject_key,
                segment_key=segment.segment_key,
                quote=reference.quote.strip(),
                source_type=segment.source_type,
                page_number=segment.page_number,
                paragraph_index=segment.paragraph_index,
                sort_order=next_sort_order[0],
            )
        )
        next_sort_order[0] += 1


def _failure_details(error: Exception) -> tuple[str, str]:
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
    return "analysis_failed", "AI 简历分析失败，请稍后重试"


def _mark_result_failed(
    result_id: uuid.UUID,
    error: Exception,
    session_factory: SessionFactory,
) -> dict[str, str]:
    code, message = _failure_details(error)
    with session_factory() as db:
        result = db.get(ScreeningResult, result_id)
        if result is None:
            return {"status": "missing", "result_id": str(result_id)}
        result.status = "failed"
        result.failure_code = code
        result.failure_message = message
        result.completed_at = datetime.now(UTC)
        db.commit()
    return {"status": "failed", "result_id": str(result_id), "code": code}


async def analyze_resume_document(
    document_id: uuid.UUID,
    *,
    criteria_version_id: uuid.UUID | None = None,
    candidate_profile_id: uuid.UUID | None = None,
    analysis_version: int | None = None,
    session_factory: SessionFactory = SessionLocal,
    ai_client: OpenAICompatibleClient | None = None,
) -> dict[str, str | float | int]:
    client = ai_client or get_ai_client()
    with session_factory() as db:
        document = _load_document(db, document_id)
        if document is None:
            return {"status": "missing", "document_id": str(document_id)}
        if document.status != "completed" or document.redacted_at is None:
            return {
                "status": "not_ready",
                "document_id": str(document_id),
            }
        criteria = (
            _load_criteria(db, criteria_version_id)
            if criteria_version_id is not None
            else document.batch.criteria_version
        )
        if (
            criteria is None
            or criteria.job_id != document.batch.job_id
            or criteria.status != "confirmed"
        ):
            return {
                "status": "not_ready",
                "document_id": str(document_id),
            }
        profile = (
            _load_profile(db, candidate_profile_id)
            if candidate_profile_id is not None
            else None
        )
        if profile is not None and profile.document_id != document.id:
            return {
                "status": "not_ready",
                "document_id": str(document_id),
            }
        resolved_analysis_version = analysis_version or _latest_analysis_version(
            db,
            document_id=document.id,
            criteria_version_id=criteria.id,
        )
        result = db.scalar(
            select(ScreeningResult).where(
                ScreeningResult.document_id == document.id,
                ScreeningResult.criteria_version_id == criteria.id,
                ScreeningResult.analysis_version == resolved_analysis_version,
            )
        )
        if result is not None and result.status == "completed":
            return {
                "status": "completed",
                "result_id": str(result.id),
                "analysis_version": result.analysis_version,
                "group": result.ai_group or "",
                "total_score": float(result.total_score or 0),
            }
        if result is not None and result.status == "processing":
            return {
                "status": "processing",
                "result_id": str(result.id),
                "analysis_version": result.analysis_version,
            }
        if result is None:
            result = ScreeningResult(
                document_id=document.id,
                candidate_profile_id=profile.id if profile is not None else None,
                criteria_version_id=criteria.id,
                analysis_version=resolved_analysis_version,
                status="processing",
                pass_threshold=criteria.pass_threshold,
                hard_requirement_results=[],
                strengths=[],
                gaps=[],
                missing_items=[],
                interview_questions=[],
                model_name=client.model or "unconfigured",
                prompt_version=RESUME_MATCH_PROMPT_VERSION,
                started_at=datetime.now(UTC),
            )
            db.add(result)
        else:
            result.status = "processing"
            result.candidate_profile_id = profile.id if profile is not None else None
            result.pass_threshold = criteria.pass_threshold
            result.failure_code = None
            result.failure_message = None
            result.completed_at = None
            result.started_at = datetime.now(UTC)
        db.commit()
        result_id = result.id
        resolved_criteria_id = criteria.id
        resolved_profile_id = profile.id if profile is not None else None

    try:
        with session_factory() as db:
            document = _load_document(db, document_id)
            if document is None:
                return {"status": "missing", "result_id": str(result_id)}
            criteria = _load_criteria(db, resolved_criteria_id)
            profile = (
                _load_profile(db, resolved_profile_id)
                if resolved_profile_id is not None
                else None
            )
            if criteria is None:
                return {"status": "missing", "result_id": str(result_id)}
            payload = build_resume_analysis_payload(
                document,
                criteria,
                profile,
            )
        analysis = await client.analyze_resume(payload)
        with session_factory() as db:
            document = _load_document(db, document_id)
            result = db.get(ScreeningResult, result_id)
            if document is None or result is None:
                return {"status": "missing", "result_id": str(result_id)}
            criteria = _load_criteria(db, resolved_criteria_id)
            profile = (
                _load_profile(db, resolved_profile_id)
                if resolved_profile_id is not None
                else None
            )
            if criteria is None:
                return {"status": "missing", "result_id": str(result_id)}
            segment_map = {segment.segment_key: segment for segment in document.text_segments}
            profile_data = _profile_draft(profile) if profile else analysis.candidate_profile
            _validate_analysis_contract(analysis, criteria, segment_map, profile_data)

            if profile is None:
                profile = CandidateProfile(
                    document_id=document.id,
                    version_number=_latest_profile_version(db, document.id),
                    source="ai",
                    model_name=client.model,
                    prompt_version=RESUME_MATCH_PROMPT_VERSION,
                    education=[
                        item.model_dump(mode="json") for item in profile_data.education
                    ],
                    work_experiences=[
                        item.model_dump(mode="json")
                        for item in profile_data.work_experiences
                    ],
                    projects=[
                        item.model_dump(mode="json") for item in profile_data.projects
                    ],
                    skills=[item.model_dump(mode="json") for item in profile_data.skills],
                    certifications=[
                        item.model_dump(mode="json")
                        for item in profile_data.certifications
                    ],
                    languages=[
                        item.model_dump(mode="json") for item in profile_data.languages
                    ],
                )
                db.add(profile)
            result.candidate_profile = profile

            requirement_map = {item.id: item for item in criteria.hard_requirements}
            result.hard_requirement_results = [
                {
                    "requirement_id": str(judgment.requirement_id),
                    "requirement_type": requirement_map[
                        judgment.requirement_id
                    ].requirement_type,
                    "title": requirement_map[judgment.requirement_id].title,
                    "expected_value": requirement_map[
                        judgment.requirement_id
                    ].expected_value,
                    "auto_reject": requirement_map[judgment.requirement_id].auto_reject,
                    "status": judgment.status,
                    "rationale": judgment.rationale,
                    "evidence_segment_keys": [
                        item.segment_key for item in judgment.evidence
                    ],
                }
                for judgment in analysis.hard_requirements
            ]
            auto_rejected = any(
                requirement_map[judgment.requirement_id].auto_reject
                and judgment.status == "failed"
                for judgment in analysis.hard_requirements
            )

            dimension_map = {item.id: item for item in criteria.scoring_dimensions}
            total_score = Decimal("0")
            dimension_rows: dict[uuid.UUID, DimensionScore] = {}
            for sort_order, score in enumerate(analysis.dimension_scores):
                dimension = dimension_map[score.dimension_id]
                weighted_score = (
                    Decimal(score.score) * Decimal(dimension.weight_percent) / Decimal(100)
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                total_score += weighted_score
                row = DimensionScore(
                    scoring_dimension_id=dimension.id,
                    dimension_name=dimension.name,
                    score=score.score,
                    weight_percent=dimension.weight_percent,
                    weighted_score=weighted_score,
                    rationale=score.rationale,
                    missing_items=score.missing_items,
                    sort_order=sort_order,
                )
                result.dimension_scores.append(row)
                dimension_rows[score.dimension_id] = row

            total_score = total_score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            result.total_score = total_score
            if auto_rejected:
                result.ai_group = "auto_rejected"
            elif total_score < Decimal(criteria.pass_threshold):
                result.ai_group = "low_match"
            else:
                result.ai_group = "passed"
            result.strengths = analysis.strengths
            result.gaps = analysis.gaps
            result.missing_items = analysis.missing_items
            result.interview_questions = analysis.interview_questions

            next_sort_order = [0]
            for subject_key, evidence in _profile_evidence(profile_data):
                _add_citations(
                    result,
                    subject_type="profile",
                    subject_key=subject_key,
                    evidence=evidence,
                    segment_map=segment_map,
                    dimension_score=None,
                    next_sort_order=next_sort_order,
                )
            for judgment in analysis.hard_requirements:
                _add_citations(
                    result,
                    subject_type="hard_requirement",
                    subject_key=str(judgment.requirement_id),
                    evidence=judgment.evidence,
                    segment_map=segment_map,
                    dimension_score=None,
                    next_sort_order=next_sort_order,
                )
            for score in analysis.dimension_scores:
                _add_citations(
                    result,
                    subject_type="dimension",
                    subject_key=str(score.dimension_id),
                    evidence=score.evidence,
                    segment_map=segment_map,
                    dimension_score=dimension_rows[score.dimension_id],
                    next_sort_order=next_sort_order,
                )

            result.status = "completed"
            result.failure_code = None
            result.failure_message = None
            result.completed_at = datetime.now(UTC)
            if result.ai_group == "auto_rejected":
                record_audit(
                    db,
                    action="screening.auto_rejected",
                    target_type="screening_result",
                    target_id=result.id,
                    job_id=document.batch.job_id,
                    batch_id=document.batch_id,
                    result="success",
                    actor_username="system",
                    details={
                        "analysis_version": result.analysis_version,
                        "criteria_version_id": str(result.criteria_version_id),
                    },
                )
            db.commit()
            return {
                "status": "completed",
                "result_id": str(result.id),
                "analysis_version": result.analysis_version,
                "group": result.ai_group,
                "total_score": float(total_score),
            }
    except (
        AIConfigurationError,
        AIRequestTimeout,
        AIResponseValidationError,
        AIUpstreamError,
        AnalysisContractError,
        ModelPayloadSecurityError,
    ) as error:
        return _mark_result_failed(result_id, error, session_factory)
    except Exception as error:
        logger.exception("AI 简历分析出现未预期错误，document_id=%s", document_id)
        return _mark_result_failed(result_id, error, session_factory)
