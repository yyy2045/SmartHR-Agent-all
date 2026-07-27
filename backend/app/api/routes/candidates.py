import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import Candidate, CandidateDuplicateReview, JobApplication, ResumeDocument, User
from app.schemas.candidate import (
    CandidateDuplicateResolutionRequest,
    CandidateDuplicateReviewResponse,
    CandidateMergeRequest,
    CandidateMergeResponse,
    CandidateSummaryResponse,
)
from app.services.candidate_merging import (
    dismiss_duplicate_review,
    merge_duplicate_candidates,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _ensure_candidate_operator(user: User) -> None:
    if not user.has_role("administrator", "recruiter"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有候选人去重处理权限",
        )


def _candidate_summary(db: Session, candidate: Candidate) -> CandidateSummaryResponse:
    application_count = db.scalar(
        select(func.count(JobApplication.id)).where(
            JobApplication.candidate_id == candidate.id
        )
    )
    resume_count = db.scalar(
        select(func.count(ResumeDocument.id)).where(
            ResumeDocument.candidate_id == candidate.id
        )
    )
    return CandidateSummaryResponse(
        id=candidate.id,
        candidate_code=candidate.candidate_code,
        full_name=candidate.full_name,
        phone=candidate.phone,
        email=candidate.email,
        status=candidate.status,
        merged_into_candidate_id=candidate.merged_into_candidate_id,
        application_count=application_count or 0,
        resume_count=resume_count or 0,
    )


def _review_response(
    db: Session,
    review: CandidateDuplicateReview,
) -> CandidateDuplicateReviewResponse:
    candidate_a = db.get(Candidate, review.candidate_a_id)
    candidate_b = db.get(Candidate, review.candidate_b_id)
    if candidate_a is None or candidate_b is None:
        raise RuntimeError("重复提示关联的候选人不存在")
    return CandidateDuplicateReviewResponse(
        id=review.id,
        candidate_a=_candidate_summary(db, candidate_a),
        candidate_b=_candidate_summary(db, candidate_b),
        source_document_id=review.source_document_id,
        confidence=review.confidence,
        signals=review.signals,
        status=review.status,
        resolved_by_id=review.resolved_by_id,
        resolution_note=review.resolution_note,
        resolved_at=review.resolved_at,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def _get_review(
    db: Session,
    review_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> CandidateDuplicateReview:
    statement = select(CandidateDuplicateReview).where(
        CandidateDuplicateReview.id == review_id
    )
    if for_update:
        statement = statement.with_for_update()
    review = db.scalar(statement)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="重复提示不存在")
    return review


@router.get(
    "/duplicate-reviews",
    response_model=list[CandidateDuplicateReviewResponse],
)
def list_candidate_duplicate_reviews(
    current_user: CurrentUser,
    db: DbSession,
    review_status: Annotated[
        Literal["pending", "not_duplicate", "merged"] | None,
        Query(alias="status"),
    ] = "pending",
) -> list[CandidateDuplicateReviewResponse]:
    _ensure_candidate_operator(current_user)
    statement = select(CandidateDuplicateReview)
    if review_status is not None:
        statement = statement.where(CandidateDuplicateReview.status == review_status)
    reviews = db.scalars(
        statement.order_by(
            case((CandidateDuplicateReview.confidence == "strong", 0), else_=1),
            CandidateDuplicateReview.created_at,
        )
    ).all()
    return [_review_response(db, review) for review in reviews]


@router.post(
    "/duplicate-reviews/{review_id}/dismiss",
    response_model=CandidateDuplicateReviewResponse,
)
def dismiss_candidate_duplicate_review(
    review_id: uuid.UUID,
    payload: CandidateDuplicateResolutionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateDuplicateReviewResponse:
    _ensure_candidate_operator(current_user)
    review = _get_review(db, review_id, for_update=True)
    try:
        dismiss_duplicate_review(
            db,
            review=review,
            actor=current_user,
            reason=payload.reason,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    db.commit()
    review = _get_review(db, review_id)
    return _review_response(db, review)


@router.post(
    "/duplicate-reviews/{review_id}/merge",
    response_model=CandidateMergeResponse,
)
def merge_candidate_duplicate_review(
    review_id: uuid.UUID,
    payload: CandidateMergeRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateMergeResponse:
    _ensure_candidate_operator(current_user)
    review = _get_review(db, review_id, for_update=True)
    pair = {review.candidate_a_id, review.candidate_b_id}
    if payload.target_candidate_id not in pair:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="保留候选人必须来自当前重复候选人对",
        )
    source_candidate_id = next(item for item in pair if item != payload.target_candidate_id)
    candidates = {
        item.id: item
        for item in db.scalars(
            select(Candidate)
            .where(Candidate.id.in_([payload.target_candidate_id, source_candidate_id]))
            .with_for_update()
        ).all()
    }
    target_candidate = candidates.get(payload.target_candidate_id)
    source_candidate = candidates.get(source_candidate_id)
    if target_candidate is None or source_candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人不存在")
    try:
        outcome = merge_duplicate_candidates(
            db,
            review=review,
            target_candidate=target_candidate,
            source_candidate=source_candidate,
            actor=current_user,
            reason=payload.reason,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    db.commit()
    review = _get_review(db, review_id)
    refreshed_target = db.get(Candidate, outcome.target_candidate.id)
    refreshed_source = db.get(Candidate, outcome.merged_candidate.id)
    if refreshed_target is None or refreshed_source is None:
        raise RuntimeError("候选人合并后无法读取主档案")
    return CandidateMergeResponse(
        review=_review_response(db, review),
        target_candidate=_candidate_summary(db, refreshed_target),
        merged_candidate=_candidate_summary(db, refreshed_source),
        moved_application_ids=list(outcome.moved_application_ids),
        merged_application_ids=list(outcome.merged_application_ids),
        moved_document_count=outcome.moved_document_count,
    )
