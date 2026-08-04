from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AiEvaluationDataset,
    AiEvaluationErrorCase,
    AiEvaluationResult,
    AiEvaluationRun,
    AiEvaluationSample,
)
from app.services.ai_evaluation import (
    DEFAULT_RESUME_EVALUATION_DATASET_CODE,
    OfflineEvaluationOptions,
    ensure_default_resume_evaluation_dataset,
    run_offline_resume_evaluation,
)


@pytest.fixture
def ai_evaluation_service_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_ensure_default_resume_evaluation_dataset_is_idempotent(
    ai_evaluation_service_session_factory: sessionmaker[Session],
) -> None:
    with ai_evaluation_service_session_factory() as db:
        first = ensure_default_resume_evaluation_dataset(db)
        second = ensure_default_resume_evaluation_dataset(db)

        dataset_count = db.scalar(select(func.count(AiEvaluationDataset.id)))
        sample_count = db.scalar(select(func.count(AiEvaluationSample.id)))

    assert first.id == second.id
    assert first.code == DEFAULT_RESUME_EVALUATION_DATASET_CODE
    assert dataset_count == 1
    assert sample_count == 30


def test_run_offline_resume_evaluation_persists_passed_run(
    ai_evaluation_service_session_factory: sessionmaker[Session],
) -> None:
    with ai_evaluation_service_session_factory() as db:
        run = run_offline_resume_evaluation(db)

        result_count = db.scalar(select(func.count(AiEvaluationResult.id)))
        error_case_count = db.scalar(select(func.count(AiEvaluationErrorCase.id)))
        stored_run = db.get(AiEvaluationRun, run.id)

    assert stored_run is not None
    assert stored_run.status == "succeeded"
    assert stored_run.total_samples == 30
    assert stored_run.completed_samples == 30
    assert stored_run.passed_samples == 30
    assert stored_run.failed_samples == 0
    assert stored_run.average_score == 1.0
    assert stored_run.metrics_summary["pass_rate"] == 1.0
    assert result_count == 30
    assert error_case_count == 0


def test_run_offline_resume_evaluation_creates_error_cases_for_failed_samples(
    ai_evaluation_service_session_factory: sessionmaker[Session],
) -> None:
    with ai_evaluation_service_session_factory() as db:
        run = run_offline_resume_evaluation(
            db,
            options=OfflineEvaluationOptions(
                forced_error_case_keys=frozenset({"BE-01", "DA-01"})
            ),
        )

        failed_results = db.scalars(
            select(AiEvaluationResult).where(AiEvaluationResult.status == "failed")
        ).all()
        failed_case_keys = {result.sample.case_key for result in failed_results}
        error_cases = db.scalars(select(AiEvaluationErrorCase)).all()
        stored_run = db.get(AiEvaluationRun, run.id)

    assert stored_run is not None
    assert stored_run.status == "failed"
    assert stored_run.failed_samples == 2
    assert stored_run.passed_samples == 28
    assert stored_run.metrics_summary["error_counts"] == {
        "evidence_missing": 2,
        "wrong_recommendation": 2,
    }
    assert failed_case_keys == {"BE-01", "DA-01"}
    assert len(error_cases) == 4
    assert {case.error_type for case in error_cases} == {
        "evidence_missing",
        "wrong_recommendation",
    }
