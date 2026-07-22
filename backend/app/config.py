from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SmartHR AI 简历筛选"
    app_env: str = "development"
    app_secret_key: str = Field(default="development-only-change-me", min_length=16)
    app_session_cookie: str = "smarthr_session"
    app_session_expire_minutes: int = 480
    app_session_secure: bool = False

    initial_recruiter_username: str = "recruiter"
    initial_recruiter_password: str = "change-me-before-use"
    initial_recruiter_display_name: str = "招聘专员"

    database_url: str = "postgresql+psycopg://smarthr:smarthr-local-password@postgres:5432/smarthr"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    celery_worker_concurrency: int = Field(default=1, ge=1, le=2)

    file_storage_root: Path = Path("data/local/uploads")
    max_resume_file_size_mb: int = 20
    max_batch_file_count: int = Field(default=2, ge=1, le=2)

    ai_base_url: str = "https://api.example.com/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout_seconds: int = 120
    ai_max_concurrency: int = Field(default=3, ge=1, le=10)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def session_cookie_secure(self) -> bool:
        return self.app_session_secure or self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
