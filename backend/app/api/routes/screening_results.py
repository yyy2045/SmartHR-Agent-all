import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.api.routes.batches import screening_result_response
from app.database import get_db
from app.models import (
    DimensionScore,
    Job,
    RecruiterDecision,
    ResumeDocument,
    ScreeningBatch,
    ScreeningResult,
)
from app.schemas.screening import (
    AIGroup,
    AnalysisStatus,
    ManualDecision,
    OriginalEvidenceResponse,
    RecruiterDecisionCreate,
    RecruiterDecisionResponse,
    ScreeningResultResponse,
    ScreeningResultSummaryResponse,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _result_options() -> tuple[object, ...]:
    return (
        selectinload(ScreeningResult.document).selectinload(ResumeDocument.batch),
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
    owner_id: uuid.UUID,
    for_update: bool = False,
) -> ScreeningResult:
    statement = (
        select(ScreeningResult)
        .join(ResumeDocument)
        .join(ScreeningBatch)
        .join(Job)
        .where(
            ScreeningResult.id == result_id,
            ScreeningBatch.job_id == job_id,
            Job.owner_id == owner_id,
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
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="最低分不能高于最高分",
        )

    latest_version = (
        select(func.max(ScreeningResult.analysis_version))
        .where(
            ScreeningResult.document_id == ResumeDocument.id,
            ScreeningResult.criteria_version_id == ScreeningBatch.criteria_version_id,
        )
        .correlate(ResumeDocument, ScreeningBatch)
        .scalar_subquery()
    )
    statement = (
        select(ScreeningResult)
        .join(ResumeDocument)
        .join(ScreeningBatch)
        .join(Job)
        .where(
            ScreeningBatch.job_id == job_id,
            Job.owner_id == current_user.id,
            ScreeningResult.criteria_version_id == ScreeningBatch.criteria_version_id,
            ScreeningResult.analysis_version == latest_version,
        )
        .options(*_result_options())
    )
    if processing_status is not None:
        statement = statement.where(ScreeningResult.status == processing_status)
    if ai_group is not None:
        statement = statement.where(ScreeningResult.ai_group == ai_group)
    if min_score is not None:
        statement = statement.where(ScreeningResult.total_score >= min_score)
    if max_score is not None:
        statement = statement.where(ScreeningResult.total_score <= max_score)

    results = list(db.scalars(statement).unique().all())
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
        owner_id=current_user.id,
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
        owner_id=current_user.id,
    )
    citation = next(
        (item for item in result.evidence_citations if item.id == citation_id),
        None,
    )
    if citation is None or citation.segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原文证据不存在")
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
        owner_id=current_user.id,
        for_update=True,
    )
    if result.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只有已完成的 AI 分析可以作出人工决策",
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
    db.commit()
    db.refresh(decision)
    return _decision_response(decision, operator_display_name=current_user.display_name)
