import pytest
from pydantic import ValidationError

from app.config import Settings


def test_celery_worker_concurrency_defaults_to_two_and_accepts_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CELERY_WORKER_CONCURRENCY", raising=False)

    assert Settings(_env_file=None).celery_worker_concurrency == 2
    assert Settings(
        _env_file=None,
        celery_worker_concurrency=1,
    ).celery_worker_concurrency == 1


@pytest.mark.parametrize("value", [0, 3])
def test_celery_worker_concurrency_rejects_values_outside_limit(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, celery_worker_concurrency=value)


def test_batch_file_count_defaults_to_fifty_and_cannot_exceed_limit() -> None:
    assert Settings(_env_file=None).max_batch_file_count == 50
    assert Settings(_env_file=None, max_batch_file_count=1).max_batch_file_count == 1
    assert Settings(_env_file=None, max_batch_file_count=50).max_batch_file_count == 50
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_batch_file_count=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_batch_file_count=51)


def test_ai_concurrency_has_safe_bounds() -> None:
    assert Settings(_env_file=None).ai_max_concurrency == 3
    assert Settings(_env_file=None, ai_max_concurrency=1).ai_max_concurrency == 1
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_max_concurrency=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ai_max_concurrency=11)


def test_embedding_defaults_are_disabled_and_configuration_is_bounded() -> None:
    default = Settings(_env_file=None)
    assert default.embedding_enabled is False
    assert default.embedding_dimension == 1536
    assert default.embedding_batch_size == 16
    assert default.embedding_max_concurrency == 2
    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_dimension=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_batch_size=101)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_max_concurrency=11)
