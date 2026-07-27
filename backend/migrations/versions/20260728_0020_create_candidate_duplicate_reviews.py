"""创建候选人重复识别提示

Revision ID: 20260728_0020
Revises: 20260728_0019
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0020"
down_revision: str | None = "20260728_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates", sa.Column("full_name_normalized", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "candidates", sa.Column("phone_normalized", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "candidates", sa.Column("email_normalized", sa.String(length=320), nullable=True)
    )
    op.add_column(
        "candidates", sa.Column("experience_fingerprint", sa.String(length=32), nullable=True)
    )
    op.create_index("ix_candidates_full_name_normalized", "candidates", ["full_name_normalized"])
    op.create_index("ix_candidates_phone_normalized", "candidates", ["phone_normalized"])
    op.create_index("ix_candidates_email_normalized", "candidates", ["email_normalized"])
    op.create_index(
        "ix_candidates_experience_fingerprint", "candidates", ["experience_fingerprint"]
    )
    op.execute(
        sa.text(
            """
            UPDATE candidates
            SET
                full_name_normalized = NULLIF(
                    translate(
                        regexp_replace(lower(trim(full_name)), '[[:space:]]', '', 'g'),
                        '·•._,，。:：;；-()（）',
                        ''
                    ),
                    ''
                ),
                phone_normalized = NULLIF(
                    regexp_replace(phone, '[^0-9]', '', 'g'),
                    ''
                ),
                email_normalized = NULLIF(lower(trim(email)), '')
            """
        )
    )

    op.create_table(
        "candidate_duplicate_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_a_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_b_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="pending", nullable=False),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "candidate_a_id <> candidate_b_id",
            name="ck_candidate_duplicate_reviews_distinct_candidates",
        ),
        sa.CheckConstraint(
            "confidence IN ('strong', 'weak')",
            name="ck_candidate_duplicate_reviews_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'not_duplicate', 'merged')",
            name="ck_candidate_duplicate_reviews_status",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_a_id"], ["candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_b_id"], ["candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["resume_documents.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_candidate_duplicate_reviews_pair",
        "candidate_duplicate_reviews",
        ["candidate_a_id", "candidate_b_id"],
        unique=True,
    )
    op.create_index(
        "ix_candidate_duplicate_reviews_candidate_a_id",
        "candidate_duplicate_reviews",
        ["candidate_a_id"],
    )
    op.create_index(
        "ix_candidate_duplicate_reviews_candidate_b_id",
        "candidate_duplicate_reviews",
        ["candidate_b_id"],
    )
    op.create_index(
        "ix_candidate_duplicate_reviews_source_document_id",
        "candidate_duplicate_reviews",
        ["source_document_id"],
    )
    op.create_index(
        "ix_candidate_duplicate_reviews_confidence",
        "candidate_duplicate_reviews",
        ["confidence"],
    )
    op.create_index(
        "ix_candidate_duplicate_reviews_status",
        "candidate_duplicate_reviews",
        ["status"],
    )
    op.create_index(
        "ix_candidate_duplicate_reviews_resolved_by_id",
        "candidate_duplicate_reviews",
        ["resolved_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_duplicate_reviews_resolved_by_id",
        table_name="candidate_duplicate_reviews",
    )
    op.drop_index(
        "ix_candidate_duplicate_reviews_status", table_name="candidate_duplicate_reviews"
    )
    op.drop_index(
        "ix_candidate_duplicate_reviews_confidence",
        table_name="candidate_duplicate_reviews",
    )
    op.drop_index(
        "ix_candidate_duplicate_reviews_source_document_id",
        table_name="candidate_duplicate_reviews",
    )
    op.drop_index(
        "ix_candidate_duplicate_reviews_candidate_b_id",
        table_name="candidate_duplicate_reviews",
    )
    op.drop_index(
        "ix_candidate_duplicate_reviews_candidate_a_id",
        table_name="candidate_duplicate_reviews",
    )
    op.drop_index(
        "uq_candidate_duplicate_reviews_pair", table_name="candidate_duplicate_reviews"
    )
    op.drop_table("candidate_duplicate_reviews")
    op.drop_index("ix_candidates_experience_fingerprint", table_name="candidates")
    op.drop_index("ix_candidates_email_normalized", table_name="candidates")
    op.drop_index("ix_candidates_phone_normalized", table_name="candidates")
    op.drop_index("ix_candidates_full_name_normalized", table_name="candidates")
    op.drop_column("candidates", "experience_fingerprint")
    op.drop_column("candidates", "email_normalized")
    op.drop_column("candidates", "phone_normalized")
    op.drop_column("candidates", "full_name_normalized")
