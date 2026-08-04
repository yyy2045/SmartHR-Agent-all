from __future__ import annotations

import logging
import unicodedata
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.database import SessionLocal
from app.models import (
    ApplicationResumeDocument,
    CandidateProfile,
    DimensionScore,
    EvidenceCitation,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeTextSegment,
    ScreeningBatch,
    ScreeningResult,
)
from app.schemas.screening import CandidateProfileDraft, EvidenceReference, ResumeAnalysisDraft
from app.services.ai_client import (
    MAX_MODEL_RETRIES,
    RESUME_MATCH_PROMPT_VERSION,
    AIConfigurationError,
    AIRequestTimeout,
    AIResponseValidationError,
    AIUpstreamError,
    OpenAICompatibleClient,
    get_ai_client,
)
from app.services.ai_observability import record_ai_call
from app.services.audit import record_audit
from app.services.candidate_duplicates import detect_candidate_duplicates
from app.services.model_payload import (
    ModelPayloadSecurityError,
    build_resume_analysis_payload,
)

logger = logging.getLogger(__name__)
SessionFactory = sessionmaker[Session]
AI_GROUP_PRIORITY = {"passed": 0, "low_match": 1, "auto_rejected": 2}


class AnalysisContractError(RuntimeError):
    pass


PRESERVED_EVIDENCE_PUNCTUATION = {"#", "_", "-", "/", "\\"}


def _neighboring_non_space(
    characters: list[tuple[str, int]],
    position: int,
    direction: int,
) -> str | None:
    index = position + direction
    while 0 <= index < len(characters):
        character = characters[index][0]
        if not character.isspace():
            return character
        index += direction
    return None


def _evidence_match_text(text: str) -> tuple[str, list[int]]:
    characters: list[tuple[str, int]] = []
    for source_index, source_character in enumerate(text):
        for normalized_character in unicodedata.normalize("NFKC", source_character):
            characters.append((normalized_character, source_index))

    matched_characters: list[str] = []
    source_indexes: list[int] = []
    for position, (character, source_index) in enumerate(characters):
        if character.isspace():
            continue
        if unicodedata.category(character).startswith("P"):
            previous_character = _neighboring_non_space(characters, position, -1)
            next_character = _neighboring_non_space(characters, position, 1)
            numeric_separator = (
                character in {".", ",", ":"}
                and previous_character is not None
                and next_character is not None
                and previous_character.isdigit()
                and next_character.isdigit()
            )
            if character not in PRESERVED_EVIDENCE_PUNCTUATION and not numeric_separator:
                continue
        matched_characters.append(character)
        source_indexes.append(source_index)
    return "".join(matched_characters), source_indexes


def _find_source_quote(segment_text: str, quote: str) -> str | None:
    exact_start = segment_text.find(quote)
    if exact_start >= 0:
        return segment_text[exact_start : exact_start + len(quote)]

    normalized_quote, _ = _evidence_match_text(quote)
    normalized_segment, source_indexes = _evidence_match_text(segment_text)
    if len(normalized_quote) < 2:
        return None
    normalized_start = normalized_segment.find(normalized_quote)
    if normalized_start < 0:
        return None

    source_start = source_indexes[normalized_start]
    normalized_end = normalized_start + len(normalized_quote) - 1
    source_end = source_indexes[normalized_end] + 1
    source_quote = segment_text[source_start:source_end].strip()
    if not source_quote or len(source_quote) > 1_000:
        return None
    return source_quote


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
    application_id: uuid.UUID,
    criteria_version_id: uuid.UUID,
) -> int:
    latest = db.scalar(
        select(func.max(ScreeningResult.analysis_version)).where(
            ScreeningResult.application_id == application_id,
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
        if segment is None:
            raise AnalysisContractError(f"证据片段不存在：{citation.segment_key}")
        segment_text = (
            segment.redacted_text
            if segment.document.batch.ai_input_mode == "redacted"
            else segment.normalized_text
        )
        if segment_text is None:
            raise AnalysisContractError(f"证据片段不存在：{citation.segment_key}")
        source_quote = _find_source_quote(segment_text, citation.quote.strip())
        if source_quote is None:
            raise AnalysisContractError(
                f"证据引用不属于对应简历片段：{citation.segment_key}"
            )
        citation.quote = source_quote


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
    application_id: uuid.UUID | None = None,
    criteria_version_id: uuid.UUID | None = None,
    candidate_profile_id: uuid.UUID | None = None,
    analysis_version: int | None = None,
    session_factory: SessionFactory = SessionLocal,
    ai_client: OpenAICompatibleClient | None = None,
    task_id: str | None = None,
) -> dict[str, str | float | int]:
    client = ai_client or get_ai_client()
    resolved_job_id: uuid.UUID | None = None
    resolved_batch_id: uuid.UUID | None = None
    with session_factory() as db:
        document = _load_document(db, document_id)
        if document is None:
            return {"status": "missing", "document_id": str(document_id)}
        if document.status != "completed" or document.redacted_at is None:
            return {
                "status": "not_ready",
                "document_id": str(document_id),
            }
        resolved_application_id = application_id or document.application_id
        if resolved_application_id is None:
            return {"status": "not_ready", "document_id": str(document_id)}
        application = db.scalar(
            select(JobApplication)
            .join(
                ApplicationResumeDocument,
                ApplicationResumeDocument.application_id == JobApplication.id,
            )
            .where(
                JobApplication.id == resolved_application_id,
                ApplicationResumeDocument.document_id == document.id,
            )
        )
        if application is None:
            return {"status": "not_ready", "document_id": str(document_id)}
        criteria = (
            _load_criteria(db, criteria_version_id)
            if criteria_version_id is not None
            else document.batch.criteria_version if document.batch is not None else None
        )
        if (
            criteria is None
            or criteria.job_id != application.job_id
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
            application_id=application.id,
            criteria_version_id=criteria.id,
        )
        result = db.scalar(
            select(ScreeningResult).where(
                ScreeningResult.application_id == application.id,
                ScreeningResult.criteria_version_id == criteria.id,
                ScreeningResult.analysis_version == resolved_analysis_version,
            )
        )
        if result is not None and result.status == "completed":
            return {
                "status": "completed",
                "result_id": str(result.id),
                "candidate_profile_id": (
                    str(result.candidate_profile_id)
                    if result.candidate_profile_id is not None
                    else ""
                ),
                "analysis_version": result.analysis_version,
                "group": result.ai_group or "",
                "total_score": float(result.total_score or 0),
            }
        if result is not None and result.status == "processing":
            return {
                "status": "processing",
                "result_id": str(result.id),
                "candidate_profile_id": str(profile.id),
                "analysis_version": result.analysis_version,
            }
        if result is None:
            result = ScreeningResult(
                application_id=application.id,
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
        resolved_job_id = criteria.job_id
        resolved_batch_id = document.batch_id

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
        try:
            if hasattr(client, "analyze_resume_with_metrics"):
                analysis, metrics = await client.analyze_resume_with_metrics(payload)
            else:
                analysis = await client.analyze_resume(payload)
                metrics = None
            record_ai_call(
                scenario="resume_analysis",
                status="succeeded",
                model_name=metrics.model_name if metrics else getattr(client, "model", None),
                prompt_version=RESUME_MATCH_PROMPT_VERSION,
                celery_task_id=task_id,
                retry_count=metrics.retry_count if metrics else 0,
                duration_ms=metrics.duration_ms if metrics else None,
                input_tokens=metrics.input_tokens if metrics else None,
                output_tokens=metrics.output_tokens if metrics else None,
                total_tokens=metrics.total_tokens if metrics else None,
                resource_type="resume_document",
                resource_id=document_id,
                job_id=resolved_job_id,
                batch_id=resolved_batch_id,
                document_id=document_id,
                application_id=resolved_application_id,
                candidate_profile_id=resolved_profile_id,
                session_factory=session_factory,
            )
        except (
            AIConfigurationError,
            AIRequestTimeout,
            AIResponseValidationError,
            AIUpstreamError,
        ) as error:
            record_ai_call(
                scenario="resume_analysis",
                status="failed",
                model_name=getattr(client, "model", None),
                prompt_version=RESUME_MATCH_PROMPT_VERSION,
                celery_task_id=task_id,
                retry_count=0 if isinstance(error, AIConfigurationError) else MAX_MODEL_RETRIES,
                resource_type="resume_document",
                resource_id=document_id,
                job_id=resolved_job_id,
                batch_id=resolved_batch_id,
                document_id=document_id,
                application_id=resolved_application_id,
                candidate_profile_id=resolved_profile_id,
                failure_code=error.__class__.__name__,
                failure_message=str(error),
                session_factory=session_factory,
            )
            raise
        try:
            with session_factory() as db:
                validation_document = _load_document(db, document_id)
                validation_criteria = _load_criteria(db, resolved_criteria_id)
                validation_profile = (
                    _load_profile(db, resolved_profile_id)
                    if resolved_profile_id is not None
                    else None
                )
                if validation_document is None or validation_criteria is None:
                    return {"status": "missing", "result_id": str(result_id)}
                validation_segment_map = {
                    segment.segment_key: segment
                    for segment in validation_document.text_segments
                }
                validation_profile_data = (
                    _profile_draft(validation_profile)
                    if validation_profile is not None
                    else analysis.candidate_profile
                )
                _validate_analysis_contract(
                    analysis,
                    validation_criteria,
                    validation_segment_map,
                    validation_profile_data,
                )
        except AnalysisContractError as error:
            logger.warning(
                "AI 简历分析合同校验失败，准备执行一次纠正重试，document_id=%s",
                document_id,
            )
            try:
                if hasattr(client, "analyze_resume_with_metrics"):
                    analysis, repair_metrics = await client.analyze_resume_with_metrics(
                        payload,
                        validation_feedback=str(error),
                        previous_analysis=analysis.model_dump(mode="json"),
                    )
                else:
                    analysis = await client.analyze_resume(
                        payload,
                        validation_feedback=str(error),
                        previous_analysis=analysis.model_dump(mode="json"),
                    )
                    repair_metrics = None
                record_ai_call(
                    scenario="resume_analysis_repair",
                    status="succeeded",
                    model_name=(
                        repair_metrics.model_name
                        if repair_metrics
                        else getattr(client, "model", None)
                    ),
                    prompt_version=RESUME_MATCH_PROMPT_VERSION,
                    celery_task_id=task_id,
                    retry_count=repair_metrics.retry_count if repair_metrics else 0,
                    duration_ms=repair_metrics.duration_ms if repair_metrics else None,
                    input_tokens=repair_metrics.input_tokens if repair_metrics else None,
                    output_tokens=repair_metrics.output_tokens if repair_metrics else None,
                    total_tokens=repair_metrics.total_tokens if repair_metrics else None,
                    resource_type="resume_document",
                    resource_id=document_id,
                    job_id=resolved_job_id,
                    batch_id=resolved_batch_id,
                    document_id=document_id,
                    application_id=resolved_application_id,
                    candidate_profile_id=resolved_profile_id,
                    session_factory=session_factory,
                )
            except (
                AIConfigurationError,
                AIRequestTimeout,
                AIResponseValidationError,
                AIUpstreamError,
            ) as repair_error:
                record_ai_call(
                    scenario="resume_analysis_repair",
                    status="failed",
                    model_name=getattr(client, "model", None),
                    prompt_version=RESUME_MATCH_PROMPT_VERSION,
                    celery_task_id=task_id,
                    retry_count=(
                        0
                        if isinstance(repair_error, AIConfigurationError)
                        else MAX_MODEL_RETRIES
                    ),
                    resource_type="resume_document",
                    resource_id=document_id,
                    job_id=resolved_job_id,
                    batch_id=resolved_batch_id,
                    document_id=document_id,
                    application_id=resolved_application_id,
                    candidate_profile_id=resolved_profile_id,
                    failure_code=repair_error.__class__.__name__,
                    failure_message=str(repair_error),
                    session_factory=session_factory,
                )
                raise
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
            detect_candidate_duplicates(db, document=document, profile=profile)

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
