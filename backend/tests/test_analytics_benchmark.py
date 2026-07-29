import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite

from app.evaluation.analytics_benchmark import (
    BenchmarkConfig,
    database_name_is_safe,
    percentile,
)
from app.models import JobApplication
from app.services.analytics import _uuid_membership


def test_benchmark_database_guard_requires_suffix() -> None:
    assert database_name_is_safe("postgresql+psycopg://user:pass@db/app_benchmark")
    assert not database_name_is_safe("postgresql+psycopg://user:pass@db/app")
    assert not database_name_is_safe("sqlite+pysqlite:///:memory:")


def test_benchmark_uses_fixed_f23_scale() -> None:
    config = BenchmarkConfig()
    config.validate()

    assert config.job_count == 100
    assert config.application_count == 10_000
    assert config.process_event_count == 30_000


def test_benchmark_rejects_a_different_event_shape() -> None:
    with pytest.raises(ValueError, match="3 条流程事件"):
        BenchmarkConfig(process_events_per_application=2).validate()


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.5) == 2.0
    assert percentile([4.0, 1.0, 3.0, 2.0], 0.95) == 4.0


def test_large_uuid_filter_uses_one_postgresql_array_parameter() -> None:
    application_ids = tuple(uuid.uuid4() for _ in range(10_000))
    statement = select(JobApplication.id).where(
        _uuid_membership(
            JobApplication.id,
            application_ids,
            dialect_name="postgresql",
        )
    )

    compiled = statement.compile(dialect=postgresql.dialect())

    assert " = ANY (" in str(compiled)
    assert len(compiled.params) == 1
    assert next(iter(compiled.params.values())) == list(application_ids)


def test_uuid_filter_keeps_sqlite_expanding_in_compatibility() -> None:
    application_ids = (uuid.uuid4(), uuid.uuid4())
    statement = select(JobApplication.id).where(
        _uuid_membership(
            JobApplication.id,
            application_ids,
            dialect_name="sqlite",
        )
    )

    compiled = statement.compile(
        dialect=sqlite.dialect(),
        compile_kwargs={"render_postcompile": True},
    )

    assert " IN (?, ?)" in str(compiled)
    assert len(compiled.params) == 2
