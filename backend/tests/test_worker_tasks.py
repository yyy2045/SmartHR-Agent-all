import uuid

import pytest

from app.workers import tasks


def test_parse_task_enqueues_analysis_only_after_completed_parse(monkeypatch) -> None:
    document_id = uuid.uuid4()
    application_id = uuid.uuid4()
    enqueued: list[tuple[uuid.UUID, uuid.UUID | None]] = []

    monkeypatch.setattr(
        tasks,
        "process_resume_document",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "document_id": str(document_id),
            "application_id": str(application_id),
            "segments": 2,
        },
    )
    monkeypatch.setattr(
        tasks,
        "enqueue_resume_analysis",
        lambda value, application_id=None: enqueued.append((value, application_id))
        or "analysis-task-1",
    )

    completed = tasks.parse_resume_task.run(str(document_id))
    assert completed["analysis_enqueued"] is True
    assert completed["analysis_task_id"] == "analysis-task-1"
    assert enqueued == [(document_id, application_id)]

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
    assert enqueued == [(document_id, application_id)]


def test_analysis_task_enqueues_knowledge_index_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    enqueued: list[tuple[uuid.UUID, bool]] = []

    async def completed_analysis(*_args, **_kwargs):
        return {
            "status": "completed",
            "document_id": str(document_id),
            "candidate_profile_id": str(profile_id),
        }

    monkeypatch.setattr(tasks, "analyze_resume_document", completed_analysis)
    monkeypatch.setattr(tasks.settings, "embedding_enabled", True)
    monkeypatch.setattr(
        tasks,
        "enqueue_knowledge_index",
        lambda value, force=False: enqueued.append((value, force)) or "knowledge-task-1",
    )

    result = tasks.analyze_resume_task.run(str(document_id))

    assert result["knowledge_index_enqueued"] is True
    assert result["knowledge_index_task_id"] == "knowledge-task-1"
    assert enqueued == [(profile_id, False)]


def test_knowledge_index_task_passes_task_context(monkeypatch: pytest.MonkeyPatch) -> None:
    profile_id = uuid.uuid4()
    received: list[tuple[uuid.UUID, str, bool]] = []

    async def index_profile(value, *, task_id, force):
        received.append((value, task_id, force))
        return {"status": "completed", "chunk_count": 2}

    monkeypatch.setattr(tasks, "index_candidate_profile", index_profile)

    result = tasks.index_candidate_profile_task.run(str(profile_id), force=True)

    assert result == {"status": "completed", "chunk_count": 2}
    assert received == [(profile_id, "None", True)]


def test_talent_recommendation_task_dispatches_retrieval_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid.uuid4()
    received: list[tuple[uuid.UUID, str]] = []

    async def retrieve(value, *, task_id):
        received.append((value, task_id))
        return {"status": "rescoring", "retrieved_count": 3}

    monkeypatch.setattr(tasks, "retrieve_talent_recommendations", retrieve)

    result = tasks.run_talent_recommendation_task.run(str(run_id))
    retry = tasks.run_talent_recommendation_task.run(
        str(run_id),
        retry_failed_only=True,
    )

    assert result == {"status": "rescoring", "retrieved_count": 3}
    assert received == [(run_id, "None")]
    assert retry == {"status": "rescoring_retry_pending", "run_id": str(run_id)}
