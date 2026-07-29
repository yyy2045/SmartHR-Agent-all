import uuid

from app.workers.celery_app import celery_app


def enqueue_resume_parsing(document_id: uuid.UUID) -> str:
    result = celery_app.send_task("resume.parse", args=[str(document_id)])
    return str(result.id)


def enqueue_resume_analysis(
    document_id: uuid.UUID,
    *,
    application_id: uuid.UUID | None = None,
    criteria_version_id: uuid.UUID | None = None,
    candidate_profile_id: uuid.UUID | None = None,
    analysis_version: int | None = None,
) -> str:
    kwargs = {
        "application_id": str(application_id) if application_id else None,
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


def enqueue_knowledge_index(
    candidate_profile_id: uuid.UUID,
    *,
    force: bool = False,
) -> str:
    result = celery_app.send_task(
        "knowledge.index_profile",
        args=[str(candidate_profile_id)],
        kwargs={"force": force},
    )
    return str(result.id)


def enqueue_talent_recommendation(
    run_id: uuid.UUID,
    *,
    retry_failed_only: bool = False,
) -> str:
    result = celery_app.send_task(
        "talent.recommendation.run",
        args=[str(run_id)],
        kwargs={"retry_failed_only": retry_failed_only},
    )
    return str(result.id)


def revoke_task(task_id: str) -> None:
    celery_app.control.revoke(task_id, terminate=False)
