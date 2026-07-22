"""创建筛选批次与简历文件表

Revision ID: 20260722_0003
Revises: 20260722_0002
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0003"
down_revision: str | None = "20260722_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "screening_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("criteria_version_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
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
            "status IN ('uploading', 'ready', 'partial_failure', 'failed', "
            "'processing', 'completed')",
            name="ck_screening_batches_status",
        ),
        sa.ForeignKeyConstraint(
            ["criteria_version_id"],
            ["job_criteria_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_screening_batches_criteria_version_id"),
        "screening_batches",
        ["criteria_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_screening_batches_job_id"),
        "screening_batches",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_screening_batches_status"),
        "screening_batches",
        ["status"],
        unique=False,
    )

    op.create_table(
        "resume_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_extension", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=150), nullable=False),
        sa.Column("detected_type", sa.String(length=20), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("failure_code", sa.String(length=50), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
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
        sa.CheckConstraint("attempt_count >= 1", name="ck_resume_documents_attempt_count"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_resume_documents_size"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'queued', 'processing', 'completed', 'failed')",
            name="ck_resume_documents_status",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["screening_batches.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_resume_documents_batch_id"),
        "resume_documents",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_documents_sha256"),
        "resume_documents",
        ["sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_resume_documents_status"),
        "resume_documents",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_resume_documents_status"), table_name="resume_documents")
    op.drop_index(op.f("ix_resume_documents_sha256"), table_name="resume_documents")
    op.drop_index(op.f("ix_resume_documents_batch_id"), table_name="resume_documents")
    op.drop_table("resume_documents")
    op.drop_index(op.f("ix_screening_batches_status"), table_name="screening_batches")
    op.drop_index(op.f("ix_screening_batches_job_id"), table_name="screening_batches")
    op.drop_index(
        op.f("ix_screening_batches_criteria_version_id"),
        table_name="screening_batches",
    )
    op.drop_table("screening_batches")
