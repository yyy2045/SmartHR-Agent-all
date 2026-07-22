"""增加简历脱敏文本与命中映射

Revision ID: 20260723_0005
Revises: 20260722_0004
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260723_0005"
down_revision: str | None = "20260722_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resume_documents",
        sa.Column("redaction_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "resume_documents",
        sa.Column("redacted_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "resume_text_segments",
        sa.Column("redacted_text", sa.Text()),
    )
    op.execute(
        "UPDATE resume_text_segments "
        "SET redacted_text = normalized_text "
        "WHERE redacted_text IS NULL"
    )

    op.create_table(
        "resume_redactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("segment_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("replacement_text", sa.String(100), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('name', 'phone', 'email', 'id_number', 'address', "
            "'social_account')",
            name="ck_resume_redactions_entity_type",
        ),
        sa.CheckConstraint(
            "end_offset > start_offset",
            name="ck_resume_redactions_end_offset",
        ),
        sa.CheckConstraint(
            "start_offset >= 0",
            name="ck_resume_redactions_start_offset",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["resume_text_segments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "segment_id",
            "start_offset",
            "end_offset",
            "entity_type",
            name="uq_resume_redaction_span",
        ),
    )
    op.create_index(
        op.f("ix_resume_redactions_segment_id"),
        "resume_redactions",
        ["segment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_resume_redactions_segment_id"), table_name="resume_redactions")
    op.drop_table("resume_redactions")
    op.drop_column("resume_text_segments", "redacted_text")
    op.drop_column("resume_documents", "redacted_at")
    op.drop_column("resume_documents", "redaction_count")
