import uuid

from app.workers import tasks


def test_parse_task_enqueues_analysis_only_after_completed_parse(monkeypatch) -> None:
    document_id = uuid.uuid4()
    enqueued: list[uuid.UUID] = []

    monkeypatch.setattr(
        tasks,
        "process_resume_document",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "document_id": str(document_id),
            "segments": 2,
        },
    )
    monkeypatch.setattr(
        tasks,
        "enqueue_resume_analysis",
        lambda value: enqueued.append(value) or "analysis-task-1",
    )

    completed = tasks.parse_resume_task.run(str(document_id))
    assert completed["analysis_enqueued"] is True
    assert completed["analysis_task_id"] == "analysis-task-1"
    assert enqueued == [document_id]

    monkeypatch.setattr(
        tasks,
        "process_resume_document",
        lambda *_args, **_kwargs: {
            "status": "failed",
            "document_id": str(document_id),
            "code": "empty_text",
        },
    )
    failed = tasks.parse_resume_task.run(str(document_id))
    assert "analysis_enqueued" not in failed
    assert enqueued == [document_id]
