from __future__ import annotations

import pytest

from app.evaluation.talent_recommendation_benchmark import (
    BenchmarkConfig,
    database_name_is_safe,
    percentile,
)


def test_benchmark_database_guard_requires_suffix() -> None:
    assert database_name_is_safe(
        "postgresql+psycopg://user:pass@db/talent_recommendation_benchmark"
    )
    assert not database_name_is_safe(
        "postgresql+psycopg://user:pass@db/smarthr"
    )


def test_benchmark_uses_fixed_f27_scale() -> None:
    config = BenchmarkConfig()

    assert config.candidate_count == 10_000
    assert config.embedding_dimension == 1_536
    assert config.warmup_runs == 3
    assert config.p95_limit_ms == 1_000
    config.validate()


def test_benchmark_rejects_smaller_or_underwarmed_run() -> None:
    with pytest.raises(ValueError, match="10,000"):
        BenchmarkConfig(candidate_count=100).validate()
    with pytest.raises(ValueError, match="至少为 8"):
        BenchmarkConfig(embedding_dimension=4).validate()
    with pytest.raises(ValueError, match="预热 3 次"):
        BenchmarkConfig(warmup_runs=2).validate()


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.5) == 3.0
    assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.95) == 5.0
