import asyncio
import logging
import uuid
from typing import Any

from app.config import settings
from app.services.knowledge_index import index_candidate_profile
from app.services.resume_analysis import analyze_resume_document
from app.services.resume_processing import process_resume_document
from app.workers.celery_app import celery_app
from app.workers.dispatcher import enqueue_knowledge_index, enqueue_resume_analysis

logger = logging.getLogger(__name__)


@celery_app.task(name="resume.parse", bind=True, acks_late=True)
def parse_resume_task(task, document_id: str) -> dict[str, str | int | bool]:
    result = process_resume_document(
        uuid.UUID(document_id),
        task_id=str(task.request.id),
    )
    if result.get("status") == "completed":
        try:
            application_id = result.get("application_id")
            result["analysis_task_id"] = enqueue_resume_analysis(
                uuid.UUID(document_id),
                application_id=(uuid.UUID(str(application_id)) if application_id else None),
            )
            result["analysis_enqueued"] = True
        except Exception:
            logger.exception("AI 分析任务创建失败，document_id=%s", document_id)
            result["analysis_enqueued"] = False
    return result


@celery_app.task(name="resume.analyze", bind=True, acks_late=True)
def analyze_resume_task(
    task,
    document_id: str,
    application_id: str | None = None,
    criteria_version_id: str | None = None,
    candidate_profile_id: str | None = None,
    analysis_version: int | None = None,
) -> dict[str, Any]:
    del task
    result = asyncio.run(
        analyze_resume_document(
            uuid.UUID(document_id),
            application_id=uuid.UUID(application_id) if application_id else None,
            criteria_version_id=(
                uuid.UUID(criteria_version_id) if criteria_version_id else None
            ),
            candidate_profile_id=(
                uuid.UUID(candidate_profile_id) if candidate_profile_id else None
            ),
            analysis_version=analysis_version,
        )
    )
    if (
        result.get("status") == "completed"
        and settings.embedding_enabled
        and result.get("candidate_profile_id")
    ):
        try:
            result["knowledge_index_task_id"] = enqueue_knowledge_index(
                uuid.UUID(str(result["candidate_profile_id"]))
            )
            result["knowledge_index_enqueued"] = True
        except Exception:
            logger.exception(
                "知识库索引任务创建失败，document_id=%s",
                document_id,
            )
            result["knowledge_index_enqueued"] = False
    return result


@celery_app.task(name="knowledge.index_profile", bind=True, acks_late=True)
def index_candidate_profile_task(
    task,
    candidate_profile_id: str,
    force: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        index_candidate_profile(
            uuid.UUID(candidate_profile_id),
            task_id=str(task.request.id),
            force=force,
        )
    )
