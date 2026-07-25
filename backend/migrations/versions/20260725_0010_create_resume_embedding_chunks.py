"""创建简历向量知识库基础

Revision ID: 20260725_0010
Revises: 20260723_0009
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260725_0010"
down_revision: str | None = "20260723_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "resume_embedding_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(length=40), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("source_segment_keys", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding_version", sa.String(length=50), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=50), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
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
            "attempt_count >= 0",
            name="ck_resume_embedding_chunks_attempt_count",
        ),
        sa.CheckConstraint(
            "embedding_dimension > 0",
            name="ck_resume_embedding_chunks_dimension",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_resume_embedding_chunks_index",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_resume_embedding_chunks_status",
        ),
        sa.CheckConstraint(
            "embedding IS NULL OR vector_dims(embedding) = embedding_dimension",
            name="ck_resume_embedding_chunks_vector_dimension",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["resume_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_profile_id",
            "chunk_type",
            "chunk_index",
            "embedding_model",
            "embedding_version",
            name="uq_resume_embedding_chunk_version",
        ),
    )
    for column in (
        "candidate_profile_id",
        "content_hash",
        "document_id",
        "status",
        "task_id",
    ):
        op.create_index(
            op.f(f"ix_resume_embedding_chunks_{column}"),
            "resume_embedding_chunks",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "task_id",
        "status",
        "document_id",
        "content_hash",
        "candidate_profile_id",
    ):
        op.drop_index(
            op.f(f"ix_resume_embedding_chunks_{column}"),
            table_name="resume_embedding_chunks",
        )
    op.drop_table("resume_embedding_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
