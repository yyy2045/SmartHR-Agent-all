import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import (
    Candidate,
    CandidateDuplicateReview,
    CandidateProcess,
    JobApplication,
    Offer,
    OfferPortalLink,
    ResumeDocument,
    User,
)
from app.schemas.candidate import (
    CandidateApplicationSummaryResponse,
    CandidateDetailResponse,
    CandidateDuplicateResolutionRequest,
    CandidateDuplicateReviewResponse,
    CandidateListItemResponse,
    CandidateListResponse,
    CandidateMergeRequest,
    CandidateMergeResponse,
    CandidatePhoneUpdateRequest,
    CandidatePhoneUpdateResponse,
    CandidateResumeSummaryResponse,
    CandidateSummaryResponse,
)
from app.services.audit import record_audit
from app.services.candidate_duplicates import detect_candidate_phone_duplicates
from app.services.candidate_identity import normalize_candidate_phone
from app.services.candidate_merging import (
    dismiss_duplicate_review,
    merge_duplicate_candidates,
)
from app.services.candidate_process import change_candidate_process_stage
from app.services.offer_portal import revoke_portal_link

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _ensure_candidate_access(user: User) -> None:
    if not user.has_role("administrator", "recruiter"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有候选人中心访问权限",
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


def _pending_duplicate_count(db: Session, candidate_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count(CandidateDuplicateReview.id)).where(
                CandidateDuplicateReview.status == "pending",
                or_(
                    CandidateDuplicateReview.candidate_a_id == candidate_id,
                    CandidateDuplicateReview.candidate_b_id == candidate_id,
                ),
            )
        )
        or 0
    )


def _candidate_list_item(
    candidate: Candidate,
    *,
    application_count: int,
    resume_count: int,
    pending_duplicate_count: int,
) -> CandidateListItemResponse:
    return CandidateListItemResponse(
        id=candidate.id,
        candidate_code=candidate.candidate_code,
        full_name=candidate.full_name,
        phone=candidate.phone,
        email=candidate.email,
        status=candidate.status,
        merged_into_candidate_id=candidate.merged_into_candidate_id,
        application_count=application_count,
        resume_count=resume_count,
        pending_duplicate_count=pending_duplicate_count,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


@router.get("", response_model=CandidateListResponse)
def list_candidates(
    current_user: CurrentUser,
    db: DbSession,
    candidate_status: Annotated[
        Literal["active", "merged", "all"],
        Query(alias="status"),
    ] = "active",
    query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CandidateListResponse:
    _ensure_candidate_access(current_user)
    filters = []
    if candidate_status != "all":
        filters.append(Candidate.status == candidate_status)
    normalized_query = query.strip() if query else ""
    if normalized_query:
        pattern = f"%{normalized_query}%"
        search_clauses = [
            Candidate.full_name.ilike(pattern),
            Candidate.phone.ilike(pattern),
            Candidate.email.ilike(pattern),
        ]
        candidate_code = normalized_query.upper().removeprefix("CAND-").replace("-", "")
        if candidate_code and len(candidate_code) <= 32 and all(
            character in "0123456789ABCDEF" for character in candidate_code
        ):
            search_clauses.append(
                func.replace(cast(Candidate.id, String), "-", "").ilike(
                    f"{candidate_code.lower()}%"
                )
            )
        filters.append(or_(*search_clauses))

    application_count = (
        select(func.count(JobApplication.id))
        .where(JobApplication.candidate_id == Candidate.id)
        .correlate(Candidate)
        .scalar_subquery()
    )
    resume_count = (
        select(func.count(ResumeDocument.id))
        .where(ResumeDocument.candidate_id == Candidate.id)
        .correlate(Candidate)
        .scalar_subquery()
    )
    pending_duplicate_count = (
        select(func.count(CandidateDuplicateReview.id))
        .where(
            CandidateDuplicateReview.status == "pending",
            or_(
                CandidateDuplicateReview.candidate_a_id == Candidate.id,
                CandidateDuplicateReview.candidate_b_id == Candidate.id,
            ),
        )
        .correlate(Candidate)
        .scalar_subquery()
    )
    total = db.scalar(select(func.count(Candidate.id)).where(*filters)) or 0
    rows = db.execute(
        select(
            Candidate,
            application_count.label("application_count"),
            resume_count.label("resume_count"),
            pending_duplicate_count.label("pending_duplicate_count"),
        )
        .where(*filters)
        .order_by(Candidate.updated_at.desc(), Candidate.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return CandidateListResponse(
        items=[
            _candidate_list_item(
                candidate,
                application_count=application_total,
                resume_count=resume_total,
                pending_duplicate_count=pending_total,
            )
            for candidate, application_total, resume_total, pending_total in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{candidate_id:uuid}", response_model=CandidateDetailResponse)
def get_candidate(
    candidate_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateDetailResponse:
    _ensure_candidate_access(current_user)
    candidate = db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .options(
            selectinload(Candidate.applications).selectinload(JobApplication.job),
            selectinload(Candidate.applications).selectinload(JobApplication.process),
            selectinload(Candidate.applications)
            .selectinload(JobApplication.documents)
            .selectinload(ResumeDocument.batch),
        )
    )
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人不存在")

    applications = sorted(
        candidate.applications,
        key=lambda item: (item.status != "active", -item.created_at.timestamp()),
    )
    application_items = [
        CandidateApplicationSummaryResponse(
            id=application.id,
            job_id=application.job_id,
            job_title=application.job.title,
            job_status=application.job.status,
            status=application.status,
            merged_into_application_id=application.merged_into_application_id,
            current_stage=(
                application.process.current_stage if application.process is not None else None
            ),
            document_count=len(application.documents),
            created_at=application.created_at,
        )
        for application in applications
    ]
    resume_items = sorted(
        (
            CandidateResumeSummaryResponse(
                id=document.id,
                application_id=document.application_id,
                job_id=application.job_id,
                job_title=application.job.title,
                batch_id=document.batch_id,
                batch_name=document.batch.name,
                original_filename=document.original_filename,
                status=document.status,
                created_at=document.created_at,
            )
            for application in applications
            for document in application.documents
        ),
        key=lambda item: item.created_at,
        reverse=True,
    )
    return CandidateDetailResponse(
        **_candidate_list_item(
            candidate,
            application_count=len(applications),
            resume_count=len(resume_items),
            pending_duplicate_count=_pending_duplicate_count(db, candidate.id),
        ).model_dump(),
        applications=application_items,
        resumes=resume_items,
    )


@router.patch(
    "/{candidate_id:uuid}/phone",
    response_model=CandidatePhoneUpdateResponse,
)
def update_candidate_phone(
    candidate_id: uuid.UUID,
    payload: CandidatePhoneUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidatePhoneUpdateResponse:
    _ensure_candidate_access(current_user)
    normalized_phone = normalize_candidate_phone(payload.phone)
    if normalized_phone is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="请输入有效的手机或联系电话",
        )
    candidate = db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .with_for_update()
        .options(
            selectinload(Candidate.applications)
            .selectinload(JobApplication.process)
            .selectinload(CandidateProcess.events),
            selectinload(Candidate.applications)
            .selectinload(JobApplication.offer)
            .selectinload(Offer.portal_links)
            .selectinload(OfferPortalLink.response),
            selectinload(Candidate.applications)
            .selectinload(JobApplication.offer)
            .selectinload(Offer.candidate_response),
        )
    )
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人不存在")
    if candidate.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已合并候选人不能修改手机号",
        )
    if candidate.phone == payload.phone and candidate.phone_normalized == normalized_phone:
        return CandidatePhoneUpdateResponse(
            candidate_id=candidate.id,
            phone=candidate.phone,
            revoked_portal_link_count=0,
        )

    revoked_links: list[OfferPortalLink] = []
    revocation_reason = f"候选人手机号已修正：{payload.reason}"
    for application in candidate.applications:
        offer = application.offer
        if offer is None:
            continue
        for link in offer.portal_links:
            if link.revoked_at is not None:
                continue
            revoke_portal_link(
                link,
                idempotency_key=uuid.uuid4(),
                reason=revocation_reason,
                user=current_user,
            )
            revoked_links.append(link)
            record_audit(
                db,
                action="offer.portal_link_revoked_phone_change",
                target_type="offer_portal_link",
                target_id=link.id,
                job_id=application.job_id,
                result="success",
                actor=current_user,
                details={
                    "offer_id": str(offer.id),
                    "candidate_id": str(candidate.id),
                    "reason": payload.reason,
                },
            )
        if offer.status == "pending_response" and offer.candidate_response is None:
            offer.status = "approved"
            change_candidate_process_stage(
                db,
                application,
                target_stage="completed",
                reason=revocation_reason,
                operator=current_user,
            )

    had_previous_phone = candidate.phone is not None
    candidate.phone = payload.phone
    candidate.phone_normalized = normalized_phone
    db.flush()
    duplicate_reviews = detect_candidate_phone_duplicates(
        db,
        candidate=candidate,
        actor=current_user,
    )
    record_audit(
        db,
        action="candidate.phone_updated",
        target_type="candidate",
        target_id=candidate.id,
        result="success",
        actor=current_user,
        details={
            "had_previous_phone": had_previous_phone,
            "revoked_portal_link_ids": [str(item.id) for item in revoked_links],
            "duplicate_review_ids": [str(item.id) for item in duplicate_reviews],
            "reason": payload.reason,
        },
    )
    db.commit()
    return CandidatePhoneUpdateResponse(
        candidate_id=candidate.id,
        phone=candidate.phone,
        revoked_portal_link_count=len(revoked_links),
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
        Literal["pending", "not_duplicate", "merged", "all"],
        Query(alias="status"),
    ] = "pending",
) -> list[CandidateDuplicateReviewResponse]:
    _ensure_candidate_access(current_user)
    statement = select(CandidateDuplicateReview)
    if review_status != "all":
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
    _ensure_candidate_access(current_user)
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
    _ensure_candidate_access(current_user)
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
