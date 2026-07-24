"""增加批次 AI 输入模式

Revision ID: 20260723_0009
Revises: 20260723_0008
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0009"
down_revision: str | None = "20260723_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "screening_batches",
        sa.Column(
            "ai_input_mode",
            sa.String(length=20),
            server_default="raw",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_screening_batches_ai_input_mode",
        "screening_batches",
        "ai_input_mode IN ('raw', 'redacted')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_screening_batches_ai_input_mode",
        "screening_batches",
        type_="check",
    )
    op.drop_column("screening_batches", "ai_input_mode")
