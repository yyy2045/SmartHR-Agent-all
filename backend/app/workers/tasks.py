import asyncio
import logging
import uuid
from typing import Any

from app.config import settings
from app.services.ai_observability import (
    record_task_finished,
    record_task_started,
    task_succeeded_from_result,
)
from app.services.knowledge_index import index_candidate_profile
from app.services.resume_analysis import analyze_resume_document
from app.services.resume_processing import process_resume_document
from app.services.talent_recommendation_rescoring import rescore_talent_recommendations
from app.services.talent_recommendation_retrieval import retrieve_talent_recommendations
from app.workers.celery_app import celery_app
from app.workers.dispatcher import enqueue_knowledge_index, enqueue_resume_analysis

logger = logging.getLogger(__name__)


def _safe_record_task_started(**kwargs: Any) -> None:
    try:
        record_task_started(**kwargs)
    except Exception:
        logger.exception("AI 任务观测开始事件写入失败")


def _safe_record_task_finished(**kwargs: Any) -> None:
    try:
        record_task_finished(**kwargs)
    except Exception:
        logger.exception("AI 任务观测结束事件写入失败")


@celery_app.task(name="resume.parse", bind=True, acks_late=True)
def parse_resume_task(task, document_id: str) -> dict[str, str | int | bool]:
    task_id = str(task.request.id)
    resolved_document_id = uuid.UUID(document_id)
    _safe_record_task_started(
        celery_task_id=task_id,
        task_name="resume.parse",
        scenario="resume_parse",
        resource_type="resume_document",
        resource_id=resolved_document_id,
        document_id=resolved_document_id,
        attempt_count=int(getattr(task.request, "retries", 0)) + 1,
    )
    try:
        result = process_resume_document(
            resolved_document_id,
            task_id=task_id,
        )
        if result.get("status") == "completed":
            try:
                application_id = result.get("application_id")
                result["analysis_task_id"] = enqueue_resume_analysis(
                    resolved_document_id,
                    application_id=(uuid.UUID(str(application_id)) if application_id else None),
                )
                result["analysis_enqueued"] = True
            except Exception:
                logger.exception("AI 分析任务创建失败，document_id=%s", document_id)
                result["analysis_enqueued"] = False
        _safe_record_task_finished(
            celery_task_id=task_id,
            succeeded=task_succeeded_from_result(result),
            failure_code=str(result.get("failure_code") or "") or None,
            failure_message=str(result.get("failure_message") or "") or None,
        )
        return result
    except Exception as error:
        _safe_record_task_finished(
            celery_task_id=task_id,
            succeeded=False,
            failure_code=error.__class__.__name__,
            failure_message=str(error)[:500],
        )
        raise


@celery_app.task(name="resume.analyze", bind=True, acks_late=True)
def analyze_resume_task(
    task,
    document_id: str,
    application_id: str | None = None,
    criteria_version_id: str | None = None,
    candidate_profile_id: str | None = None,
    analysis_version: int | None = None,
) -> dict[str, Any]:
    task_id = str(task.request.id)
    resolved_document_id = uuid.UUID(document_id)
    resolved_application_id = uuid.UUID(application_id) if application_id else None
    resolved_profile_id = uuid.UUID(candidate_profile_id) if candidate_profile_id else None
    _safe_record_task_started(
        celery_task_id=task_id,
        task_name="resume.analyze",
        scenario="resume_analysis",
        resource_type="resume_document",
        resource_id=resolved_document_id,
        document_id=resolved_document_id,
        application_id=resolved_application_id,
        candidate_profile_id=resolved_profile_id,
        attempt_count=int(getattr(task.request, "retries", 0)) + 1,
    )
    try:
        result = asyncio.run(
            analyze_resume_document(
                resolved_document_id,
                application_id=resolved_application_id,
                criteria_version_id=(
                    uuid.UUID(criteria_version_id) if criteria_version_id else None
                ),
                candidate_profile_id=resolved_profile_id,
                analysis_version=analysis_version,
                task_id=task_id,
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
        _safe_record_task_finished(
            celery_task_id=task_id,
            succeeded=task_succeeded_from_result(result),
            failure_code=str(result.get("failure_code") or "") or None,
            failure_message=str(result.get("failure_message") or "") or None,
        )
        return result
    except Exception as error:
        _safe_record_task_finished(
            celery_task_id=task_id,
            succeeded=False,
            failure_code=error.__class__.__name__,
            failure_message=str(error)[:500],
        )
        raise


@celery_app.task(name="knowledge.index_profile", bind=True, acks_late=True)
def index_candidate_profile_task(
    task,
    candidate_profile_id: str,
    force: bool = False,
) -> dict[str, Any]:
    task_id = str(task.request.id)
    resolved_profile_id = uuid.UUID(candidate_profile_id)
    _safe_record_task_started(
        celery_task_id=task_id,
        task_name="knowledge.index_profile",
        scenario="knowledge_index",
        resource_type="candidate_profile",
        resource_id=resolved_profile_id,
        candidate_profile_id=resolved_profile_id,
        attempt_count=int(getattr(task.request, "retries", 0)) + 1,
    )
    try:
        result = asyncio.run(
            index_candidate_profile(
                resolved_profile_id,
                task_id=task_id,
                force=force,
            )
        )
        _safe_record_task_finished(
            celery_task_id=task_id,
            succeeded=task_succeeded_from_result(result),
            failure_code=str(result.get("failure_code") or "") or None,
            failure_message=str(result.get("failure_message") or "") or None,
        )
        return result
    except Exception as error:
        _safe_record_task_finished(
            celery_task_id=task_id,
            succeeded=False,
            failure_code=error.__class__.__name__,
            failure_message=str(error)[:500],
        )
        raise


@celery_app.task(name="talent.recommendation.run", bind=True, acks_late=True)
def run_talent_recommendation_task(
    task,
    run_id: str,
    retry_failed_only: bool = False,
) -> dict[str, Any]:
    task_id = str(task.request.id)
    resolved_run_id = uuid.UUID(run_id)
    _safe_record_task_started(
        celery_task_id=task_id,
        task_name="talent.recommendation.run",
        scenario="talent_recommendation",
        resource_type="talent_recommendation_run",
        resource_id=resolved_run_id,
        attempt_count=int(getattr(task.request, "retries", 0)) + 1,
    )

    async def execute() -> dict[str, Any]:
        if retry_failed_only:
            return await rescore_talent_recommendations(
                resolved_run_id,
                task_id=task_id,
                retry_failed_only=True,
            )
        retrieval = await retrieve_talent_recommendations(
            resolved_run_id,
            task_id=task_id,
        )
        if retrieval.get("status") != "rescoring":
            return retrieval
        return await rescore_talent_recommendations(
            resolved_run_id,
            task_id=task_id,
        )

    try:
        result = asyncio.run(execute())
        _safe_record_task_finished(
            celery_task_id=task_id,
            succeeded=task_succeeded_from_result(result),
            failure_code=str(result.get("failure_code") or "") or None,
            failure_message=str(result.get("failure_message") or "") or None,
        )
        return result
    except Exception as error:
        _safe_record_task_finished(
            celery_task_id=task_id,
            succeeded=False,
            failure_code=error.__class__.__name__,
            failure_message=str(error)[:500],
        )
        raise
