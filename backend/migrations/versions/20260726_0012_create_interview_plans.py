"""创建职位面试方案与结构化评分表

Revision ID: 20260726_0012
Revises: 20260726_0011
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0012"
down_revision: str | None = "20260726_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_plan_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
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
            "status IN ('draft', 'confirmed')",
            name="ck_interview_plan_versions_status",
        ),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["interview_plan_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "version_number",
            name="uq_interview_plan_version_number",
        ),
    )
    op.create_index(
        op.f("ix_interview_plan_versions_job_id"),
        "interview_plan_versions",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interview_plan_versions_status"),
        "interview_plan_versions",
        ["status"],
        unique=False,
    )

    op.create_table(
        "interview_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_version_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("round_type", sa.String(length=20), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("pass_threshold", sa.Integer(), nullable=False),
        sa.Column("focus", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "duration_minutes >= 15 AND duration_minutes <= 480",
            name="ck_interview_rounds_duration",
        ),
        sa.CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 100",
            name="ck_interview_rounds_pass_threshold",
        ),
        sa.CheckConstraint(
            "round_type IN ('phone', 'technical', 'business', 'hr', 'final', 'other')",
            name="ck_interview_rounds_type",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_interview_rounds_sort_order"),
        sa.ForeignKeyConstraint(
            ["plan_version_id"],
            ["interview_plan_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_version_id",
            "sort_order",
            name="uq_interview_round_sort_order",
        ),
    )
    op.create_index(
        op.f("ix_interview_rounds_plan_version_id"),
        "interview_rounds",
        ["plan_version_id"],
        unique=False,
    )

    op.create_table(
        "interview_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("evaluation_guide", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("sort_order >= 0", name="ck_interview_questions_sort_order"),
        sa.ForeignKeyConstraint(["round_id"], ["interview_rounds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "round_id",
            "sort_order",
            name="uq_interview_question_sort_order",
        ),
    )
    op.create_index(
        op.f("ix_interview_questions_round_id"),
        "interview_questions",
        ["round_id"],
        unique=False,
    )

    op.create_table(
        "interview_score_dimensions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("weight_percent", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "weight_percent >= 0 AND weight_percent <= 100",
            name="ck_interview_score_dimensions_weight",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_interview_score_dimensions_sort_order",
        ),
        sa.ForeignKeyConstraint(["round_id"], ["interview_rounds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "round_id",
            "sort_order",
            name="uq_interview_score_dimension_sort_order",
        ),
    )
    op.create_index(
        op.f("ix_interview_score_dimensions_round_id"),
        "interview_score_dimensions",
        ["round_id"],
        unique=False,
    )

    op.create_table(
        "interview_score_anchors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dimension_id", sa.Uuid(), nullable=False),
        sa.Column("score_value", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "score_value >= 1 AND score_value <= 5",
            name="ck_interview_score_anchors_value",
        ),
        sa.ForeignKeyConstraint(
            ["dimension_id"],
            ["interview_score_dimensions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dimension_id",
            "score_value",
            name="uq_interview_score_anchor_value",
        ),
    )
    op.create_index(
        op.f("ix_interview_score_anchors_dimension_id"),
        "interview_score_anchors",
        ["dimension_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_interview_score_anchors_dimension_id"),
        table_name="interview_score_anchors",
    )
    op.drop_table("interview_score_anchors")
    op.drop_index(
        op.f("ix_interview_score_dimensions_round_id"),
        table_name="interview_score_dimensions",
    )
    op.drop_table("interview_score_dimensions")
    op.drop_index(
        op.f("ix_interview_questions_round_id"),
        table_name="interview_questions",
    )
    op.drop_table("interview_questions")
    op.drop_index(
        op.f("ix_interview_rounds_plan_version_id"),
        table_name="interview_rounds",
    )
    op.drop_table("interview_rounds")
    op.drop_index(
        op.f("ix_interview_plan_versions_status"),
        table_name="interview_plan_versions",
    )
    op.drop_index(
        op.f("ix_interview_plan_versions_job_id"),
        table_name="interview_plan_versions",
    )
    op.drop_table("interview_plan_versions")
