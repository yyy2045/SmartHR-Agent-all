"""Create recruitment knowledge RAG tables.

Revision ID: 20260805_0042
Revises: 20260804_0041
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260805_0042"
down_revision: str | None = "20260804_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "recruitment_knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("resource_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
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
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_rkb_status"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120", name="ck_rkb_name"),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 1000",
            name="ck_rkb_description",
        ),
        sa.CheckConstraint("resource_version >= 1", name="ck_rkb_resource_version"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_rkb_name"),
    )
    op.create_index("ix_rkb_status", "recruitment_knowledge_bases", ["status"])
    op.create_index(
        "ix_recruitment_knowledge_bases_created_by_id",
        "recruitment_knowledge_bases",
        ["created_by_id"],
    )

    op.create_table(
        "recruitment_knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column(
            "visibility_scope",
            sa.String(length=40),
            server_default="all_internal",
            nullable=False,
        ),
        sa.Column("related_job_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=True),
        sa.Column("resource_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
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
            "category IN ('policy', 'job_standard', 'interview', 'offer', "
            "'compensation', 'communication', 'general')",
            name="ck_rkd_category",
        ),
        sa.CheckConstraint(
            "visibility_scope IN ('all_internal', 'recruiter_manager', "
            "'recruiter_only', 'admin_only')",
            name="ck_rkd_visibility_scope",
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_rkd_status"),
        sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 200", name="ck_rkd_title"),
        sa.CheckConstraint("summary IS NULL OR length(summary) <= 1000", name="ck_rkd_summary"),
        sa.CheckConstraint(
            "current_version_number IS NULL OR current_version_number >= 1",
            name="ck_rkd_current_version",
        ),
        sa.CheckConstraint("resource_version >= 1", name="ck_rkd_resource_version"),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["recruitment_knowledge_bases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["related_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_base_id", "title", name="uq_rkd_title"),
    )
    op.create_index(
        "ix_rkd_base_category",
        "recruitment_knowledge_documents",
        ["knowledge_base_id", "category"],
    )
    op.create_index(
        "ix_rkd_scope_status",
        "recruitment_knowledge_documents",
        ["visibility_scope", "status"],
    )
    for column in ("category", "created_by_id", "knowledge_base_id", "related_job_id", "status"):
        op.create_index(
            op.f(f"ix_recruitment_knowledge_documents_{column}"),
            "recruitment_knowledge_documents",
            [column],
        )

    op.create_table(
        "recruitment_knowledge_document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("change_note", sa.String(length=500), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("parser_name", sa.String(length=120), nullable=True),
        sa.Column("parser_version", sa.String(length=80), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column("published_by_id", sa.Uuid(), nullable=True),
        sa.Column("published_by_username", sa.String(length=64), nullable=True),
        sa.Column("published_by_display_name", sa.String(length=100), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_rkdv_number"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_rkdv_status",
        ),
        sa.CheckConstraint("source_type IN ('manual', 'upload')", name="ck_rkdv_source_type"),
        sa.CheckConstraint(
            "length(trim(change_note)) BETWEEN 1 AND 500",
            name="ck_rkdv_change_note",
        ),
        sa.CheckConstraint(
            "length(trim(raw_text)) BETWEEN 1 AND 200000",
            name="ck_rkdv_raw_text",
        ),
        sa.CheckConstraint(
            "parser_name IS NULL OR length(parser_name) <= 120",
            name="ck_rkdv_parser_name",
        ),
        sa.CheckConstraint("chunk_count >= 0", name="ck_rkdv_chunk_count"),
        sa.CheckConstraint(
            "published_at IS NULL OR status IN ('published', 'retired')",
            name="ck_rkdv_published_at",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["recruitment_knowledge_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_rkdv_number"),
        sa.UniqueConstraint("document_id", "idempotency_key", name="uq_rkdv_idempotency"),
    )
    op.create_index(
        "ix_rkdv_document_status",
        "recruitment_knowledge_document_versions",
        ["document_id", "status"],
    )
    for column in ("content_hash", "created_by_id", "document_id", "published_by_id", "status"):
        op.create_index(
            op.f(f"ix_recruitment_knowledge_document_versions_{column}"),
            "recruitment_knowledge_document_versions",
            [column],
        )

    op.create_table(
        "recruitment_knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("heading_path", sa.JSON(), nullable=False),
        sa.Column("source_locator", sa.String(length=200), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding_version", sa.String(length=50), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("task_id", sa.String(length=120), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
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
        sa.CheckConstraint("chunk_index >= 0", name="ck_rkc_index"),
        sa.CheckConstraint("length(trim(chunk_text)) BETWEEN 1 AND 8000", name="ck_rkc_text"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_rkc_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_rkc_attempt_count"),
        sa.CheckConstraint("embedding_dimension > 0", name="ck_rkc_dimension"),
        sa.CheckConstraint(
            "embedding IS NULL OR vector_dims(embedding) = embedding_dimension",
            name="ck_rkc_vector_dimension",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["recruitment_knowledge_bases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["recruitment_knowledge_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["recruitment_knowledge_document_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            "embedding_model",
            "embedding_version",
            name="uq_rkc_version_index",
        ),
    )
    op.create_index(
        "ix_rkc_document_status",
        "recruitment_knowledge_chunks",
        ["document_id", "status"],
    )
    op.create_index(
        "ix_rkc_model_status",
        "recruitment_knowledge_chunks",
        ["embedding_model", "embedding_version", "status"],
    )
    for column in (
        "content_hash",
        "document_id",
        "document_version_id",
        "knowledge_base_id",
        "status",
        "task_id",
    ):
        op.create_index(
            op.f(f"ix_recruitment_knowledge_chunks_{column}"),
            "recruitment_knowledge_chunks",
            [column],
        )

    op.create_table(
        "recruitment_knowledge_retrieval_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("query_summary", sa.Text(), nullable=True),
        sa.Column("invoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_template_version_id", sa.Uuid(), nullable=True),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding_version", sa.String(length=50), nullable=False),
        sa.Column("limit_count", sa.Integer(), nullable=False),
        sa.Column("returned_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("filtered_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retrieved_chunk_ids", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(scenario)) BETWEEN 1 AND 80",
            name="ck_rkrl_scenario",
        ),
        sa.CheckConstraint(
            "query_summary IS NULL OR length(query_summary) <= 1000",
            name="ck_rkrl_query_summary",
        ),
        sa.CheckConstraint("limit_count >= 1 AND limit_count <= 20", name="ck_rkrl_limit"),
        sa.CheckConstraint(
            "returned_count >= 0 AND filtered_count >= 0",
            name="ck_rkrl_counts",
        ),
        sa.ForeignKeyConstraint(["invoked_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["prompt_template_version_id"],
            ["prompt_template_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_rkrl_scenario_created",
        "recruitment_knowledge_retrieval_logs",
        ["scenario", "created_at"],
    )
    op.create_index(
        "ix_rkrl_resource",
        "recruitment_knowledge_retrieval_logs",
        ["resource_type", "resource_id"],
    )
    for column in (
        "application_id",
        "created_at",
        "invoked_by_id",
        "job_id",
        "prompt_template_version_id",
        "query_hash",
        "resource_id",
        "scenario",
    ):
        op.create_index(
            op.f(f"ix_recruitment_knowledge_retrieval_logs_{column}"),
            "recruitment_knowledge_retrieval_logs",
            [column],
        )


def downgrade() -> None:
    for column in (
        "scenario",
        "resource_id",
        "query_hash",
        "prompt_template_version_id",
        "job_id",
        "invoked_by_id",
        "created_at",
        "application_id",
    ):
        op.drop_index(
            op.f(f"ix_recruitment_knowledge_retrieval_logs_{column}"),
            table_name="recruitment_knowledge_retrieval_logs",
        )
    op.drop_index("ix_rkrl_resource", table_name="recruitment_knowledge_retrieval_logs")
    op.drop_index("ix_rkrl_scenario_created", table_name="recruitment_knowledge_retrieval_logs")
    op.drop_table("recruitment_knowledge_retrieval_logs")

    for column in (
        "task_id",
        "status",
        "knowledge_base_id",
        "document_version_id",
        "document_id",
        "content_hash",
    ):
        op.drop_index(
            op.f(f"ix_recruitment_knowledge_chunks_{column}"),
            table_name="recruitment_knowledge_chunks",
        )
    op.drop_index("ix_rkc_model_status", table_name="recruitment_knowledge_chunks")
    op.drop_index("ix_rkc_document_status", table_name="recruitment_knowledge_chunks")
    op.drop_table("recruitment_knowledge_chunks")

    for column in ("status", "published_by_id", "document_id", "created_by_id", "content_hash"):
        op.drop_index(
            op.f(f"ix_recruitment_knowledge_document_versions_{column}"),
            table_name="recruitment_knowledge_document_versions",
        )
    op.drop_index(
        "ix_rkdv_document_status",
        table_name="recruitment_knowledge_document_versions",
    )
    op.drop_table("recruitment_knowledge_document_versions")

    for column in ("status", "related_job_id", "knowledge_base_id", "created_by_id", "category"):
        op.drop_index(
            op.f(f"ix_recruitment_knowledge_documents_{column}"),
            table_name="recruitment_knowledge_documents",
        )
    op.drop_index("ix_rkd_scope_status", table_name="recruitment_knowledge_documents")
    op.drop_index("ix_rkd_base_category", table_name="recruitment_knowledge_documents")
    op.drop_table("recruitment_knowledge_documents")

    op.drop_index(
        "ix_recruitment_knowledge_bases_created_by_id",
        table_name="recruitment_knowledge_bases",
    )
    op.drop_index("ix_rkb_status", table_name="recruitment_knowledge_bases")
    op.drop_table("recruitment_knowledge_bases")
