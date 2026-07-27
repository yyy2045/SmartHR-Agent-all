from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Candidate,
    CandidateDuplicateReview,
    JobApplication,
    ResumeDocument,
    User,
)
from app.services.audit import record_audit


@dataclass(frozen=True)
class CandidateMergeOutcome:
    target_candidate: Candidate
    merged_candidate: Candidate
    moved_application_ids: tuple[uuid.UUID, ...]
    merged_application_ids: tuple[uuid.UUID, ...]
    moved_document_count: int


def _copy_missing_identity(target: Candidate, source: Candidate) -> None:
    for field_name in (
        "full_name",
        "phone",
        "email",
        "full_name_normalized",
        "phone_normalized",
        "email_normalized",
        "experience_fingerprint",
    ):
        if getattr(target, field_name) is None:
            setattr(target, field_name, getattr(source, field_name))


def dismiss_duplicate_review(
    db: Session,
    *,
    review: CandidateDuplicateReview,
    actor: User,
    reason: str,
) -> CandidateDuplicateReview:
    if review.status == "not_duplicate":
        return review
    if review.status == "merged":
        raise ValueError("已合并的重复提示不能改为非重复")
    now = datetime.now(UTC)
    review.status = "not_duplicate"
    review.resolved_by_id = actor.id
    review.resolution_note = reason
    review.resolved_at = now
    record_audit(
        db,
        action="candidate.duplicate_dismissed",
        target_type="candidate_duplicate_review",
        target_id=review.id,
        result="success",
        actor=actor,
        details={
            "candidate_a_id": str(review.candidate_a_id),
            "candidate_b_id": str(review.candidate_b_id),
            "reason": reason,
        },
    )
    return review


def merge_duplicate_candidates(
    db: Session,
    *,
    review: CandidateDuplicateReview,
    target_candidate: Candidate,
    source_candidate: Candidate,
    actor: User,
    reason: str,
) -> CandidateMergeOutcome:
    if target_candidate.id == source_candidate.id:
        raise ValueError("不能将候选人合并到自身")
    if target_candidate.status != "active":
        raise ValueError("保留候选人不是有效主档案")
    if source_candidate.status == "merged":
        if source_candidate.merged_into_candidate_id != target_candidate.id:
            raise ValueError("待合并候选人已经合并到其他主档案")
        return CandidateMergeOutcome(
            target_candidate=target_candidate,
            merged_candidate=source_candidate,
            moved_application_ids=(),
            merged_application_ids=(),
            moved_document_count=0,
        )
    if review.status != "pending":
        raise ValueError("只有待确认的重复提示可以执行合并")

    target_applications = list(
        db.scalars(
            select(JobApplication)
            .where(JobApplication.candidate_id == target_candidate.id)
            .with_for_update()
        ).all()
    )
    source_applications = list(
        db.scalars(
            select(JobApplication)
            .where(JobApplication.candidate_id == source_candidate.id)
            .with_for_update()
        ).all()
    )
    active_target_by_job = {
        item.job_id: item for item in target_applications if item.status == "active"
    }
    now = datetime.now(UTC)
    moved_application_ids: list[uuid.UUID] = []
    merged_application_ids: list[uuid.UUID] = []
    for application in source_applications:
        target_application = active_target_by_job.get(application.job_id)
        if application.status == "active" and target_application is not None:
            application.status = "merged"
            application.merged_into_application_id = target_application.id
            application.merged_at = now
            merged_application_ids.append(application.id)
        application.candidate_id = target_candidate.id
        moved_application_ids.append(application.id)

    documents = list(
        db.scalars(
            select(ResumeDocument)
            .where(ResumeDocument.candidate_id == source_candidate.id)
            .with_for_update()
        ).all()
    )
    for document in documents:
        document.candidate_id = target_candidate.id

    _copy_missing_identity(target_candidate, source_candidate)
    source_candidate.status = "merged"
    source_candidate.merged_into_candidate_id = target_candidate.id
    source_candidate.merged_at = now
    review.status = "merged"
    review.resolved_by_id = actor.id
    review.resolution_note = reason
    review.resolved_at = now
    db.flush()

    record_audit(
        db,
        action="candidate.merged",
        target_type="candidate",
        target_id=target_candidate.id,
        result="success",
        actor=actor,
        details={
            "review_id": str(review.id),
            "source_candidate_id": str(source_candidate.id),
            "target_candidate_id": str(target_candidate.id),
            "moved_application_ids": [str(item) for item in moved_application_ids],
            "merged_application_ids": [str(item) for item in merged_application_ids],
            "moved_document_count": len(documents),
            "reason": reason,
        },
    )
    return CandidateMergeOutcome(
        target_candidate=target_candidate,
        merged_candidate=source_candidate,
        moved_application_ids=tuple(moved_application_ids),
        merged_application_ids=tuple(merged_application_ids),
        moved_document_count=len(documents),
    )
