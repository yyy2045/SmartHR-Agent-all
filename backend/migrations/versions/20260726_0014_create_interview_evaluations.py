"""创建结构化面试评价

Revision ID: 20260726_0014
Revises: 20260726_0013
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0014"
down_revision: str | None = "20260726_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_round_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("overall_recommendation", sa.String(length=30), nullable=True),
        sa.Column("overall_comment", sa.Text(), nullable=False),
        sa.Column("total_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("submitted_by_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
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
            "overall_recommendation IS NULL OR overall_recommendation IN "
            "('strongly_recommend', 'recommend', 'reserve', 'not_recommend')",
            name="ck_interview_evaluations_recommendation",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted')",
            name="ck_interview_evaluations_status",
        ),
        sa.CheckConstraint(
            "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
            name="ck_interview_evaluations_total_score",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_round_id"], ["candidate_interview_rounds.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_round_id", name="uq_interview_evaluation_round"),
    )
    op.create_index(
        op.f("ix_interview_evaluations_candidate_round_id"),
        "interview_evaluations",
        ["candidate_round_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interview_evaluations_status"),
        "interview_evaluations",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interview_evaluations_submitted_by_id"),
        "interview_evaluations",
        ["submitted_by_id"],
        unique=False,
    )

    op.create_table(
        "interview_question_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("answer_summary", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["interview_evaluations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["interview_questions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id", "question_id", name="uq_interview_question_response"
        ),
    )
    op.create_index(
        op.f("ix_interview_question_responses_evaluation_id"),
        "interview_question_responses",
        ["evaluation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interview_question_responses_question_id"),
        "interview_question_responses",
        ["question_id"],
        unique=False,
    )

    op.create_table(
        "interview_dimension_ratings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("dimension_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 1 AND score <= 5)",
            name="ck_interview_dimension_ratings_score",
        ),
        sa.ForeignKeyConstraint(
            ["dimension_id"], ["interview_score_dimensions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["interview_evaluations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_id", "dimension_id", name="uq_interview_dimension_rating"
        ),
    )
    op.create_index(
        op.f("ix_interview_dimension_ratings_dimension_id"),
        "interview_dimension_ratings",
        ["dimension_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interview_dimension_ratings_evaluation_id"),
        "interview_dimension_ratings",
        ["evaluation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_interview_dimension_ratings_evaluation_id"),
        table_name="interview_dimension_ratings",
    )
    op.drop_index(
        op.f("ix_interview_dimension_ratings_dimension_id"),
        table_name="interview_dimension_ratings",
    )
    op.drop_table("interview_dimension_ratings")
    op.drop_index(
        op.f("ix_interview_question_responses_question_id"),
        table_name="interview_question_responses",
    )
    op.drop_index(
        op.f("ix_interview_question_responses_evaluation_id"),
        table_name="interview_question_responses",
    )
    op.drop_table("interview_question_responses")
    op.drop_index(
        op.f("ix_interview_evaluations_submitted_by_id"),
        table_name="interview_evaluations",
    )
    op.drop_index(
        op.f("ix_interview_evaluations_status"),
        table_name="interview_evaluations",
    )
    op.drop_index(
        op.f("ix_interview_evaluations_candidate_round_id"),
        table_name="interview_evaluations",
    )
    op.drop_table("interview_evaluations")
