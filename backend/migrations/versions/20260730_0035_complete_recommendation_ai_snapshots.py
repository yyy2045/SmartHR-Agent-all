"""Complete recommendation AI result snapshots.

Revision ID: 20260730_0035
Revises: 20260730_0034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0035"
down_revision: str | None = "20260730_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SNAPSHOT_COLUMNS = (
    "ai_hard_requirement_results",
    "ai_strengths",
    "ai_gaps",
    "ai_missing_items",
    "ai_interview_questions",
)


def upgrade() -> None:
    for column_name in SNAPSHOT_COLUMNS:
        op.add_column(
            "talent_recommendation_results",
            sa.Column(column_name, sa.JSON(), nullable=True),
        )
        op.execute(
            sa.text(
                f"UPDATE talent_recommendation_results "
                f"SET {column_name} = CAST('[]' AS JSON) "
                f"WHERE {column_name} IS NULL"
            )
        )
        op.alter_column(
            "talent_recommendation_results",
            column_name,
            existing_type=sa.JSON(),
            nullable=False,
        )


def downgrade() -> None:
    for column_name in reversed(SNAPSHOT_COLUMNS):
        op.drop_column("talent_recommendation_results", column_name)
