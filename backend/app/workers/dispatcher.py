import uuid

from app.workers.celery_app import celery_app


def enqueue_resume_parsing(document_id: uuid.UUID) -> str:
    result = celery_app.send_task("resume.parse", args=[str(document_id)])
    return str(result.id)


def enqueue_resume_analysis(
    document_id: uuid.UUID,
    *,
    criteria_version_id: uuid.UUID | None = None,
    candidate_profile_id: uuid.UUID | None = None,
    analysis_version: int | None = None,
) -> str:
    kwargs = {
        "criteria_version_id": str(criteria_version_id) if criteria_version_id else None,
        "candidate_profile_id": str(candidate_profile_id) if candidate_profile_id else None,
        "analysis_version": analysis_version,
    }
    result = celery_app.send_task(
        "resume.analyze",
        args=[str(document_id)],
        kwargs=kwargs,
    )
    return str(result.id)
