from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    InterviewEvaluation,
    InterviewReport,
    JobApplication,
    Offer,
    Onboarding,
    ResumeDocument,
    ScreeningResult,
    User,
)
from app.services.authorization import get_visible_job


def _can_view_candidate_contacts(user: User, job_owner_id: uuid.UUID) -> bool:
    return user.has_role("administrator") or (
        user.has_role("recruiter") and user.id == job_owner_id
    )


def _latest_screening_result(
    db: Session,
    application_id: uuid.UUID,
) -> ScreeningResult | None:
    return db.scalar(
        select(ScreeningResult)
        .where(
            ScreeningResult.application_id == application_id,
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


def _submitted_interview_evaluations(
    db: Session,
    application_id: uuid.UUID,
) -> list[InterviewEvaluation]:
    return list(
        db.scalars(
            select(InterviewEvaluation)
            .join(
                CandidateInterviewRound,
                InterviewEvaluation.candidate_round_id == CandidateInterviewRound.id,
            )
            .join(
                CandidateInterviewSchedule,
                CandidateInterviewRound.schedule_id == CandidateInterviewSchedule.id,
            )
            .where(
                CandidateInterviewSchedule.application_id == application_id,
                InterviewEvaluation.status == "submitted",
            )
            .options(
                selectinload(InterviewEvaluation.candidate_round).selectinload(
                    CandidateInterviewRound.plan_round
                )
            )
            .order_by(InterviewEvaluation.submitted_at.desc(), InterviewEvaluation.id)
        )
    )


def _current_recruiter_decision(result: ScreeningResult | None) -> str | None:
    if result is None or not result.recruiter_decisions:
        return None
    return result.recruiter_decisions[-1].decision


def _candidate_profile_snapshot(application: JobApplication) -> dict[str, Any] | None:
    document = application.primary_document
    if document is None or not document.candidate_profiles:
        return None
    profile = document.candidate_profiles[-1]
    return {
        "id": str(profile.id),
        "document_id": str(profile.document_id),
        "version_number": profile.version_number,
        "source": profile.source,
        "education": profile.education,
        "work_experiences": profile.work_experiences,
        "projects": profile.projects,
        "skills": profile.skills,
        "certifications": profile.certifications,
        "languages": profile.languages,
    }


def _screening_snapshot(result: ScreeningResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "id": str(result.id),
        "analysis_version": result.analysis_version,
        "ai_group": result.ai_group,
        "total_score": float(result.total_score or 0),
        "pass_threshold": result.pass_threshold,
        "current_recruiter_decision": _current_recruiter_decision(result),
        "strengths": result.strengths,
        "gaps": result.gaps,
        "missing_items": result.missing_items,
        "evidence_citations": [
            {
                "id": str(item.id),
                "subject_type": item.subject_type,
                "subject_key": item.subject_key,
                "quote": item.quote,
                "source_type": item.source_type,
                "page_number": item.page_number,
                "paragraph_index": item.paragraph_index,
            }
            for item in result.evidence_citations[:20]
        ],
    }


def _interview_evaluation_snapshot(
    evaluations: list[InterviewEvaluation],
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item.id),
            "round_name": item.candidate_round.plan_round.name,
            "round_type": item.candidate_round.plan_round.round_type,
            "overall_recommendation": item.overall_recommendation,
            "overall_comment": item.overall_comment,
            "total_score": item.total_score,
            "passed": item.passed,
            "submitted_at": item.submitted_at.isoformat() if item.submitted_at else None,
        }
        for item in evaluations[:10]
    ]


def _interview_report_snapshot(report: InterviewReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    version = report.current_version
    return {
        "id": str(report.id),
        "status": report.status,
        "current_version_number": report.current_version_number,
        "conclusion": version.conclusion,
        "executive_summary": version.executive_summary,
        "strengths": version.strengths,
        "concerns": version.concerns,
        "follow_up_actions": version.follow_up_actions,
    }


def _offer_snapshot(offer: Offer | None) -> dict[str, Any] | None:
    if offer is None:
        return None
    return {
        "id": str(offer.id),
        "status": offer.status,
        "current_version_number": offer.current_version_number,
    }


def _onboarding_snapshot(onboarding: Onboarding | None) -> dict[str, Any] | None:
    if onboarding is None:
        return None
    return {
        "id": str(onboarding.id),
        "status": onboarding.status,
        "confirmed_start_date": (
            onboarding.confirmed_start_date.isoformat()
            if onboarding.confirmed_start_date
            else None
        ),
        "actual_start_date": (
            onboarding.actual_start_date.isoformat() if onboarding.actual_start_date else None
        ),
    }


def build_candidate_agent_context(
    db: Session,
    *,
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    actor: User,
) -> dict[str, Any]:
    job = get_visible_job(db, job_id, actor)
    application = db.scalar(
        select(JobApplication)
        .where(
            JobApplication.id == application_id,
            JobApplication.job_id == job.id,
        )
        .options(
            selectinload(JobApplication.candidate),
            selectinload(JobApplication.primary_document).selectinload(
                ResumeDocument.candidate_profiles
            ),
            selectinload(JobApplication.process),
            selectinload(JobApplication.interview_report).selectinload(
                InterviewReport.versions
            ),
            selectinload(JobApplication.offer),
            selectinload(JobApplication.onboarding),
        )
    )
    if application is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="职位应聘记录不存在",
        )
    show_contacts = _can_view_candidate_contacts(actor, job.owner_id)
    latest_screening = _latest_screening_result(db, application.id)
    evaluations = _submitted_interview_evaluations(db, application.id)

    return {
        "job": {
            "id": str(job.id),
            "title": job.title,
            "department": job.department,
        },
        "application": {
            "id": str(application.id),
            "status": application.status,
            "source_type": application.source_type,
            "current_stage": (
                application.process.current_stage if application.process is not None else None
            ),
        },
        "candidate": {
            "id": str(application.candidate.id),
            "candidate_code": application.candidate.candidate_code,
            "full_name": application.candidate.full_name,
            "phone": application.candidate.phone if show_contacts else None,
            "email": application.candidate.email if show_contacts else None,
            "contacts_visible": show_contacts,
        },
        "primary_document": (
            {
                "id": str(application.primary_document.id),
                "status": application.primary_document.status,
                "original_filename": application.primary_document.original_filename,
            }
            if application.primary_document is not None
            else None
        ),
        "candidate_profile": _candidate_profile_snapshot(application),
        "latest_screening": _screening_snapshot(latest_screening),
        "interview_evaluations": _interview_evaluation_snapshot(evaluations),
        "interview_report": _interview_report_snapshot(application.interview_report),
        "offer": _offer_snapshot(application.offer),
        "onboarding": _onboarding_snapshot(application.onboarding),
    }
