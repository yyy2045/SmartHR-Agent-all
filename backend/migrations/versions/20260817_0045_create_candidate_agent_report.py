"""Create candidate assessment report table and add agent loop trajectory columns.

Revision ID: 20260817_0045
Revises: 20260805_0044
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260817_0045"
down_revision: str | None = "20260805_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_agent_exchanges",
        sa.Column(
            "tool_trajectory",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "candidate_agent_exchanges",
        sa.Column(
            "ai_call_log_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.alter_column("candidate_agent_exchanges", "tool_trajectory", server_default=None)
    op.alter_column("candidate_agent_exchanges", "ai_call_log_ids", server_default=None)

    op.create_table(
        "candidate_agent_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("match_assessment", sa.Text(), nullable=True),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("contradictions", sa.JSON(), nullable=False),
        sa.Column("evidence_gaps", sa.JSON(), nullable=False),
        sa.Column("next_step_suggestions", sa.JSON(), nullable=False),
        sa.Column("open_questions", sa.JSON(), nullable=False),
        sa.Column("overall_recommendation", sa.String(length=20), nullable=True),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_references", sa.JSON(), nullable=False),
        sa.Column("knowledge_citations", sa.JSON(), nullable=False),
        sa.Column("tool_trajectory", sa.JSON(), nullable=False),
        sa.Column("ai_call_log_ids", sa.JSON(), nullable=False),
        sa.Column("prompt_template_version_id", sa.Uuid(), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=120), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
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
            "status IN ('pending', 'succeeded', 'manual_fallback')",
            name="ck_candidate_agent_reports_status",
        ),
        sa.CheckConstraint(
            "overall_recommendation IS NULL OR overall_recommendation IN "
            "('hire', 'next_round', 'reserve', 'reject')",
            name="ck_candidate_agent_reports_overall_recommendation",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) BETWEEN 1 AND 80",
            name="ck_candidate_agent_reports_failure_code",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["job_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["prompt_template_version_id"],
            ["prompt_template_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id",
            "idempotency_key",
            name="uq_candidate_agent_reports_idempotency",
        ),
    )
    op.create_index(
        "ix_candidate_agent_reports_application_created",
        "candidate_agent_reports",
        ["application_id", "created_at"],
    )
    op.create_index(
        "ix_candidate_agent_reports_job_created",
        "candidate_agent_reports",
        ["job_id", "created_at"],
    )
    for column in (
        "application_id",
        "created_at",
        "created_by_id",
        "job_id",
        "prompt_template_version_id",
        "status",
    ):
        op.create_index(
            op.f(f"ix_candidate_agent_reports_{column}"),
            "candidate_agent_reports",
            [column],
        )


def downgrade() -> None:
    for column in (
        "status",
        "prompt_template_version_id",
        "job_id",
        "created_by_id",
        "created_at",
        "application_id",
    ):
        op.drop_index(
            op.f(f"ix_candidate_agent_reports_{column}"),
            table_name="candidate_agent_reports",
        )
    op.drop_index(
        "ix_candidate_agent_reports_job_created",
        table_name="candidate_agent_reports",
    )
    op.drop_index(
        "ix_candidate_agent_reports_application_created",
        table_name="candidate_agent_reports",
    )
    op.drop_table("candidate_agent_reports")

    op.drop_column("candidate_agent_exchanges", "ai_call_log_ids")
    op.drop_column("candidate_agent_exchanges", "tool_trajectory")
