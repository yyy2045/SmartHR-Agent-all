import pytest
from pydantic import ValidationError

from app.config import Settings


def test_celery_worker_concurrency_defaults_to_one_and_accepts_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CELERY_WORKER_CONCURRENCY", raising=False)

    assert Settings(_env_file=None).celery_worker_concurrency == 1
    assert Settings(
        _env_file=None,
        celery_worker_concurrency=2,
    ).celery_worker_concurrency == 2


@pytest.mark.parametrize("value", [0, 3])
def test_celery_worker_concurrency_rejects_values_outside_limit(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, celery_worker_concurrency=value)


def test_batch_file_count_defaults_to_two_and_cannot_exceed_limit() -> None:
    assert Settings(_env_file=None).max_batch_file_count == 2
    assert Settings(_env_file=None, max_batch_file_count=1).max_batch_file_count == 1
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_batch_file_count=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_batch_file_count=3)


def test_ai_concurrency_has_safe_bounds() -> None:
    assert Settings(_env_file=None).ai_max_concurrency == 3
    assert Settings(_env_file=None, ai_max_concurrency=1).ai_max_concurrency == 1
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_max_concurrency=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_max_concurrency=11)
