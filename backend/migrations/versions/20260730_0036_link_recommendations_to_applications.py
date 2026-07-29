"""Link talent recommendations to created job applications.

Revision ID: 20260730_0036
Revises: 20260730_0035
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0036"
down_revision: str | None = "20260730_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_talent_recommendation_results_id_run",
        "talent_recommendation_results",
        ["id", "run_id"],
    )
    op.add_column(
        "job_applications",
        sa.Column(
            "source_type",
            sa.String(length=30),
            nullable=False,
            server_default="resume_upload",
        ),
    )
    op.add_column(
        "job_applications",
        sa.Column("talent_recommendation_run_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "job_applications",
        sa.Column("talent_recommendation_result_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_job_applications_source_type",
        "job_applications",
        ["source_type"],
    )
    op.create_index(
        "ix_job_applications_talent_recommendation_run_id",
        "job_applications",
        ["talent_recommendation_run_id"],
    )
    op.create_index(
        "ix_job_applications_talent_recommendation_result_id",
        "job_applications",
        ["talent_recommendation_result_id"],
    )
    op.create_unique_constraint(
        "uq_job_applications_recommendation_result",
        "job_applications",
        ["talent_recommendation_result_id"],
    )
    op.create_foreign_key(
        "fk_job_applications_recommendation_result",
        "job_applications",
        "talent_recommendation_results",
        ["talent_recommendation_result_id", "talent_recommendation_run_id"],
        ["id", "run_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_job_applications_source_type",
        "job_applications",
        "source_type IN ('resume_upload', 'talent_recommendation')",
    )
    op.create_check_constraint(
        "ck_job_applications_recommendation_source",
        "job_applications",
        "(source_type = 'resume_upload' "
        "AND talent_recommendation_run_id IS NULL "
        "AND talent_recommendation_result_id IS NULL) OR "
        "(source_type = 'talent_recommendation' "
        "AND talent_recommendation_run_id IS NOT NULL "
        "AND talent_recommendation_result_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_job_applications_recommendation_source",
        "job_applications",
        type_="check",
    )
    op.drop_constraint(
        "ck_job_applications_source_type",
        "job_applications",
        type_="check",
    )
    op.drop_constraint(
        "fk_job_applications_recommendation_result",
        "job_applications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_job_applications_recommendation_result",
        "job_applications",
        type_="unique",
    )
    op.drop_index(
        "ix_job_applications_talent_recommendation_result_id",
        table_name="job_applications",
    )
    op.drop_index(
        "ix_job_applications_talent_recommendation_run_id",
        table_name="job_applications",
    )
    op.drop_index(
        "ix_job_applications_source_type",
        table_name="job_applications",
    )
    op.drop_column("job_applications", "talent_recommendation_result_id")
    op.drop_column("job_applications", "talent_recommendation_run_id")
    op.drop_column("job_applications", "source_type")
    op.drop_constraint(
        "uq_talent_recommendation_results_id_run",
        "talent_recommendation_results",
        type_="unique",
    )
