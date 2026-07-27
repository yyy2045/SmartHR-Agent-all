import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    InterviewDimensionRating,
    InterviewEvaluation,
    InterviewQuestionResponse,
    JobApplication,
    ResumeDocument,
    ScreeningResult,
)
from app.schemas.interview_report import (
    InterviewReportContextResponse,
    ReportDimensionEvidenceResponse,
    ReportMissingRoundResponse,
    ReportQuestionEvidenceResponse,
    ReportScreeningCitationResponse,
    ReportScreeningEvidenceResponse,
    ReportSubmittedEvaluationResponse,
)
from app.services.authorization import get_visible_job

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _latest_screening_result(
    db: Session, application_id: uuid.UUID
) -> ScreeningResult | None:
    return db.scalar(
        select(ScreeningResult)
        .join(ResumeDocument, ScreeningResult.document_id == ResumeDocument.id)
        .where(
            ResumeDocument.application_id == application_id,
            ScreeningResult.status == "completed",
        )
        .options(
            selectinload(ScreeningResult.evidence_citations),
            selectinload(ScreeningResult.recruiter_decisions),
        )
        .order_by(
            ScreeningResult.completed_at.desc().nulls_last(),
            ScreeningResult.created_at.desc(),
            ScreeningResult.analysis_version.desc(),
            ScreeningResult.id,
        )
        .limit(1)
    )


def _screening_response(
    result: ScreeningResult | None,
) -> ReportScreeningEvidenceResponse | None:
    if result is None:
        return None
    current_decision = (
        result.recruiter_decisions[-1].decision
        if result.recruiter_decisions
        else "unprocessed"
    )
    return ReportScreeningEvidenceResponse(
        id=result.id,
        document_id=result.document_id,
        criteria_version_id=result.criteria_version_id,
        analysis_version=result.analysis_version,
        ai_group=result.ai_group,
        total_score=result.total_score,
        pass_threshold=result.pass_threshold,
        current_decision=current_decision,
        strengths=result.strengths,
        gaps=result.gaps,
        missing_items=result.missing_items,
        completed_at=result.completed_at,
        citations=[
            ReportScreeningCitationResponse(
                id=item.id,
                subject_type=item.subject_type,
                subject_key=item.subject_key,
                quote=item.quote,
                source_type=item.source_type,
                page_number=item.page_number,
                paragraph_index=item.paragraph_index,
            )
            for item in result.evidence_citations
        ],
    )


def _load_interview_rounds(
    db: Session, application_id: uuid.UUID
) -> list[CandidateInterviewRound]:
    return list(
        db.scalars(
            select(CandidateInterviewRound)
            .join(
                CandidateInterviewSchedule,
                CandidateInterviewRound.schedule_id == CandidateInterviewSchedule.id,
            )
            .where(CandidateInterviewSchedule.application_id == application_id)
            .options(
                selectinload(CandidateInterviewRound.plan_round),
                selectinload(CandidateInterviewRound.evaluation)
                .selectinload(InterviewEvaluation.question_responses)
                .selectinload(InterviewQuestionResponse.question),
                selectinload(CandidateInterviewRound.evaluation)
                .selectinload(InterviewEvaluation.dimension_ratings)
                .selectinload(InterviewDimensionRating.dimension),
            )
            .order_by(CandidateInterviewRound.sort_order, CandidateInterviewRound.id)
        ).all()
    )


def _evaluation_response(
    round_item: CandidateInterviewRound,
) -> ReportSubmittedEvaluationResponse:
    evaluation = round_item.evaluation
    if (
        evaluation is None
        or evaluation.status != "submitted"
        or evaluation.overall_recommendation is None
        or evaluation.submitted_at is None
    ):
        raise RuntimeError("面试轮次没有完整的已提交评价")
    return ReportSubmittedEvaluationResponse(
        evaluation_id=evaluation.id,
        round_id=round_item.id,
        round_name=round_item.plan_round.name,
        round_type=round_item.plan_round.round_type,
        sort_order=round_item.sort_order,
        total_score=evaluation.total_score,
        passed=evaluation.passed,
        overall_recommendation=evaluation.overall_recommendation,
        overall_comment=evaluation.overall_comment,
        submitted_at=evaluation.submitted_at,
        question_responses=[
            ReportQuestionEvidenceResponse(
                question_id=item.question_id,
                question_text=item.question.question_text,
                answer_summary=item.answer_summary,
                evidence=item.evidence,
            )
            for item in sorted(
                evaluation.question_responses,
                key=lambda response: (response.question.sort_order, response.id),
            )
        ],
        dimension_ratings=[
            ReportDimensionEvidenceResponse(
                dimension_id=item.dimension_id,
                dimension_name=item.dimension.name,
                score=item.score,
                evidence=item.evidence,
            )
            for item in sorted(
                evaluation.dimension_ratings,
                key=lambda rating: (rating.dimension.sort_order, rating.id),
            )
        ],
    )


@router.get(
    "/{job_id}/applications/{application_id}/interview-report/context",
    response_model=InterviewReportContextResponse,
)
def get_interview_report_context(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewReportContextResponse:
    job = get_visible_job(db, job_id, current_user)
    application = db.scalar(
        select(JobApplication)
        .where(
            JobApplication.id == application_id,
            JobApplication.job_id == job_id,
        )
        .options(selectinload(JobApplication.candidate))
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="职位应聘记录不存在",
        )

    submitted_evaluations: list[ReportSubmittedEvaluationResponse] = []
    missing_rounds: list[ReportMissingRoundResponse] = []
    for round_item in _load_interview_rounds(db, application.id):
        if round_item.evaluation is not None and round_item.evaluation.status == "submitted":
            submitted_evaluations.append(_evaluation_response(round_item))
            continue
        missing_rounds.append(
            ReportMissingRoundResponse(
                round_id=round_item.id,
                round_name=round_item.plan_round.name,
                round_type=round_item.plan_round.round_type,
                sort_order=round_item.sort_order,
                round_status=round_item.status,
                reason=("cancelled" if round_item.status == "cancelled" else "not_submitted"),
            )
        )

    return InterviewReportContextResponse(
        application_id=application.id,
        application_status=application.status,
        job_id=job.id,
        job_title=job.title,
        candidate_id=application.candidate_id,
        candidate_code=application.candidate.candidate_code,
        candidate_name=application.candidate.full_name,
        latest_screening=_screening_response(
            _latest_screening_result(db, application.id)
        ),
        submitted_evaluations=submitted_evaluations,
        missing_rounds=missing_rounds,
    )
