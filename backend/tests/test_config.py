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
