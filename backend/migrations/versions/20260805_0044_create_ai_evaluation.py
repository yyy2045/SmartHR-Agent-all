"""Create AI evaluation tables.

Revision ID: 20260805_0044
Revises: 20260805_0043
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0044"
down_revision: str | None = "20260805_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_evaluation_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scenario IN ('resume_analysis', 'candidate_qa', 'interview_report', "
            "'offer_copy', 'candidate_comparison')",
            name="ck_ai_eval_datasets_scenario",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_ai_eval_datasets_status",
        ),
        sa.CheckConstraint(
            "length(trim(code)) BETWEEN 1 AND 80",
            name="ck_ai_eval_datasets_code",
        ),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160",
            name="ck_ai_eval_datasets_name",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 2000",
            name="ck_ai_eval_datasets_description",
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_ai_eval_datasets_version_number"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_ai_evaluation_datasets_code"),
    )
    op.create_index(
        "ix_ai_evaluation_datasets_scenario_status",
        "ai_evaluation_datasets",
        ["scenario", "status"],
    )
    for column in ("created_at", "created_by_id", "scenario", "status"):
        op.create_index(
            op.f(f"ix_ai_evaluation_datasets_{column}"),
            "ai_evaluation_datasets",
            [column],
        )

    op.create_table(
        "ai_evaluation_samples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("case_key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("difficulty", sa.String(length=20), server_default="medium", nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("expected_output", sa.JSON(), nullable=False),
        sa.Column("expected_recommendation", sa.String(length=80), nullable=True),
        sa.Column("expected_evidence_keywords", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scenario IN ('resume_analysis', 'candidate_qa', 'interview_report', "
            "'offer_copy', 'candidate_comparison')",
            name="ck_ai_eval_samples_scenario",
        ),
        sa.CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')",
            name="ck_ai_eval_samples_difficulty",
        ),
        sa.CheckConstraint(
            "length(trim(case_key)) BETWEEN 1 AND 120",
            name="ck_ai_eval_samples_key",
        ),
        sa.CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 200",
            name="ck_ai_eval_samples_title",
        ),
        sa.CheckConstraint(
            "expected_recommendation IS NULL OR "
            "length(trim(expected_recommendation)) BETWEEN 1 AND 80",
            name="ck_ai_eval_samples_recommendation",
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["ai_evaluation_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "case_key", name="uq_ai_eval_samples_case_key"),
    )
    op.create_index(
        "ix_ai_evaluation_samples_dataset_active",
        "ai_evaluation_samples",
        ["dataset_id", "is_active"],
    )
    op.create_index("ix_ai_evaluation_samples_scenario", "ai_evaluation_samples", ["scenario"])
    for column in ("created_at", "dataset_id", "scenario"):
        op.create_index(
            op.f(f"ix_ai_evaluation_samples_{column}"),
            "ai_evaluation_samples",
            [column],
        )

    op.create_table(
        "ai_evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column(
            "provider",
            sa.String(length=60),
            server_default="openai_compatible",
            nullable=False,
        ),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("prompt_template_version_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_version", sa.String(length=120), nullable=True),
        sa.Column("run_config", sa.JSON(), nullable=False),
        sa.Column("metrics_summary", sa.JSON(), nullable=False),
        sa.Column("total_samples", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_samples", sa.Integer(), server_default="0", nullable=False),
        sa.Column("passed_samples", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_samples", sa.Integer(), server_default="0", nullable=False),
        sa.Column("average_score", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scenario IN ('resume_analysis', 'candidate_qa', 'interview_report', "
            "'offer_copy', 'candidate_comparison')",
            name="ck_ai_eval_runs_scenario",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_ai_eval_runs_status",
        ),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 160",
            name="ck_ai_eval_runs_name",
        ),
        sa.CheckConstraint("total_samples >= 0", name="ck_ai_eval_runs_total_samples"),
        sa.CheckConstraint("completed_samples >= 0", name="ck_ai_eval_runs_completed_samples"),
        sa.CheckConstraint("passed_samples >= 0", name="ck_ai_eval_runs_passed_samples"),
        sa.CheckConstraint("failed_samples >= 0", name="ck_ai_eval_runs_failed_samples"),
        sa.CheckConstraint(
            "average_score IS NULL OR (average_score >= 0 AND average_score <= 1)",
            name="ck_ai_eval_runs_average_score",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_eval_runs_duration_ms",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="ck_ai_eval_runs_completed_at",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dataset_id"], ["ai_evaluation_datasets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["prompt_template_version_id"],
            ["prompt_template_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_evaluation_runs_dataset_created",
        "ai_evaluation_runs",
        ["dataset_id", "created_at"],
    )
    op.create_index(
        "ix_ai_evaluation_runs_status_created",
        "ai_evaluation_runs",
        ["status", "created_at"],
    )
    for column in (
        "created_at",
        "created_by_id",
        "dataset_id",
        "prompt_template_version_id",
        "scenario",
        "status",
    ):
        op.create_index(op.f(f"ix_ai_evaluation_runs_{column}"), "ai_evaluation_runs", [column])

    op.create_table(
        "ai_evaluation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sample_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("actual_output", sa.JSON(), nullable=False),
        sa.Column("expected_snapshot", sa.JSON(), nullable=False),
        sa.Column("error_types", sa.JSON(), nullable=False),
        sa.Column("evidence_coverage_score", sa.Float(), nullable=True),
        sa.Column("format_valid", sa.Boolean(), nullable=True),
        sa.Column("recommendation_matched", sa.Boolean(), nullable=True),
        sa.Column("ai_call_log_id", sa.Uuid(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'error', 'skipped')",
            name="ck_ai_eval_results_status",
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_ai_eval_results_score",
        ),
        sa.CheckConstraint(
            "evidence_coverage_score IS NULL OR "
            "(evidence_coverage_score >= 0 AND evidence_coverage_score <= 1)",
            name="ck_ai_eval_results_evidence_score",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_eval_results_duration_ms",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_eval_results_input_tokens",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_eval_results_output_tokens",
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_ai_eval_results_total_tokens",
        ),
        sa.ForeignKeyConstraint(["ai_call_log_id"], ["ai_call_logs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["ai_evaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sample_id"], ["ai_evaluation_samples.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sample_id", name="uq_ai_eval_results_run_sample"),
    )
    op.create_index(
        "ix_ai_evaluation_results_run_status",
        "ai_evaluation_results",
        ["run_id", "status"],
    )
    op.create_index("ix_ai_evaluation_results_sample", "ai_evaluation_results", ["sample_id"])
    for column in ("ai_call_log_id", "created_at", "run_id", "sample_id", "status"):
        op.create_index(
            op.f(f"ix_ai_evaluation_results_{column}"),
            "ai_evaluation_results",
            [column],
        )

    op.create_table(
        "ai_evaluation_error_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("result_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sample_id", sa.Uuid(), nullable=False),
        sa.Column("error_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expected_behavior", sa.Text(), nullable=True),
        sa.Column("actual_behavior", sa.Text(), nullable=True),
        sa.Column("remediation_note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "error_type IN ('wrong_recommendation', 'evidence_missing', 'hallucination', "
            "'format_error', 'risk_omission', 'timeout', 'other')",
            name="ck_ai_eval_error_cases_type",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_ai_eval_error_cases_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'ignored')",
            name="ck_ai_eval_error_cases_status",
        ),
        sa.CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 200",
            name="ck_ai_eval_error_cases_title",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 4000",
            name="ck_ai_eval_error_cases_description",
        ),
        sa.CheckConstraint(
            "remediation_note IS NULL OR length(remediation_note) <= 4000",
            name="ck_ai_eval_error_cases_remediation",
        ),
        sa.CheckConstraint(
            "(status IN ('resolved', 'ignored') AND resolved_at IS NOT NULL) OR "
            "(status = 'open' AND resolved_at IS NULL)",
            name="ck_ai_eval_error_cases_resolved_at",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["ai_evaluation_datasets.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["result_id"], ["ai_evaluation_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["ai_evaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sample_id"], ["ai_evaluation_samples.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("result_id", "error_type", name="uq_ai_eval_error_cases_result_type"),
    )
    op.create_index(
        "ix_ai_evaluation_error_cases_status_severity",
        "ai_evaluation_error_cases",
        ["status", "severity"],
    )
    op.create_index(
        "ix_ai_evaluation_error_cases_dataset_created",
        "ai_evaluation_error_cases",
        ["dataset_id", "created_at"],
    )
    for column in (
        "created_at",
        "created_by_id",
        "dataset_id",
        "error_type",
        "resolved_by_id",
        "result_id",
        "run_id",
        "sample_id",
        "status",
    ):
        op.create_index(
            op.f(f"ix_ai_evaluation_error_cases_{column}"),
            "ai_evaluation_error_cases",
            [column],
        )


def downgrade() -> None:
    for column in (
        "status",
        "sample_id",
        "run_id",
        "result_id",
        "resolved_by_id",
        "error_type",
        "dataset_id",
        "created_by_id",
        "created_at",
    ):
        op.drop_index(
            op.f(f"ix_ai_evaluation_error_cases_{column}"),
            table_name="ai_evaluation_error_cases",
        )
    op.drop_index(
        "ix_ai_evaluation_error_cases_dataset_created",
        table_name="ai_evaluation_error_cases",
    )
    op.drop_index(
        "ix_ai_evaluation_error_cases_status_severity",
        table_name="ai_evaluation_error_cases",
    )
    op.drop_table("ai_evaluation_error_cases")

    for column in ("status", "sample_id", "run_id", "created_at", "ai_call_log_id"):
        op.drop_index(
            op.f(f"ix_ai_evaluation_results_{column}"),
            table_name="ai_evaluation_results",
        )
    op.drop_index("ix_ai_evaluation_results_sample", table_name="ai_evaluation_results")
    op.drop_index("ix_ai_evaluation_results_run_status", table_name="ai_evaluation_results")
    op.drop_table("ai_evaluation_results")

    for column in (
        "status",
        "scenario",
        "prompt_template_version_id",
        "dataset_id",
        "created_by_id",
        "created_at",
    ):
        op.drop_index(op.f(f"ix_ai_evaluation_runs_{column}"), table_name="ai_evaluation_runs")
    op.drop_index("ix_ai_evaluation_runs_status_created", table_name="ai_evaluation_runs")
    op.drop_index("ix_ai_evaluation_runs_dataset_created", table_name="ai_evaluation_runs")
    op.drop_table("ai_evaluation_runs")

    for column in ("scenario", "dataset_id", "created_at"):
        op.drop_index(
            op.f(f"ix_ai_evaluation_samples_{column}"),
            table_name="ai_evaluation_samples",
        )
    op.drop_index("ix_ai_evaluation_samples_scenario", table_name="ai_evaluation_samples")
    op.drop_index("ix_ai_evaluation_samples_dataset_active", table_name="ai_evaluation_samples")
    op.drop_table("ai_evaluation_samples")

    for column in ("status", "scenario", "created_by_id", "created_at"):
        op.drop_index(
            op.f(f"ix_ai_evaluation_datasets_{column}"),
            table_name="ai_evaluation_datasets",
        )
    op.drop_index(
        "ix_ai_evaluation_datasets_scenario_status",
        table_name="ai_evaluation_datasets",
    )
    op.drop_table("ai_evaluation_datasets")
