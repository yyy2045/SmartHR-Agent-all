"""创建候选人档案与 AI 筛选结果

Revision ID: 20260723_0006
Revises: 20260723_0005
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0006"
down_revision: str | None = "20260723_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_profile_id", sa.Uuid()),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("education", sa.JSON(), nullable=False),
        sa.Column("work_experiences", sa.JSON(), nullable=False),
        sa.Column("projects", sa.JSON(), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("certifications", sa.JSON(), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('ai', 'manual')", name="ck_candidate_profiles_source"),
        sa.CheckConstraint("version_number >= 1", name="ck_candidate_profiles_version"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["resume_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_profile_id"], ["candidate_profiles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_candidate_profile_document_version",
        ),
    )
    op.create_index(
        op.f("ix_candidate_profiles_document_id"),
        "candidate_profiles",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "screening_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid()),
        sa.Column("criteria_version_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("ai_group", sa.String(30)),
        sa.Column("total_score", sa.Numeric(5, 2)),
        sa.Column("pass_threshold", sa.Integer(), nullable=False),
        sa.Column("hard_requirement_results", sa.JSON(), nullable=False),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("missing_items", sa.JSON(), nullable=False),
        sa.Column("interview_questions", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("failure_code", sa.String(50)),
        sa.Column("failure_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("analysis_version >= 1", name="ck_screening_results_version"),
        sa.CheckConstraint(
            "ai_group IS NULL OR ai_group IN ('passed', 'low_match', 'auto_rejected')",
            name="ck_screening_results_ai_group",
        ),
        sa.CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 100",
            name="ck_screening_results_pass_threshold",
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_screening_results_status",
        ),
        sa.CheckConstraint(
            "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
            name="ck_screening_results_total_score",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["criteria_version_id"], ["job_criteria_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["resume_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "criteria_version_id",
            "analysis_version",
            name="uq_screening_result_analysis_version",
        ),
    )
    for column in (
        "ai_group",
        "candidate_profile_id",
        "criteria_version_id",
        "document_id",
        "status",
    ):
        op.create_index(
            op.f(f"ix_screening_results_{column}"),
            "screening_results",
            [column],
            unique=False,
        )

    op.create_table(
        "dimension_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("screening_result_id", sa.Uuid(), nullable=False),
        sa.Column("scoring_dimension_id", sa.Uuid()),
        sa.Column("dimension_name", sa.String(100), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("weight_percent", sa.Integer(), nullable=False),
        sa.Column("weighted_score", sa.Numeric(7, 2), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("missing_items", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name="ck_dimension_scores_score"
        ),
        sa.CheckConstraint(
            "sort_order >= 0", name="ck_dimension_scores_sort_order"
        ),
        sa.CheckConstraint(
            "weight_percent >= 0 AND weight_percent <= 100",
            name="ck_dimension_scores_weight",
        ),
        sa.CheckConstraint(
            "weighted_score >= 0 AND weighted_score <= 100",
            name="ck_dimension_scores_weighted_score",
        ),
        sa.ForeignKeyConstraint(
            ["scoring_dimension_id"], ["scoring_dimensions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["screening_result_id"], ["screening_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "screening_result_id",
            "sort_order",
            name="uq_dimension_score_result_sort_order",
        ),
    )
    op.create_index(
        op.f("ix_dimension_scores_scoring_dimension_id"),
        "dimension_scores",
        ["scoring_dimension_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dimension_scores_screening_result_id"),
        "dimension_scores",
        ["screening_result_id"],
        unique=False,
    )

    op.create_table(
        "evidence_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("screening_result_id", sa.Uuid(), nullable=False),
        sa.Column("dimension_score_id", sa.Uuid()),
        sa.Column("segment_id", sa.Uuid()),
        sa.Column("subject_type", sa.String(30), nullable=False),
        sa.Column("subject_key", sa.String(100), nullable=False),
        sa.Column("segment_key", sa.String(20), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("paragraph_index", sa.Integer()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "sort_order >= 0", name="ck_evidence_citations_sort_order"
        ),
        sa.CheckConstraint(
            "subject_type IN ('profile', 'hard_requirement', 'dimension')",
            name="ck_evidence_citations_subject_type",
        ),
        sa.ForeignKeyConstraint(
            ["dimension_score_id"], ["dimension_scores.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["screening_result_id"], ["screening_results.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"], ["resume_text_segments.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("dimension_score_id", "screening_result_id", "segment_id"):
        op.create_index(
            op.f(f"ix_evidence_citations_{column}"),
            "evidence_citations",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("segment_id", "screening_result_id", "dimension_score_id"):
        op.drop_index(
            op.f(f"ix_evidence_citations_{column}"),
            table_name="evidence_citations",
        )
    op.drop_table("evidence_citations")
    op.drop_index(
        op.f("ix_dimension_scores_screening_result_id"),
        table_name="dimension_scores",
    )
    op.drop_index(
        op.f("ix_dimension_scores_scoring_dimension_id"),
        table_name="dimension_scores",
    )
    op.drop_table("dimension_scores")
    for column in (
        "status",
        "document_id",
        "criteria_version_id",
        "candidate_profile_id",
        "ai_group",
    ):
        op.drop_index(
            op.f(f"ix_screening_results_{column}"),
            table_name="screening_results",
        )
    op.drop_table("screening_results")
    op.drop_index(
        op.f("ix_candidate_profiles_document_id"),
        table_name="candidate_profiles",
    )
    op.drop_table("candidate_profiles")
