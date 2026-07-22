"""创建简历文本片段并扩展解析状态

Revision ID: 20260722_0004
Revises: 20260722_0003
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0004"
down_revision: str | None = "20260722_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("resume_documents", sa.Column("extraction_method", sa.String(30)))
    op.add_column(
        "resume_documents",
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "resume_documents",
        sa.Column("text_character_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "resume_documents",
        sa.Column("processing_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("resume_documents", sa.Column("task_id", sa.String(100)))
    op.add_column(
        "resume_documents",
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
    )
    op.add_column("resume_documents", sa.Column("parsed_at", sa.DateTime(timezone=True)))
    op.create_index(
        op.f("ix_resume_documents_task_id"),
        "resume_documents",
        ["task_id"],
        unique=False,
    )

    op.create_table(
        "resume_text_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("segment_key", sa.String(20), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("paragraph_index", sa.Integer()),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("ocr_confidence", sa.Float()),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)",
            name="ck_resume_text_segments_ocr_confidence",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_resume_text_segments_sort_order",
        ),
        sa.CheckConstraint(
            "source_type IN ('pdf_page', 'docx_paragraph', 'image_ocr')",
            name="ck_resume_text_segments_source_type",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["resume_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "segment_key", name="uq_resume_segment_key"),
        sa.UniqueConstraint(
            "document_id",
            "sort_order",
            name="uq_resume_segment_sort_order",
        ),
    )
    op.create_index(
        op.f("ix_resume_text_segments_document_id"),
        "resume_text_segments",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_resume_text_segments_document_id"),
        table_name="resume_text_segments",
    )
    op.drop_table("resume_text_segments")
    op.drop_index(op.f("ix_resume_documents_task_id"), table_name="resume_documents")
    op.drop_column("resume_documents", "parsed_at")
    op.drop_column("resume_documents", "processing_started_at")
    op.drop_column("resume_documents", "task_id")
    op.drop_column("resume_documents", "processing_attempt_count")
    op.drop_column("resume_documents", "text_character_count")
    op.drop_column("resume_documents", "segment_count")
    op.drop_column("resume_documents", "extraction_method")
