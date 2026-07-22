import uuid

from app.workers.celery_app import celery_app


def enqueue_resume_parsing(document_id: uuid.UUID) -> str:
    result = celery_app.send_task("resume.parse", args=[str(document_id)])
    return str(result.id)


def enqueue_resume_analysis(document_id: uuid.UUID) -> str:
    result = celery_app.send_task("resume.analyze", args=[str(document_id)])
    return str(result.id)
