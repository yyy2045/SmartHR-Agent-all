import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.api.routes.jobs import ensure_job_active
from app.database import get_db
from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    InterviewDimensionRating,
    InterviewEvaluation,
    InterviewQuestionResponse,
    InterviewRound,
    InterviewScoreDimension,
    JobApplication,
    ResumeDocument,
    ScreeningBatch,
    User,
)
from app.schemas.interview_evaluation import (
    InterviewEvaluationContextResponse,
    InterviewEvaluationDraftUpdate,
)
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def evaluation_load_options() -> tuple[object, ...]:
    return (
        selectinload(CandidateInterviewRound.schedule).selectinload(
            CandidateInterviewSchedule.application
        ).selectinload(JobApplication.documents),
        selectinload(CandidateInterviewRound.plan_round).selectinload(
            InterviewRound.questions
        ),
        selectinload(CandidateInterviewRound.plan_round)
        .selectinload(InterviewRound.scoring_dimensions)
        .selectinload(InterviewScoreDimension.anchors),
        selectinload(CandidateInterviewRound.evaluation).selectinload(
            InterviewEvaluation.question_responses
        ),
        selectinload(CandidateInterviewRound.evaluation).selectinload(
            InterviewEvaluation.dimension_ratings
        ),
    )


def get_owned_candidate_round(
    db: Session,
    *,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    round_id: uuid.UUID,
    user: User,
    for_update: bool = False,
) -> CandidateInterviewRound:
    job = get_visible_job(db, job_id, user)
    if for_update:
        ensure_job_writable(job, user)
    statement = (
        select(CandidateInterviewRound)
        .join(
            CandidateInterviewSchedule,
            CandidateInterviewRound.schedule_id == CandidateInterviewSchedule.id,
        )
        .join(
            JobApplication,
            CandidateInterviewSchedule.application_id == JobApplication.id,
        )
        .join(ResumeDocument, ResumeDocument.application_id == JobApplication.id)
        .join(ScreeningBatch, ResumeDocument.batch_id == ScreeningBatch.id)
        .where(
            CandidateInterviewRound.id == round_id,
            ResumeDocument.id == document_id,
            ScreeningBatch.job_id == job_id,
        )
        .options(*evaluation_load_options())
    )
    if for_update:
        statement = statement.with_for_update()
    round_item = db.scalar(statement)
    if round_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人面试轮次不存在")
    return round_item


def serialize_context(
    round_item: CandidateInterviewRound,
) -> InterviewEvaluationContextResponse:
    return InterviewEvaluationContextResponse.model_validate(
        {
            "round_id": round_item.id,
            "plan_round_id": round_item.plan_round_id,
            "round_name": round_item.plan_round.name,
            "round_type": round_item.plan_round.round_type,
            "round_status": round_item.status,
            "pass_threshold": round_item.plan_round.pass_threshold,
            "scheduled_start_at": round_item.scheduled_start_at,
            "questions": round_item.plan_round.questions,
            "dimensions": round_item.plan_round.scoring_dimensions,
            "evaluation": round_item.evaluation,
        }
    )


def replace_question_responses(
    evaluation: InterviewEvaluation,
    payload: InterviewEvaluationDraftUpdate,
) -> None:
    supplied = {item.question_id: item for item in payload.question_responses}
    for existing in list(evaluation.question_responses):
        if existing.question_id not in supplied:
            evaluation.question_responses.remove(existing)
    existing_by_id = {item.question_id: item for item in evaluation.question_responses}
    for question_id, item in supplied.items():
        response = existing_by_id.get(question_id)
        if response is None:
            evaluation.question_responses.append(
                InterviewQuestionResponse(
                    question_id=question_id,
                    answer_summary=item.answer_summary,
                    evidence=item.evidence,
                )
            )
        else:
            response.answer_summary = item.answer_summary
            response.evidence = item.evidence


def replace_dimension_ratings(
    evaluation: InterviewEvaluation,
    payload: InterviewEvaluationDraftUpdate,
) -> None:
    supplied = {item.dimension_id: item for item in payload.dimension_ratings}
    for existing in list(evaluation.dimension_ratings):
        if existing.dimension_id not in supplied:
            evaluation.dimension_ratings.remove(existing)
    existing_by_id = {item.dimension_id: item for item in evaluation.dimension_ratings}
    for dimension_id, item in supplied.items():
        rating = existing_by_id.get(dimension_id)
        if rating is None:
            evaluation.dimension_ratings.append(
                InterviewDimensionRating(
                    dimension_id=dimension_id,
                    score=item.score,
                    evidence=item.evidence,
                )
            )
        else:
            rating.score = item.score
            rating.evidence = item.evidence


def validate_payload_references(
    round_item: CandidateInterviewRound,
    payload: InterviewEvaluationDraftUpdate,
) -> None:
    expected_question_ids = {item.id for item in round_item.plan_round.questions}
    supplied_question_ids = {item.question_id for item in payload.question_responses}
    if not supplied_question_ids.issubset(expected_question_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="评价包含不属于当前面试轮次的问题",
        )
    expected_dimension_ids = {item.id for item in round_item.plan_round.scoring_dimensions}
    supplied_dimension_ids = {item.dimension_id for item in payload.dimension_ratings}
    if not supplied_dimension_ids.issubset(expected_dimension_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="评价包含不属于当前面试轮次的评分维度",
        )


def validate_submittable(round_item: CandidateInterviewRound) -> InterviewEvaluation:
    evaluation = round_item.evaluation
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="请先保存面试评价草稿",
        )
    if evaluation.status == "submitted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="面试评价已提交")
    if evaluation.overall_recommendation is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="请选择总体建议",
        )

    responses = {item.question_id: item for item in evaluation.question_responses}
    for question in round_item.plan_round.questions:
        response = responses.get(question.id)
        if response is None or not response.answer_summary.strip() or not response.evidence.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"问题“{question.question_text}”需要填写回答摘要和事实证据",
            )

    ratings = {item.dimension_id: item for item in evaluation.dimension_ratings}
    for dimension in round_item.plan_round.scoring_dimensions:
        rating = ratings.get(dimension.id)
        if rating is None or rating.score is None or not rating.evidence.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"评分维度“{dimension.name}”需要填写分数和评分依据",
            )
    return evaluation


@router.get(
    "/{job_id}/candidate-processes/{document_id}/interview-schedule/rounds/"
    "{round_id}/evaluation",
    response_model=InterviewEvaluationContextResponse,
)
def get_interview_evaluation(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    round_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewEvaluationContextResponse:
    get_visible_job(db, job_id, current_user)
    round_item = get_owned_candidate_round(
        db,
        job_id=job_id,
        document_id=document_id,
        round_id=round_id,
        user=current_user,
    )
    return serialize_context(round_item)


@router.put(
    "/{job_id}/candidate-processes/{document_id}/interview-schedule/rounds/"
    "{round_id}/evaluation",
    response_model=InterviewEvaluationContextResponse,
)
def save_interview_evaluation_draft(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    round_id: uuid.UUID,
    payload: InterviewEvaluationDraftUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewEvaluationContextResponse:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    round_item = get_owned_candidate_round(
        db,
        job_id=job_id,
        document_id=document_id,
        round_id=round_id,
        user=current_user,
        for_update=True,
    )
    if round_item.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已取消轮次不能填写评价")
    if round_item.evaluation is not None and round_item.evaluation.status == "submitted":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已提交评价不能修改")
    validate_payload_references(round_item, payload)

    created = round_item.evaluation is None
    if round_item.evaluation is None:
        round_item.evaluation = InterviewEvaluation(status="draft")
    evaluation = round_item.evaluation
    evaluation.overall_recommendation = payload.overall_recommendation
    evaluation.overall_comment = payload.overall_comment
    replace_question_responses(evaluation, payload)
    replace_dimension_ratings(evaluation, payload)
    db.flush()
    record_audit(
        db,
        actor=current_user,
        action=("interview_evaluation.created" if created else "interview_evaluation.updated"),
        target_type="interview_evaluation",
        target_id=evaluation.id,
        job_id=job_id,
        batch_id=round_item.schedule.document.batch_id,
        result="success",
        details={
            "document_id": str(document_id),
            "candidate_round_id": str(round_item.id),
            "question_response_count": len(payload.question_responses),
            "dimension_rating_count": len(payload.dimension_ratings),
        },
    )
    db.commit()
    refreshed = get_owned_candidate_round(
        db,
        job_id=job_id,
        document_id=document_id,
        round_id=round_id,
        user=current_user,
    )
    return serialize_context(refreshed)


@router.post(
    "/{job_id}/candidate-processes/{document_id}/interview-schedule/rounds/"
    "{round_id}/evaluation/submit",
    response_model=InterviewEvaluationContextResponse,
)
def submit_interview_evaluation(
    job_id: uuid.UUID,
    document_id: uuid.UUID,
    round_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewEvaluationContextResponse:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    round_item = get_owned_candidate_round(
        db,
        job_id=job_id,
        document_id=document_id,
        round_id=round_id,
        user=current_user,
        for_update=True,
    )
    if round_item.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已取消轮次不能提交评价")
    evaluation = validate_submittable(round_item)
    ratings = {item.dimension_id: item for item in evaluation.dimension_ratings}
    total_score = sum(
        Decimal(ratings[dimension.id].score or 0)
        * Decimal(dimension.weight_percent)
        / Decimal(5)
        for dimension in round_item.plan_round.scoring_dimensions
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    submitted_at = datetime.now(UTC)
    evaluation.status = "submitted"
    evaluation.total_score = total_score
    evaluation.passed = total_score >= Decimal(round_item.plan_round.pass_threshold)
    evaluation.submitted_by_id = current_user.id
    evaluation.submitted_at = submitted_at
    evaluation.updated_at = submitted_at
    record_audit(
        db,
        actor=current_user,
        action="interview_evaluation.submitted",
        target_type="interview_evaluation",
        target_id=evaluation.id,
        job_id=job_id,
        batch_id=round_item.schedule.document.batch_id,
        result="success",
        details={
            "document_id": str(document_id),
            "candidate_round_id": str(round_item.id),
            "total_score": float(total_score),
            "pass_threshold": round_item.plan_round.pass_threshold,
            "passed": evaluation.passed,
            "overall_recommendation": evaluation.overall_recommendation,
        },
    )
    db.commit()
    refreshed = get_owned_candidate_round(
        db,
        job_id=job_id,
        document_id=document_id,
        round_id=round_id,
        user=current_user,
    )
    return serialize_context(refreshed)
