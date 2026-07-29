import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.api.routes.batches import screening_result_response
from app.database import get_db
from app.models import (
    DimensionScore,
    JobApplication,
    RecruiterDecision,
    ResumeDocument,
    ScreeningResult,
    User,
)
from app.schemas.screening import (
    AIGroup,
    AnalysisStatus,
    CandidateComparisonRequest,
    CandidateComparisonResponse,
    ManualDecision,
    OriginalEvidenceResponse,
    RecruiterDecisionCreate,
    RecruiterDecisionResponse,
    ScreeningResultResponse,
    ScreeningResultSummaryResponse,
)
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _result_options() -> tuple[object, ...]:
    return (
        selectinload(ScreeningResult.document).selectinload(ResumeDocument.batch),
        selectinload(ScreeningResult.application).selectinload(JobApplication.process),
        selectinload(ScreeningResult.candidate_profile),
        selectinload(ScreeningResult.criteria_version),
        selectinload(ScreeningResult.dimension_scores).selectinload(
            DimensionScore.evidence_citations
        ),
        selectinload(ScreeningResult.evidence_citations),
        selectinload(ScreeningResult.recruiter_decisions).selectinload(
            RecruiterDecision.operator
        ),
    )


def _get_owned_result(
    db: Session,
    *,
    job_id: uuid.UUID,
    result_id: uuid.UUID,
    user: User,
    writable: bool = False,
    for_update: bool = False,
) -> ScreeningResult:
    job = get_visible_job(db, job_id, user)
    if writable:
        ensure_job_writable(job, user)
    statement = (
        select(ScreeningResult)
        .join(JobApplication, ScreeningResult.application_id == JobApplication.id)
        .where(
            ScreeningResult.id == result_id,
            JobApplication.job_id == job_id,
        )
        .options(*_result_options())
    )
    if for_update:
        statement = statement.with_for_update()
    result = db.scalar(statement)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="筛选结果不存在")
    return result


def _current_decision(result: ScreeningResult) -> ManualDecision:
    if not result.recruiter_decisions:
        return "unprocessed"
    return result.recruiter_decisions[-1].decision  # type: ignore[return-value]


def _decision_response(
    decision: RecruiterDecision,
    *,
    operator_display_name: str | None = None,
) -> RecruiterDecisionResponse:
    return RecruiterDecisionResponse(
        id=decision.id,
        screening_result_id=decision.screening_result_id,
        sequence_number=decision.sequence_number,
        previous_decision=decision.previous_decision,
        decision=decision.decision,
        reason=decision.reason,
        is_auto_rejection_override=decision.is_auto_rejection_override,
        operator_id=decision.operator_id,
        operator_display_name=(
            operator_display_name
            if operator_display_name is not None
            else decision.operator.display_name
        ),
        created_at=decision.created_at,
    )


@router.get(
    "/{job_id}/screening-results",
    response_model=list[ScreeningResultSummaryResponse],
)
def list_screening_results(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    processing_status: AnalysisStatus | None = None,
    ai_group: AIGroup | None = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    decision: ManualDecision | None = None,
) -> list[ScreeningResultSummaryResponse]:
    get_visible_job(db, job_id, current_user)
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="最低分不能高于最高分",
        )

    statement = (
        select(ScreeningResult)
        .join(JobApplication, ScreeningResult.application_id == JobApplication.id)
        .where(JobApplication.job_id == job_id)
        .options(*_result_options())
    )
    all_results = list(db.scalars(statement).unique().all())
    grouped: dict[uuid.UUID, list[ScreeningResult]] = {}
    for item in all_results:
        grouped.setdefault(item.application_id, []).append(item)

    results: list[ScreeningResult] = []
    for document_results in grouped.values():
        completed = [item for item in document_results if item.status == "completed"]
        candidates = completed or document_results
        results.append(
            max(
                candidates,
                key=lambda item: (
                    item.created_at,
                    item.criteria_version.version_number,
                    item.analysis_version,
                ),
            )
        )
    if processing_status is not None:
        results = [item for item in results if item.status == processing_status]
    if ai_group is not None:
        results = [item for item in results if item.ai_group == ai_group]
    if min_score is not None:
        results = [
            item
            for item in results
            if item.total_score is not None and float(item.total_score) >= min_score
        ]
    if max_score is not None:
        results = [
            item
            for item in results
            if item.total_score is not None and float(item.total_score) <= max_score
        ]
    if decision is not None:
        results = [item for item in results if _current_decision(item) == decision]

    group_rank = {"passed": 0, "low_match": 1, "auto_rejected": 2}
    status_rank = {"completed": 0, "processing": 1, "failed": 2}
    results.sort(
        key=lambda item: (
            status_rank[item.status],
            group_rank.get(item.ai_group or "", 3),
            -(float(item.total_score) if item.total_score is not None else -1),
            item.document.candidate_code,
        )
    )

    return [
        ScreeningResultSummaryResponse(
            id=item.id,
            application_id=item.application_id,
            batch_id=item.document.batch_id,
            batch_name=item.document.batch.name,
            document_id=item.document_id,
            candidate_code=item.document.candidate_code,
            criteria_version_id=item.criteria_version_id,
            criteria_version_number=item.criteria_version.version_number,
            analysis_version=item.analysis_version,
            status=item.status,
            ai_group=item.ai_group,
            total_score=(float(item.total_score) if item.total_score is not None else None),
            pass_threshold=item.pass_threshold,
            current_decision=_current_decision(item),
            latest_decision_at=(
                item.recruiter_decisions[-1].created_at
                if item.recruiter_decisions
                else None
            ),
            created_at=item.created_at,
        )
        for item in results
    ]


@router.post(
    "/{job_id}/screening-results/compare",
    response_model=CandidateComparisonResponse,
)
def compare_screening_results(
    job_id: uuid.UUID,
    payload: CandidateComparisonRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateComparisonResponse:
    get_visible_job(db, job_id, current_user)
    results = list(
        db.scalars(
            select(ScreeningResult)
            .join(JobApplication, ScreeningResult.application_id == JobApplication.id)
            .where(
                ScreeningResult.id.in_(payload.result_ids),
                JobApplication.job_id == job_id,
            )
            .options(*_result_options())
        )
        .unique()
        .all()
    )
    if len(results) != len(payload.result_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="筛选结果不存在")

    by_id = {item.id: item for item in results}
    ordered_results = [by_id[result_id] for result_id in payload.result_ids]
    if any(item.application.job_id != job_id for item in ordered_results):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="筛选结果不存在")
    if any(item.status != "completed" for item in ordered_results):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只能比较已完成 AI 分析的候选人",
        )

    criteria_version_ids = {item.criteria_version_id for item in ordered_results}
    analysis_versions = {item.analysis_version for item in ordered_results}
    if len(criteria_version_ids) != 1 or len(analysis_versions) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="只能比较同一职位标准和同一分析版本的候选人",
        )

    first = ordered_results[0]
    return CandidateComparisonResponse(
        job_id=job_id,
        criteria_version_id=first.criteria_version_id,
        criteria_version_number=first.criteria_version.version_number,
        analysis_version=first.analysis_version,
        candidates=[
            screening_result_response(item, item.document.candidate_code)
            for item in ordered_results
        ],
    )


@router.get(
    "/{job_id}/screening-results/{result_id}",
    response_model=ScreeningResultResponse,
)
def get_screening_result(
    job_id: uuid.UUID,
    result_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> ScreeningResultResponse:
    result = _get_owned_result(
        db,
        job_id=job_id,
        result_id=result_id,
        user=current_user,
    )
    return screening_result_response(result, result.document.candidate_code)


@router.get(
    "/{job_id}/screening-results/{result_id}/evidence/{citation_id}",
    response_model=OriginalEvidenceResponse,
)
def get_original_evidence(
    job_id: uuid.UUID,
    result_id: uuid.UUID,
    citation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> OriginalEvidenceResponse:
    result = _get_owned_result(
        db,
        job_id=job_id,
        result_id=result_id,
        user=current_user,
        writable=True,
    )
    citation = next(
        (item for item in result.evidence_citations if item.id == citation_id),
        None,
    )
    if citation is None or citation.segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原文证据不存在")
    record_audit(
        db,
        action="resume.original_evidence_viewed",
        target_type="evidence_citation",
        target_id=citation.id,
        job_id=job_id,
        batch_id=result.document.batch_id,
        result="success",
        actor=current_user,
        details={"screening_result_id": str(result.id)},
    )
    db.commit()
    return OriginalEvidenceResponse(
        citation_id=citation.id,
        segment_key=citation.segment_key,
        quote=citation.quote,
        original_text=citation.segment.normalized_text,
        source_type=citation.source_type,
        page_number=citation.page_number,
        paragraph_index=citation.paragraph_index,
    )


@router.post(
    "/{job_id}/screening-results/{result_id}/decisions",
    response_model=RecruiterDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_recruiter_decision(
    job_id: uuid.UUID,
    result_id: uuid.UUID,
    payload: RecruiterDecisionCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruiterDecisionResponse:
    result = _get_owned_result(
        db,
        job_id=job_id,
        result_id=result_id,
        user=current_user,
        writable=True,
        for_update=True,
    )
    if result.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只有已完成的 AI 分析可以作出人工决策",
        )
    if result.application.process is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="候选人已进入流程看板，请在看板中调整阶段",
        )

    previous_decision = _current_decision(result)
    if previous_decision == payload.decision:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="人工结论没有变化")

    overrides_auto_rejection = (
        result.ai_group == "auto_rejected"
        and payload.decision in {"shortlisted", "pending"}
    )
    if overrides_auto_rejection and not payload.reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="恢复自动淘汰候选人时必须填写原因",
        )

    decision = RecruiterDecision(
        screening_result_id=result.id,
        operator_id=current_user.id,
        sequence_number=len(result.recruiter_decisions) + 1,
        previous_decision=previous_decision,
        decision=payload.decision,
        reason=payload.reason,
        is_auto_rejection_override=overrides_auto_rejection,
    )
    db.add(decision)
    record_audit(
        db,
        action="screening.decision_changed",
        target_type="screening_result",
        target_id=result.id,
        job_id=job_id,
        batch_id=result.document.batch_id,
        result="success",
        actor=current_user,
        details={
            "previous_decision": previous_decision,
            "decision": payload.decision,
            "has_reason": bool(payload.reason),
            "overrides_auto_rejection": overrides_auto_rejection,
        },
    )
    if overrides_auto_rejection:
        record_audit(
            db,
            action="screening.auto_rejection_overridden",
            target_type="screening_result",
            target_id=result.id,
            job_id=job_id,
            batch_id=result.document.batch_id,
            result="success",
            actor=current_user,
            details={"decision": payload.decision},
        )
    db.commit()
    db.refresh(decision)
    return _decision_response(decision, operator_display_name=current_user.display_name)
