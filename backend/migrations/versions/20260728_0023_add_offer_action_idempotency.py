"""Add Offer action idempotency fields.

Revision ID: 20260728_0023
Revises: 20260728_0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0023"
down_revision: str | None = "20260728_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "offer_versions",
        sa.Column("submission_idempotency_key", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "offer_versions",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_offer_submission_idempotency",
        "offer_versions",
        ["offer_id", "submission_idempotency_key"],
    )
    op.add_column(
        "offer_manager_confirmations",
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE offer_manager_confirmations "
            "SET idempotency_key = gen_random_uuid() "
            "WHERE idempotency_key IS NULL"
        )
    )
    op.alter_column("offer_manager_confirmations", "idempotency_key", nullable=False)
    op.add_column(
        "offer_approvals",
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE offer_approvals "
            "SET idempotency_key = gen_random_uuid() "
            "WHERE idempotency_key IS NULL"
        )
    )
    op.alter_column("offer_approvals", "idempotency_key", nullable=False)


def downgrade() -> None:
    op.drop_column("offer_approvals", "idempotency_key")
    op.drop_column("offer_manager_confirmations", "idempotency_key")
    op.drop_constraint(
        "uq_offer_submission_idempotency",
        "offer_versions",
        type_="unique",
    )
    op.drop_column("offer_versions", "submitted_at")
    op.drop_column("offer_versions", "submission_idempotency_key")
