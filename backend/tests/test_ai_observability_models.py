import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AiCallLog, AiTask, AiTaskEvent


@pytest.fixture
def ai_observability_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_ai_task_records_status_events_and_call_metrics(
    ai_observability_session_factory: sessionmaker[Session],
) -> None:
    task_id = uuid.uuid4()
    document_id = uuid.uuid4()
    completed_at = datetime.now(UTC)

    with ai_observability_session_factory() as db:
        task = AiTask(
            id=task_id,
            celery_task_id="celery-1",
            task_name="resume.analyze",
            scenario="resume_analysis",
            status="succeeded",
            attempt_count=1,
            max_retries=2,
            resource_type="resume_document",
            resource_id=document_id,
            document_id=document_id,
            duration_ms=1234,
            completed_at=completed_at,
        )
        task.events.append(
            AiTaskEvent(event_type="queued", status_after="queued", message="任务已入队")
        )
        task.events.append(
            AiTaskEvent(event_type="succeeded", status_after="succeeded", message="任务完成")
        )
        task.calls.append(
            AiCallLog(
                scenario="resume_analysis",
                status="succeeded",
                model_name="qwen-plus",
                prompt_version="resume-match-v2",
                retry_count=1,
                duration_ms=900,
                input_tokens=1200,
                output_tokens=300,
                total_tokens=1500,
                resource_type="resume_document",
                resource_id=document_id,
                document_id=document_id,
            )
        )
        db.add(task)
        db.commit()

        stored = db.scalars(select(AiTask).where(AiTask.id == task_id)).one()
        assert stored.events[0].event_type == "queued"
        assert stored.calls[0].total_tokens == 1500
        assert stored.calls[0].prompt_version == "resume-match-v2"


@pytest.mark.parametrize(
    "task_changes",
    [
        {"status": "done", "completed_at": None},
        {"task_name": "   "},
        {"scenario": ""},
        {"attempt_count": -1},
        {"max_retries": -1},
        {"duration_ms": -1},
        {"status": "succeeded", "completed_at": None},
        {"status": "running", "completed_at": datetime.now(UTC)},
    ],
)
def test_ai_task_constraints_reject_invalid_values(
    ai_observability_session_factory: sessionmaker[Session],
    task_changes: dict[str, object],
) -> None:
    task = AiTask(
        task_name="resume.parse",
        scenario="resume_parse",
        status="queued",
    )
    for key, value in task_changes.items():
        setattr(task, key, value)

    with ai_observability_session_factory() as db:
        db.add(task)
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "call_changes",
    [
        {"status": "timeout"},
        {"scenario": "   "},
        {"retry_count": -1},
        {"duration_ms": -1},
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"total_tokens": -1},
    ],
)
def test_ai_call_log_constraints_reject_invalid_values(
    ai_observability_session_factory: sessionmaker[Session],
    call_changes: dict[str, object],
) -> None:
    call = AiCallLog(scenario="jd_generation", status="succeeded")
    for key, value in call_changes.items():
        setattr(call, key, value)

    with ai_observability_session_factory() as db:
        db.add(call)
        with pytest.raises(IntegrityError):
            db.commit()


def test_task_event_constraints_reject_invalid_values(
    ai_observability_session_factory: sessionmaker[Session],
) -> None:
    with ai_observability_session_factory() as db:
        task = AiTask(task_name="resume.parse", scenario="resume_parse")
        task.events.append(AiTaskEvent(event_type="unknown", status_after="queued"))
        db.add(task)
        with pytest.raises(IntegrityError):
            db.commit()
