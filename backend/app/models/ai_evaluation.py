from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.ai_observability import AiCallLog
    from app.models.prompt import PromptTemplateVersion
    from app.models.user import User


AI_EVALUATION_SCENARIOS = (
    "resume_analysis",
    "candidate_qa",
    "interview_report",
    "offer_copy",
    "candidate_comparison",
)
AI_EVALUATION_DATASET_STATUSES = ("active", "archived")
AI_EVALUATION_SAMPLE_DIFFICULTIES = ("easy", "medium", "hard")
AI_EVALUATION_RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
AI_EVALUATION_RESULT_STATUSES = ("passed", "failed", "error", "skipped")
AI_EVALUATION_ERROR_TYPES = (
    "wrong_recommendation",
    "evidence_missing",
    "hallucination",
    "format_error",
    "risk_omission",
    "timeout",
    "other",
)
AI_EVALUATION_ERROR_SEVERITIES = ("low", "medium", "high", "critical")
AI_EVALUATION_ERROR_STATUSES = ("open", "resolved", "ignored")

SCENARIO_SQL = ", ".join(f"'{item}'" for item in AI_EVALUATION_SCENARIOS)
DATASET_STATUS_SQL = ", ".join(f"'{item}'" for item in AI_EVALUATION_DATASET_STATUSES)
SAMPLE_DIFFICULTY_SQL = ", ".join(f"'{item}'" for item in AI_EVALUATION_SAMPLE_DIFFICULTIES)
RUN_STATUS_SQL = ", ".join(f"'{item}'" for item in AI_EVALUATION_RUN_STATUSES)
RESULT_STATUS_SQL = ", ".join(f"'{item}'" for item in AI_EVALUATION_RESULT_STATUSES)
ERROR_TYPE_SQL = ", ".join(f"'{item}'" for item in AI_EVALUATION_ERROR_TYPES)
ERROR_SEVERITY_SQL = ", ".join(f"'{item}'" for item in AI_EVALUATION_ERROR_SEVERITIES)
ERROR_STATUS_SQL = ", ".join(f"'{item}'" for item in AI_EVALUATION_ERROR_STATUSES)


class AiEvaluationDataset(Base):
    __tablename__ = "ai_evaluation_datasets"
    __table_args__ = (
        UniqueConstraint("code", name="uq_ai_evaluation_datasets_code"),
        CheckConstraint(f"scenario IN ({SCENARIO_SQL})", name="ck_ai_eval_datasets_scenario"),
        CheckConstraint(f"status IN ({DATASET_STATUS_SQL})", name="ck_ai_eval_datasets_status"),
        CheckConstraint("length(trim(code)) BETWEEN 1 AND 80", name="ck_ai_eval_datasets_code"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 160", name="ck_ai_eval_datasets_name"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 2000",
            name="ck_ai_eval_datasets_description",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_ai_eval_datasets_version_number",
        ),
        Index("ix_ai_evaluation_datasets_scenario_status", "scenario", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active", index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    samples: Mapped[list[AiEvaluationSample]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        order_by="AiEvaluationSample.case_key",
    )
    runs: Mapped[list[AiEvaluationRun]] = relationship(back_populates="dataset")


class AiEvaluationSample(Base):
    __tablename__ = "ai_evaluation_samples"
    __table_args__ = (
        UniqueConstraint("dataset_id", "case_key", name="uq_ai_eval_samples_case_key"),
        CheckConstraint(f"scenario IN ({SCENARIO_SQL})", name="ck_ai_eval_samples_scenario"),
        CheckConstraint(
            f"difficulty IN ({SAMPLE_DIFFICULTY_SQL})",
            name="ck_ai_eval_samples_difficulty",
        ),
        CheckConstraint("length(trim(case_key)) BETWEEN 1 AND 120", name="ck_ai_eval_samples_key"),
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 200", name="ck_ai_eval_samples_title"),
        CheckConstraint(
            "expected_recommendation IS NULL OR "
            "length(trim(expected_recommendation)) BETWEEN 1 AND 80",
            name="ck_ai_eval_samples_recommendation",
        ),
        Index("ix_ai_evaluation_samples_dataset_active", "dataset_id", "is_active"),
        Index("ix_ai_evaluation_samples_scenario", "scenario"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evaluation_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False)
    difficulty: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium", server_default="medium"
    )
    input_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    expected_output: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    expected_recommendation: Mapped[str | None] = mapped_column(String(80))
    expected_evidence_keywords: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    dataset: Mapped[AiEvaluationDataset] = relationship(back_populates="samples")
    results: Mapped[list[AiEvaluationResult]] = relationship(back_populates="sample")


class AiEvaluationRun(Base):
    __tablename__ = "ai_evaluation_runs"
    __table_args__ = (
        CheckConstraint(f"scenario IN ({SCENARIO_SQL})", name="ck_ai_eval_runs_scenario"),
        CheckConstraint(f"status IN ({RUN_STATUS_SQL})", name="ck_ai_eval_runs_status"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 160", name="ck_ai_eval_runs_name"),
        CheckConstraint("total_samples >= 0", name="ck_ai_eval_runs_total_samples"),
        CheckConstraint("completed_samples >= 0", name="ck_ai_eval_runs_completed_samples"),
        CheckConstraint("passed_samples >= 0", name="ck_ai_eval_runs_passed_samples"),
        CheckConstraint("failed_samples >= 0", name="ck_ai_eval_runs_failed_samples"),
        CheckConstraint(
            "average_score IS NULL OR (average_score >= 0 AND average_score <= 1)",
            name="ck_ai_eval_runs_average_score",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_eval_runs_duration_ms",
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="ck_ai_eval_runs_completed_at",
        ),
        Index("ix_ai_evaluation_runs_dataset_created", "dataset_id", "created_at"),
        Index("ix_ai_evaluation_runs_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evaluation_datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scenario: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued", index=True
    )
    provider: Mapped[str] = mapped_column(
        String(60), nullable=False, default="openai_compatible", server_default="openai_compatible"
    )
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_template_versions.id", ondelete="SET NULL"), index=True
    )
    prompt_version: Mapped[str | None] = mapped_column(String(120))
    run_config: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    metrics_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    total_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completed_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    passed_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    average_score: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    dataset: Mapped[AiEvaluationDataset] = relationship(back_populates="runs")
    prompt_template_version: Mapped[PromptTemplateVersion | None] = relationship(
        foreign_keys=[prompt_template_version_id]
    )
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    results: Mapped[list[AiEvaluationResult]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AiEvaluationResult.created_at",
    )


class AiEvaluationResult(Base):
    __tablename__ = "ai_evaluation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "sample_id", name="uq_ai_eval_results_run_sample"),
        CheckConstraint(f"status IN ({RESULT_STATUS_SQL})", name="ck_ai_eval_results_status"),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_ai_eval_results_score",
        ),
        CheckConstraint(
            "evidence_coverage_score IS NULL OR "
            "(evidence_coverage_score >= 0 AND evidence_coverage_score <= 1)",
            name="ck_ai_eval_results_evidence_score",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_eval_results_duration_ms",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_eval_results_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_eval_results_output_tokens",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_ai_eval_results_total_tokens",
        ),
        Index("ix_ai_evaluation_results_run_status", "run_id", "status"),
        Index("ix_ai_evaluation_results_sample", "sample_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evaluation_samples.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    score: Mapped[float | None] = mapped_column(Float)
    actual_output: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    expected_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    error_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_coverage_score: Mapped[float | None] = mapped_column(Float)
    format_valid: Mapped[bool | None] = mapped_column(Boolean)
    recommendation_matched: Mapped[bool | None] = mapped_column(Boolean)
    ai_call_log_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_call_logs.id", ondelete="SET NULL"), index=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    run: Mapped[AiEvaluationRun] = relationship(back_populates="results")
    sample: Mapped[AiEvaluationSample] = relationship(back_populates="results")
    ai_call_log: Mapped[AiCallLog | None] = relationship(foreign_keys=[ai_call_log_id])
    error_cases: Mapped[list[AiEvaluationErrorCase]] = relationship(
        back_populates="result",
        cascade="all, delete-orphan",
        order_by="AiEvaluationErrorCase.created_at",
    )


class AiEvaluationErrorCase(Base):
    __tablename__ = "ai_evaluation_error_cases"
    __table_args__ = (
        UniqueConstraint("result_id", "error_type", name="uq_ai_eval_error_cases_result_type"),
        CheckConstraint(f"error_type IN ({ERROR_TYPE_SQL})", name="ck_ai_eval_error_cases_type"),
        CheckConstraint(
            f"severity IN ({ERROR_SEVERITY_SQL})",
            name="ck_ai_eval_error_cases_severity",
        ),
        CheckConstraint(f"status IN ({ERROR_STATUS_SQL})", name="ck_ai_eval_error_cases_status"),
        CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 200",
            name="ck_ai_eval_error_cases_title",
        ),
        CheckConstraint(
            "description IS NULL OR length(description) <= 4000",
            name="ck_ai_eval_error_cases_description",
        ),
        CheckConstraint(
            "remediation_note IS NULL OR length(remediation_note) <= 4000",
            name="ck_ai_eval_error_cases_remediation",
        ),
        CheckConstraint(
            "(status IN ('resolved', 'ignored') AND resolved_at IS NOT NULL) OR "
            "(status = 'open' AND resolved_at IS NULL)",
            name="ck_ai_eval_error_cases_resolved_at",
        ),
        Index("ix_ai_evaluation_error_cases_status_severity", "status", "severity"),
        Index("ix_ai_evaluation_error_cases_dataset_created", "dataset_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evaluation_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evaluation_datasets.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evaluation_samples.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    error_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default="open", index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    expected_behavior: Mapped[str | None] = mapped_column(Text)
    actual_behavior: Mapped[str | None] = mapped_column(Text)
    remediation_note: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    result: Mapped[AiEvaluationResult] = relationship(back_populates="error_cases")
    dataset: Mapped[AiEvaluationDataset] = relationship(foreign_keys=[dataset_id])
    run: Mapped[AiEvaluationRun] = relationship(foreign_keys=[run_id])
    sample: Mapped[AiEvaluationSample] = relationship(foreign_keys=[sample_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])
