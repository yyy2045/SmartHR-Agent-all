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
    offer_portal_verification_session_minutes: int = Field(default=15, ge=5, le=60)
    offer_portal_max_attempts: int = Field(default=5, ge=3, le=10)
    offer_portal_lock_minutes: int = Field(default=15, ge=5, le=60)
    workbench_offer_urgent_days: int = Field(default=2, ge=0, le=30)
    workbench_onboarding_urgent_days: int = Field(default=3, ge=0, le=30)

    initial_recruiter_username: str = "recruiter"
    initial_recruiter_password: str = "change-me-before-use"
    initial_recruiter_display_name: str = "招聘专员"

    database_url: str = "postgresql+psycopg://smarthr:smarthr-local-password@postgres:5432/smarthr"
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    celery_worker_concurrency: int = Field(default=2, ge=1, le=2)

    file_storage_root: Path = Path("data/local/uploads")
    max_resume_file_size_mb: int = 20
    max_knowledge_file_size_mb: int = 10
    max_batch_file_count: int = Field(default=50, ge=1, le=50)

    ai_base_url: str = "https://api.example.com/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout_seconds: int = 120
    ai_max_concurrency: int = Field(default=3, ge=1, le=10)

    embedding_enabled: bool = False
    embedding_base_url: str = "https://api.example.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimension: int = Field(default=1_536, ge=1, le=4_096)
    embedding_version: str = "v1"
    embedding_timeout_seconds: int = Field(default=120, ge=1, le=600)
    embedding_batch_size: int = Field(default=16, ge=1, le=100)
    embedding_max_concurrency: int = Field(default=2, ge=1, le=10)

    mineru_parse_base_url: str = "https://mineru.net/api/v4"
    mineru_parse_api_key: str = ""
    mineru_parse_model_version: str = "pipeline"
    mineru_parse_timeout_seconds: int = Field(default=30, ge=10, le=300)
    mineru_parse_poll_interval_seconds: float = Field(default=3.0, ge=0.0, le=30.0)
    mineru_parse_max_poll_seconds: int = Field(default=120, ge=30, le=600)
    knowledge_parse_force_ocr: bool = False
    knowledge_parse_language: str = "ch"
    knowledge_parse_enable_table: bool = True
    knowledge_parse_enable_formula: bool = True
    knowledge_parse_page_range: str | None = None

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
