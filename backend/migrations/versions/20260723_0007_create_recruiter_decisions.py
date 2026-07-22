"""创建招聘专员人工决策记录

Revision ID: 20260723_0007
Revises: 20260723_0006
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0007"
down_revision: str | None = "20260723_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruiter_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("screening_result_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("previous_decision", sa.String(20), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("is_auto_rejection_override", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('shortlisted', 'pending', 'rejected')",
            name="ck_recruiter_decisions_decision",
        ),
        sa.CheckConstraint(
            "previous_decision IN ('unprocessed', 'shortlisted', 'pending', 'rejected')",
            name="ck_recruiter_decisions_previous",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_recruiter_decisions_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["screening_result_id"], ["screening_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "screening_result_id",
            "sequence_number",
            name="uq_recruiter_decision_result_sequence",
        ),
    )
    op.create_index(
        op.f("ix_recruiter_decisions_operator_id"),
        "recruiter_decisions",
        ["operator_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recruiter_decisions_screening_result_id"),
        "recruiter_decisions",
        ["screening_result_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_recruiter_decisions_screening_result_id"),
        table_name="recruiter_decisions",
    )
    op.drop_index(
        op.f("ix_recruiter_decisions_operator_id"),
        table_name="recruiter_decisions",
    )
    op.drop_table("recruiter_decisions")
