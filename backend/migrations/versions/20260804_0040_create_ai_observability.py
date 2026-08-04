"""Create AI observability tables.

Revision ID: 20260804_0040
Revises: 20260730_0039
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0040"
down_revision: str | None = "20260730_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=120), nullable=True),
        sa.Column("task_name", sa.String(length=120), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'retrying', 'cancelled')",
            name="ck_ai_tasks_status",
        ),
        sa.CheckConstraint("length(trim(task_name)) BETWEEN 1 AND 120", name="ck_ai_tasks_name"),
        sa.CheckConstraint(
            "length(trim(scenario)) BETWEEN 1 AND 80", name="ck_ai_tasks_scenario"
        ),
        sa.CheckConstraint(
            "resource_type IS NULL OR length(trim(resource_type)) BETWEEN 1 AND 80",
            name="ck_ai_tasks_resource_type",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ai_tasks_attempt_count"),
        sa.CheckConstraint("max_retries >= 0", name="ck_ai_tasks_max_retries"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_tasks_duration_ms",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'failed', 'cancelled') AND completed_at IS NULL)",
            name="ck_ai_tasks_completed_at",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id", name="uq_ai_tasks_celery_task_id"),
    )
    op.create_index("ix_ai_tasks_celery_task_id", "ai_tasks", ["celery_task_id"])
    op.create_index("ix_ai_tasks_status", "ai_tasks", ["status"])
    op.create_index("ix_ai_tasks_scenario", "ai_tasks", ["scenario"])
    op.create_index("ix_ai_tasks_created_by_id", "ai_tasks", ["created_by_id"])
    op.create_index("ix_ai_tasks_resource_id", "ai_tasks", ["resource_id"])
    op.create_index("ix_ai_tasks_job_id", "ai_tasks", ["job_id"])
    op.create_index("ix_ai_tasks_batch_id", "ai_tasks", ["batch_id"])
    op.create_index("ix_ai_tasks_document_id", "ai_tasks", ["document_id"])
    op.create_index("ix_ai_tasks_application_id", "ai_tasks", ["application_id"])
    op.create_index("ix_ai_tasks_candidate_profile_id", "ai_tasks", ["candidate_profile_id"])
    op.create_index("ix_ai_tasks_created_at", "ai_tasks", ["created_at"])
    op.create_index("ix_ai_tasks_status_created", "ai_tasks", ["status", "created_at"])
    op.create_index("ix_ai_tasks_resource", "ai_tasks", ["resource_type", "resource_id"])

    op.create_table(
        "ai_task_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("status_after", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "event_type IN ('queued', 'started', 'retry_scheduled', 'succeeded', 'failed', "
            "'cancelled')",
            name="ck_ai_task_events_type",
        ),
        sa.CheckConstraint(
            "status_after IN ('queued', 'running', 'succeeded', 'failed', 'retrying', "
            "'cancelled')",
            name="ck_ai_task_events_status_after",
        ),
        sa.CheckConstraint(
            "length(message) <= 500",
            name="ck_ai_task_events_message_length",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["ai_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_task_events_task_id", "ai_task_events", ["task_id"])
    op.create_index("ix_ai_task_events_created_at", "ai_task_events", ["created_at"])
    op.create_index(
        "ix_ai_task_events_task_created", "ai_task_events", ["task_id", "created_at"]
    )

    op.create_table(
        "ai_call_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=120), nullable=True),
        sa.Column(
            "provider", sa.String(length=60), server_default="openai_compatible", nullable=False
        ),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("invoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('succeeded', 'failed')", name="ck_ai_call_logs_status"),
        sa.CheckConstraint(
            "length(trim(scenario)) BETWEEN 1 AND 80", name="ck_ai_call_logs_scenario"
        ),
        sa.CheckConstraint(
            "resource_type IS NULL OR length(trim(resource_type)) BETWEEN 1 AND 80",
            name="ck_ai_call_logs_resource_type",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_ai_call_logs_retry_count"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ai_call_logs_duration_ms",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_call_logs_input_tokens",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_call_logs_output_tokens",
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name="ck_ai_call_logs_total_tokens",
        ),
        sa.ForeignKeyConstraint(["invoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["ai_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_call_logs_task_id", "ai_call_logs", ["task_id"])
    op.create_index("ix_ai_call_logs_scenario", "ai_call_logs", ["scenario"])
    op.create_index("ix_ai_call_logs_status", "ai_call_logs", ["status"])
    op.create_index("ix_ai_call_logs_invoked_by_id", "ai_call_logs", ["invoked_by_id"])
    op.create_index("ix_ai_call_logs_resource_id", "ai_call_logs", ["resource_id"])
    op.create_index("ix_ai_call_logs_job_id", "ai_call_logs", ["job_id"])
    op.create_index("ix_ai_call_logs_batch_id", "ai_call_logs", ["batch_id"])
    op.create_index("ix_ai_call_logs_document_id", "ai_call_logs", ["document_id"])
    op.create_index("ix_ai_call_logs_application_id", "ai_call_logs", ["application_id"])
    op.create_index(
        "ix_ai_call_logs_candidate_profile_id", "ai_call_logs", ["candidate_profile_id"]
    )
    op.create_index("ix_ai_call_logs_created_at", "ai_call_logs", ["created_at"])
    op.create_index(
        "ix_ai_call_logs_scenario_created", "ai_call_logs", ["scenario", "created_at"]
    )
    op.create_index("ix_ai_call_logs_status_created", "ai_call_logs", ["status", "created_at"])
    op.create_index("ix_ai_call_logs_resource", "ai_call_logs", ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_call_logs_resource", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_status_created", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_scenario_created", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_created_at", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_candidate_profile_id", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_application_id", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_document_id", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_batch_id", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_job_id", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_resource_id", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_invoked_by_id", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_status", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_scenario", table_name="ai_call_logs")
    op.drop_index("ix_ai_call_logs_task_id", table_name="ai_call_logs")
    op.drop_table("ai_call_logs")

    op.drop_index("ix_ai_task_events_task_created", table_name="ai_task_events")
    op.drop_index("ix_ai_task_events_created_at", table_name="ai_task_events")
    op.drop_index("ix_ai_task_events_task_id", table_name="ai_task_events")
    op.drop_table("ai_task_events")

    op.drop_index("ix_ai_tasks_resource", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_status_created", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_created_at", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_candidate_profile_id", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_application_id", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_document_id", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_batch_id", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_job_id", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_resource_id", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_created_by_id", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_scenario", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_status", table_name="ai_tasks")
    op.drop_index("ix_ai_tasks_celery_task_id", table_name="ai_tasks")
    op.drop_table("ai_tasks")
