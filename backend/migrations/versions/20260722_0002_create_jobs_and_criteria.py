"""创建职位与筛选标准表

Revision ID: 20260722_0002
Revises: 20260721_0001
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0002"
down_revision: str | None = "20260721_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=False),
        sa.Column("original_jd", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_jobs_status"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_owner_id"), "jobs", ["owner_id"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)

    op.create_table(
        "job_criteria_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("pass_threshold", sa.Integer(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_by_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "pass_threshold >= 0 AND pass_threshold <= 100",
            name="ck_job_criteria_pass_threshold",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed')",
            name="ck_job_criteria_status",
        ),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["job_criteria_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "version_number",
            name="uq_job_criteria_version_number",
        ),
    )
    op.create_index(
        op.f("ix_job_criteria_versions_job_id"),
        "job_criteria_versions",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_job_criteria_versions_status"),
        "job_criteria_versions",
        ["status"],
        unique=False,
    )

    op.create_table(
        "hard_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("criteria_version_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("expected_value", sa.String(length=200), nullable=False),
        sa.Column("auto_reject", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "requirement_type IN ('min_experience_years', 'min_education', "
            "'required_certification', 'language_level', 'other')",
            name="ck_hard_requirement_type",
        ),
        sa.CheckConstraint(
            "NOT auto_reject OR requirement_type IN ('min_experience_years', "
            "'min_education', 'required_certification', 'language_level')",
            name="ck_hard_requirement_auto_reject_type",
        ),
        sa.ForeignKeyConstraint(
            ["criteria_version_id"],
            ["job_criteria_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_hard_requirements_criteria_version_id"),
        "hard_requirements",
        ["criteria_version_id"],
        unique=False,
    )

    op.create_table(
        "scoring_dimensions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("criteria_version_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("weight_percent", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "weight_percent >= 0 AND weight_percent <= 100",
            name="ck_scoring_dimension_weight",
        ),
        sa.ForeignKeyConstraint(
            ["criteria_version_id"],
            ["job_criteria_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_scoring_dimensions_criteria_version_id"),
        "scoring_dimensions",
        ["criteria_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_scoring_dimensions_criteria_version_id"),
        table_name="scoring_dimensions",
    )
    op.drop_table("scoring_dimensions")
    op.drop_index(
        op.f("ix_hard_requirements_criteria_version_id"),
        table_name="hard_requirements",
    )
    op.drop_table("hard_requirements")
    op.drop_index(op.f("ix_job_criteria_versions_status"), table_name="job_criteria_versions")
    op.drop_index(op.f("ix_job_criteria_versions_job_id"), table_name="job_criteria_versions")
    op.drop_table("job_criteria_versions")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_owner_id"), table_name="jobs")
    op.drop_table("jobs")
