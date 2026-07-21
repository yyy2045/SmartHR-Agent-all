from celery import Celery

from app.config import settings

celery_app = Celery(
    "smarthr_screening",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="system.ping")
def ping() -> dict[str, str]:
    return {"status": "pong"}
