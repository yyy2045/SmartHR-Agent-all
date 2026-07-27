"""关联已批准招聘需求与职位

Revision ID: 20260728_0017
Revises: 20260728_0016
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0017"
down_revision: str | None = "20260728_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("recruitment_request_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_jobs_recruitment_request_id",
        "jobs",
        "recruitment_requests",
        ["recruitment_request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_jobs_recruitment_request_id",
        "jobs",
        ["recruitment_request_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_jobs_recruitment_request_id", "jobs", type_="unique")
    op.drop_constraint("fk_jobs_recruitment_request_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "recruitment_request_id")
