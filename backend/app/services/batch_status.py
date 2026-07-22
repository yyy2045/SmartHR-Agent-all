from app.models import ScreeningBatch


def refresh_batch_status(batch: ScreeningBatch) -> None:
    failed_count = sum(item.status == "failed" for item in batch.documents)
    success_count = sum(item.status == "completed" for item in batch.documents)
    processing_count = sum(item.status in {"queued", "processing"} for item in batch.documents)
    uploaded_count = sum(item.status == "uploaded" for item in batch.documents)

    if processing_count:
        batch.status = "processing"
    elif failed_count and (success_count or uploaded_count):
        batch.status = "partial_failure"
    elif failed_count:
        batch.status = "failed"
    elif batch.documents and success_count == len(batch.documents):
        batch.status = "completed"
    else:
        batch.status = "ready"
