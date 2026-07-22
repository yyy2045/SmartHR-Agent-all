import uuid

from app.services.resume_processing import process_resume_document
from app.workers.celery_app import celery_app


@celery_app.task(name="resume.parse", bind=True, acks_late=True)
def parse_resume_task(task, document_id: str) -> dict[str, str | int]:
    return process_resume_document(
        uuid.UUID(document_id),
        task_id=str(task.request.id),
    )
