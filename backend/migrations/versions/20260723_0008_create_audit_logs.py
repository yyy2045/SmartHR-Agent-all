"""创建统一审计日志

Revision ID: 20260723_0008
Revises: 20260723_0007
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0008"
down_revision: str | None = "20260723_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("actor_username", sa.String(64)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.Uuid()),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("batch_id", sa.Uuid()),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('success', 'failure')",
            name="ck_audit_logs_result",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "action",
        "actor_user_id",
        "batch_id",
        "created_at",
        "job_id",
        "target_id",
    ):
        op.create_index(
            op.f(f"ix_audit_logs_{column}"),
            "audit_logs",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "target_id",
        "job_id",
        "created_at",
        "batch_id",
        "actor_user_id",
        "action",
    ):
        op.drop_index(op.f(f"ix_audit_logs_{column}"), table_name="audit_logs")
    op.drop_table("audit_logs")
