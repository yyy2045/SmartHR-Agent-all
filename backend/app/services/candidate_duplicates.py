from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Candidate,
    CandidateDuplicateReview,
    CandidateProfile,
    ResumeDocument,
    User,
)
from app.services.audit import record_audit
from app.services.candidate_identity import normalize_candidate_name

STRONG_SIGNALS = {"resume_sha256_exact", "phone_exact", "email_exact"}


def _normalize_experience_value(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return normalize_candidate_name(value) or ""


def build_experience_fingerprint(
    work_experiences: Iterable[dict[str, object]],
) -> str | None:
    rows = sorted(
        {
            (
                _normalize_experience_value(item.get("company")),
                _normalize_experience_value(item.get("title")),
                _normalize_experience_value(item.get("start_date")),
                _normalize_experience_value(item.get("end_date")),
            )
            for item in work_experiences
            if isinstance(item, dict)
        }
    )
    rows = [row for row in rows if any(row)]
    if not rows:
        return None
    payload = "\x1e".join("\x1f".join(row) for row in rows)
    return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def _candidate_pair(first: uuid.UUID, second: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (first, second) if first.bytes < second.bytes else (second, first)


def _upsert_duplicate_review(
    db: Session,
    *,
    candidate_id: uuid.UUID,
    other_id: uuid.UUID,
    signals: set[str],
    source_document_id: uuid.UUID | None,
) -> tuple[CandidateDuplicateReview | None, bool]:
    candidate_a_id, candidate_b_id = _candidate_pair(candidate_id, other_id)
    ordered_signals = sorted(signals)
    confidence = "strong" if signals & STRONG_SIGNALS else "weak"
    review = db.scalar(
        select(CandidateDuplicateReview).where(
            CandidateDuplicateReview.candidate_a_id == candidate_a_id,
            CandidateDuplicateReview.candidate_b_id == candidate_b_id,
        )
    )
    created = False
    if review is None:
        try:
            with db.begin_nested():
                review = CandidateDuplicateReview(
                    candidate_a_id=candidate_a_id,
                    candidate_b_id=candidate_b_id,
                    source_document_id=source_document_id,
                    confidence=confidence,
                    signals=ordered_signals,
                )
                db.add(review)
                db.flush()
                created = True
        except IntegrityError:
            review = db.scalar(
                select(CandidateDuplicateReview).where(
                    CandidateDuplicateReview.candidate_a_id == candidate_a_id,
                    CandidateDuplicateReview.candidate_b_id == candidate_b_id,
                )
            )
    if review is not None and review.status == "pending":
        review.signals = sorted(set(review.signals) | signals)
        review.confidence = "strong" if set(review.signals) & STRONG_SIGNALS else "weak"
        if source_document_id is not None:
            review.source_document_id = source_document_id
    return review, created


def _matching_candidates(
    db: Session,
    *,
    candidate: Candidate,
    document: ResumeDocument,
) -> dict[uuid.UUID, set[str]]:
    signals_by_candidate: dict[uuid.UUID, set[str]] = defaultdict(set)
    conditions = []
    if candidate.phone_normalized:
        conditions.append(Candidate.phone_normalized == candidate.phone_normalized)
    if candidate.email_normalized:
        conditions.append(Candidate.email_normalized == candidate.email_normalized)
    if candidate.full_name_normalized and candidate.experience_fingerprint:
        conditions.append(
            and_(
                Candidate.full_name_normalized == candidate.full_name_normalized,
                Candidate.experience_fingerprint == candidate.experience_fingerprint,
            )
        )
    if conditions:
        matches = db.scalars(
            select(Candidate).where(
                Candidate.id != candidate.id,
                Candidate.status == "active",
                or_(*conditions),
            )
        ).all()
        for other in matches:
            if (
                candidate.phone_normalized
                and other.phone_normalized == candidate.phone_normalized
            ):
                signals_by_candidate[other.id].add("phone_exact")
            if (
                candidate.email_normalized
                and other.email_normalized == candidate.email_normalized
            ):
                signals_by_candidate[other.id].add("email_exact")
            if (
                candidate.full_name_normalized
                and candidate.experience_fingerprint
                and other.full_name_normalized == candidate.full_name_normalized
                and other.experience_fingerprint == candidate.experience_fingerprint
            ):
                signals_by_candidate[other.id].add("name_experience_exact")

    if document.sha256:
        rows = db.execute(
            select(ResumeDocument.candidate_id)
            .where(
                ResumeDocument.id != document.id,
                ResumeDocument.sha256 == document.sha256,
                ResumeDocument.candidate_id.is_not(None),
                ResumeDocument.candidate_id != candidate.id,
            )
            .distinct()
        )
        for (candidate_id,) in rows:
            if candidate_id is not None:
                signals_by_candidate[candidate_id].add("resume_sha256_exact")
    return signals_by_candidate


def detect_candidate_duplicates(
    db: Session,
    *,
    document: ResumeDocument,
    profile: CandidateProfile | None = None,
) -> list[CandidateDuplicateReview]:
    candidate = document.candidate
    if candidate is None:
        return []
    if profile is not None:
        candidate.experience_fingerprint = build_experience_fingerprint(
            profile.work_experiences
        )
    db.flush()

    reviews: list[CandidateDuplicateReview] = []
    for other_id, signals in _matching_candidates(
        db,
        candidate=candidate,
        document=document,
    ).items():
        review, created = _upsert_duplicate_review(
            db,
            candidate_id=candidate.id,
            other_id=other_id,
            signals=signals,
            source_document_id=document.id,
        )
        if review is None:
            continue
        if created:
            candidate_a_id, candidate_b_id = _candidate_pair(candidate.id, other_id)
            record_audit(
                db,
                action="candidate.duplicate_detected",
                target_type="candidate_duplicate_review",
                target_id=review.id,
                job_id=document.batch.job_id,
                batch_id=document.batch_id,
                result="success",
                actor_username="system",
                details={
                    "candidate_a_id": str(candidate_a_id),
                    "candidate_b_id": str(candidate_b_id),
                    "confidence": review.confidence,
                    "signals": review.signals,
                },
            )
        reviews.append(review)
    return reviews


def detect_candidate_phone_duplicates(
    db: Session,
    *,
    candidate: Candidate,
    actor: User,
) -> list[CandidateDuplicateReview]:
    if candidate.phone_normalized is None:
        return []
    matches = db.scalars(
        select(Candidate).where(
            Candidate.id != candidate.id,
            Candidate.status == "active",
            Candidate.phone_normalized == candidate.phone_normalized,
        )
    ).all()
    reviews: list[CandidateDuplicateReview] = []
    for other in matches:
        review, created = _upsert_duplicate_review(
            db,
            candidate_id=candidate.id,
            other_id=other.id,
            signals={"phone_exact"},
            source_document_id=None,
        )
        if review is None:
            continue
        if created:
            record_audit(
                db,
                action="candidate.duplicate_detected",
                target_type="candidate_duplicate_review",
                target_id=review.id,
                result="success",
                actor=actor,
                details={
                    "candidate_a_id": str(review.candidate_a_id),
                    "candidate_b_id": str(review.candidate_b_id),
                    "confidence": review.confidence,
                    "signals": review.signals,
                    "source": "manual_phone_update",
                },
            )
        reviews.append(review)
    return reviews
