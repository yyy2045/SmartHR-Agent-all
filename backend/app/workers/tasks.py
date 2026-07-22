import asyncio
import logging
import uuid

from app.services.resume_analysis import analyze_resume_document
from app.services.resume_processing import process_resume_document
from app.workers.celery_app import celery_app
from app.workers.dispatcher import enqueue_resume_analysis

logger = logging.getLogger(__name__)


@celery_app.task(name="resume.parse", bind=True, acks_late=True)
def parse_resume_task(task, document_id: str) -> dict[str, str | int | bool]:
    result = process_resume_document(
        uuid.UUID(document_id),
        task_id=str(task.request.id),
    )
    if result.get("status") == "completed":
        try:
            result["analysis_task_id"] = enqueue_resume_analysis(uuid.UUID(document_id))
            result["analysis_enqueued"] = True
        except Exception:
            logger.exception("AI 分析任务创建失败，document_id=%s", document_id)
            result["analysis_enqueued"] = False
    return result


@celery_app.task(name="resume.analyze", bind=True, acks_late=True)
def analyze_resume_task(
    task,
    document_id: str,
    criteria_version_id: str | None = None,
    candidate_profile_id: str | None = None,
    analysis_version: int | None = None,
) -> dict[str, str | float | int]:
    del task
    return asyncio.run(
        analyze_resume_document(
            uuid.UUID(document_id),
            criteria_version_id=(
                uuid.UUID(criteria_version_id) if criteria_version_id else None
            ),
            candidate_profile_id=(
                uuid.UUID(candidate_profile_id) if candidate_profile_id else None
            ),
            analysis_version=analysis_version,
        )
    )
