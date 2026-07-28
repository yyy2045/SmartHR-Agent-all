"""Widen candidate process stage columns.

Revision ID: 20260729_0026
Revises: 20260729_0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0026"
down_revision: str | None = "20260729_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "candidate_processes",
        "current_stage",
        existing_type=sa.String(length=30),
        type_=sa.String(length=40),
        existing_nullable=False,
    )
    op.alter_column(
        "candidate_process_events",
        "from_stage",
        existing_type=sa.String(length=30),
        type_=sa.String(length=40),
        existing_nullable=False,
    )
    op.alter_column(
        "candidate_process_events",
        "to_stage",
        existing_type=sa.String(length=30),
        type_=sa.String(length=40),
        existing_nullable=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE candidate_processes SET current_stage = 'completed' "
            "WHERE current_stage = 'onboarding_pending_confirmation'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE candidate_process_events SET from_stage = 'completed' "
            "WHERE from_stage = 'onboarding_pending_confirmation'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE candidate_process_events SET to_stage = 'completed' "
            "WHERE to_stage = 'onboarding_pending_confirmation'"
        )
    )
    op.alter_column(
        "candidate_process_events",
        "to_stage",
        existing_type=sa.String(length=40),
        type_=sa.String(length=30),
        existing_nullable=False,
    )
    op.alter_column(
        "candidate_process_events",
        "from_stage",
        existing_type=sa.String(length=40),
        type_=sa.String(length=30),
        existing_nullable=False,
    )
    op.alter_column(
        "candidate_processes",
        "current_stage",
        existing_type=sa.String(length=40),
        type_=sa.String(length=30),
        existing_nullable=False,
    )
