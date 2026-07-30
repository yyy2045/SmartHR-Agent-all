"""Lock candidate resume inputs when recommendation runs are created.

Revision ID: 20260730_0034
Revises: 20260730_0033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0034"
down_revision: str | None = "20260730_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "talent_recommendation_run_candidates",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_code_snapshot", sa.String(length=40), nullable=False),
        sa.Column("candidate_name_snapshot", sa.String(length=200), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_sha256_snapshot", sa.String(length=64), nullable=False),
        sa.Column("document_updated_at_snapshot", sa.DateTime(timezone=True), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("embedding_model_snapshot", sa.String(length=200), nullable=False),
        sa.Column("embedding_version_snapshot", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension_snapshot", sa.Integer(), nullable=False),
        sa.Column("matched_group_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(candidate_code_snapshot)) > 0",
            name="ck_talent_recommendation_run_candidates_code",
        ),
        sa.CheckConstraint(
            "length(document_sha256_snapshot) = 64",
            name="ck_talent_recommendation_run_candidates_sha256",
        ),
        sa.CheckConstraint(
            "profile_version_snapshot >= 1 AND embedding_dimension_snapshot >= 1",
            name="ck_talent_recommendation_run_candidates_versions",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id", "document_id", "profile_version_snapshot"],
            [
                "candidate_profiles.id",
                "candidate_profiles.document_id",
                "candidate_profiles.version_number",
            ],
            name="fk_talent_recommendation_run_candidates_profile_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["resume_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["talent_recommendation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "candidate_id"),
        sa.UniqueConstraint(
            "run_id",
            "document_id",
            name="uq_talent_recommendation_run_candidates_document",
        ),
    )
    op.create_index(
        op.f("ix_talent_recommendation_run_candidates_candidate_profile_id"),
        "talent_recommendation_run_candidates",
        ["candidate_profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_talent_recommendation_run_candidates_document_id"),
        "talent_recommendation_run_candidates",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_talent_recommendation_run_candidates_document_id"),
        table_name="talent_recommendation_run_candidates",
    )
    op.drop_index(
        op.f("ix_talent_recommendation_run_candidates_candidate_profile_id"),
        table_name="talent_recommendation_run_candidates",
    )
    op.drop_table("talent_recommendation_run_candidates")
