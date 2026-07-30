from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ApplicationResumeDocument,
    Candidate,
    CandidateDuplicateReview,
    JobApplication,
    ResumeDocument,
    TalentPoolMembership,
    TalentPoolMembershipEvent,
    TalentRecommendationResult,
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
    linked_document_count: int


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


def _append_membership_merge_event(
    db: Session,
    *,
    membership: TalentPoolMembership,
    review_id: uuid.UUID,
    source_candidate_id: uuid.UUID,
    target_candidate_id: uuid.UUID,
    actor: User,
    reason: str,
    from_status: str,
    to_status: str,
    event_role: str,
) -> None:
    next_sequence = db.scalar(
        select(func.coalesce(func.max(TalentPoolMembershipEvent.sequence_number), 0) + 1).where(
            TalentPoolMembershipEvent.membership_id == membership.id
        )
    )
    membership.events.append(
        TalentPoolMembershipEvent(
            sequence_number=next_sequence or 1,
            idempotency_key=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"talent-pool-merge:{review_id}:{membership.id}:{event_role}",
            ),
            action="candidate_merged",
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            candidate_id_snapshot=source_candidate_id,
            target_candidate_id_snapshot=target_candidate_id,
            source_application_id_snapshot=membership.source_application_id,
            actor_user_id=actor.id,
            actor_username=actor.username,
            actor_display_name=actor.display_name,
        )
    )


def _merge_talent_pool_memberships(
    db: Session,
    *,
    review_id: uuid.UUID,
    target_candidate: Candidate,
    source_candidate: Candidate,
    actor: User,
    reason: str,
    merged_at: datetime,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    target_memberships = list(
        db.scalars(
            select(TalentPoolMembership)
            .where(TalentPoolMembership.candidate_id == target_candidate.id)
            .with_for_update()
        ).all()
    )
    source_memberships = list(
        db.scalars(
            select(TalentPoolMembership)
            .where(TalentPoolMembership.candidate_id == source_candidate.id)
            .with_for_update()
        ).all()
    )
    target_by_group = {membership.group_id: membership for membership in target_memberships}
    moved_membership_ids: list[uuid.UUID] = []
    conflicted_membership_ids: list[uuid.UUID] = []

    for source_membership in source_memberships:
        target_membership = target_by_group.get(source_membership.group_id)
        source_previous_status = source_membership.status
        if target_membership is None:
            source_membership.candidate_id = target_candidate.id
            source_membership.version += 1
            source_membership.updated_by_id = actor.id
            _append_membership_merge_event(
                db,
                membership=source_membership,
                review_id=review_id,
                source_candidate_id=source_candidate.id,
                target_candidate_id=target_candidate.id,
                actor=actor,
                reason=reason,
                from_status=source_previous_status,
                to_status=source_previous_status,
                event_role="moved",
            )
            target_by_group[source_membership.group_id] = source_membership
            moved_membership_ids.append(source_membership.id)
            continue

        target_previous_status = target_membership.status
        if source_membership.status == "active" and target_membership.status == "removed":
            target_membership.status = "active"
            target_membership.reason = source_membership.reason
            target_membership.removed_at = None
        target_membership.version += 1
        target_membership.updated_by_id = actor.id
        _append_membership_merge_event(
            db,
            membership=target_membership,
            review_id=review_id,
            source_candidate_id=source_candidate.id,
            target_candidate_id=target_candidate.id,
            actor=actor,
            reason=reason,
            from_status=target_previous_status,
            to_status=target_membership.status,
            event_role=f"target:{source_membership.id}",
        )

        source_membership.status = "removed"
        source_membership.removed_at = source_membership.removed_at or merged_at
        source_membership.version += 1
        source_membership.updated_by_id = actor.id
        _append_membership_merge_event(
            db,
            membership=source_membership,
            review_id=review_id,
            source_candidate_id=source_candidate.id,
            target_candidate_id=target_candidate.id,
            actor=actor,
            reason=reason,
            from_status=source_previous_status,
            to_status="removed",
            event_role="conflict",
        )
        conflicted_membership_ids.append(source_membership.id)

    return moved_membership_ids, conflicted_membership_ids


def _copy_application_resume_links(
    db: Session,
    *,
    target_application: JobApplication,
    source_application: JobApplication,
) -> int:
    target_document_ids = set(
        db.scalars(
            select(ApplicationResumeDocument.document_id).where(
                ApplicationResumeDocument.application_id == target_application.id
            )
        ).all()
    )
    source_links = list(
        db.scalars(
            select(ApplicationResumeDocument)
            .where(ApplicationResumeDocument.application_id == source_application.id)
            .order_by(
                ApplicationResumeDocument.created_at.desc(),
                ApplicationResumeDocument.document_id.desc(),
            )
            .with_for_update()
        ).all()
    )
    copied_count = 0
    for source_link in source_links:
        if source_link.document_id in target_document_ids:
            continue
        target_application.document_links.append(
            ApplicationResumeDocument(document_id=source_link.document_id)
        )
        target_document_ids.add(source_link.document_id)
        copied_count += 1

    if target_application.primary_document_id is None:
        source_primary_id = source_application.primary_document_id
        if source_primary_id in target_document_ids:
            target_application.primary_document_id = source_primary_id
        elif source_links:
            target_application.primary_document_id = source_links[0].document_id
    return copied_count


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
            linked_document_count=0,
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
    linked_document_count = 0
    for application in source_applications:
        target_application = active_target_by_job.get(application.job_id)
        if application.status == "active" and target_application is not None:
            application.status = "merged"
            application.merged_into_application_id = target_application.id
            application.merged_at = now
            linked_document_count += _copy_application_resume_links(
                db,
                target_application=target_application,
                source_application=application,
            )
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

    recommendation_results = list(
        db.scalars(
            select(TalentRecommendationResult)
            .where(
                TalentRecommendationResult.resolved_candidate_id == source_candidate.id
            )
            .with_for_update()
        ).all()
    )
    for result in recommendation_results:
        result.resolved_candidate_id = target_candidate.id
        result.candidate_merged_at = now

    moved_membership_ids, conflicted_membership_ids = _merge_talent_pool_memberships(
        db,
        review_id=review.id,
        target_candidate=target_candidate,
        source_candidate=source_candidate,
        actor=actor,
        reason=reason,
        merged_at=now,
    )

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
            "linked_document_count": linked_document_count,
            "resolved_recommendation_result_count": len(recommendation_results),
            "moved_talent_pool_membership_ids": [
                str(item) for item in moved_membership_ids
            ],
            "conflicted_talent_pool_membership_ids": [
                str(item) for item in conflicted_membership_ids
            ],
            "reason": reason,
        },
    )
    return CandidateMergeOutcome(
        target_candidate=target_candidate,
        merged_candidate=source_candidate,
        moved_application_ids=tuple(moved_application_ids),
        merged_application_ids=tuple(merged_application_ids),
        moved_document_count=len(documents),
        linked_document_count=linked_document_count,
    )
