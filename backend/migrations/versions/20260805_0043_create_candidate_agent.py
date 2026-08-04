"""Create candidate QA agent tables.

Revision ID: 20260805_0043
Revises: 20260805_0042
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0043"
down_revision: str | None = "20260805_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_agent_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
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
            "status IN ('active', 'archived')",
            name="ck_candidate_agent_sessions_status",
        ),
        sa.CheckConstraint(
            "title IS NULL OR length(trim(title)) BETWEEN 1 AND 120",
            name="ck_candidate_agent_sessions_title",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["job_applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_candidate_agent_sessions_application_status",
        "candidate_agent_sessions",
        ["application_id", "status"],
    )
    op.create_index(
        "ix_candidate_agent_sessions_job_created",
        "candidate_agent_sessions",
        ["job_id", "created_at"],
    )
    for column in ("application_id", "created_at", "created_by_id", "job_id", "status"):
        op.create_index(
            op.f(f"ix_candidate_agent_sessions_{column}"),
            "candidate_agent_sessions",
            [column],
        )

    op.create_table(
        "candidate_agent_exchanges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_references", sa.JSON(), nullable=False),
        sa.Column("knowledge_citations", sa.JSON(), nullable=False),
        sa.Column("ai_call_log_id", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'manual_fallback')",
            name="ck_candidate_agent_exchanges_status",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_candidate_agent_exchanges_sequence",
        ),
        sa.CheckConstraint(
            "length(trim(question)) BETWEEN 1 AND 2000",
            name="ck_candidate_agent_exchanges_question",
        ),
        sa.CheckConstraint(
            "answer IS NULL OR length(answer) <= 8000",
            name="ck_candidate_agent_exchanges_answer",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) BETWEEN 1 AND 80",
            name="ck_candidate_agent_exchanges_failure_code",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'manual_fallback') AND answer IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'manual_fallback'))",
            name="ck_candidate_agent_exchanges_completed_answer",
        ),
        sa.ForeignKeyConstraint(["ai_call_log_id"], ["ai_call_logs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["prompt_template_version_id"],
            ["prompt_template_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["candidate_agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "idempotency_key",
            name="uq_candidate_agent_exchanges_idempotency",
        ),
        sa.UniqueConstraint(
            "session_id",
            "sequence_number",
            name="uq_candidate_agent_exchanges_sequence",
        ),
    )
    op.create_index(
        "ix_candidate_agent_exchanges_session_created",
        "candidate_agent_exchanges",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_candidate_agent_exchanges_status_created",
        "candidate_agent_exchanges",
        ["status", "created_at"],
    )
    for column in (
        "ai_call_log_id",
        "created_at",
        "created_by_id",
        "prompt_template_version_id",
        "session_id",
        "status",
    ):
        op.create_index(
            op.f(f"ix_candidate_agent_exchanges_{column}"),
            "candidate_agent_exchanges",
            [column],
        )


def downgrade() -> None:
    for column in (
        "status",
        "session_id",
        "prompt_template_version_id",
        "created_by_id",
        "created_at",
        "ai_call_log_id",
    ):
        op.drop_index(
            op.f(f"ix_candidate_agent_exchanges_{column}"),
            table_name="candidate_agent_exchanges",
        )
    op.drop_index(
        "ix_candidate_agent_exchanges_status_created",
        table_name="candidate_agent_exchanges",
    )
    op.drop_index(
        "ix_candidate_agent_exchanges_session_created",
        table_name="candidate_agent_exchanges",
    )
    op.drop_table("candidate_agent_exchanges")

    for column in ("status", "job_id", "created_by_id", "created_at", "application_id"):
        op.drop_index(
            op.f(f"ix_candidate_agent_sessions_{column}"),
            table_name="candidate_agent_sessions",
        )
    op.drop_index(
        "ix_candidate_agent_sessions_job_created",
        table_name="candidate_agent_sessions",
    )
    op.drop_index(
        "ix_candidate_agent_sessions_application_status",
        table_name="candidate_agent_sessions",
    )
    op.drop_table("candidate_agent_sessions")
