"""Collapse recruitment knowledge to a single default base.

Revision ID: 20260909_0046
Revises: 20260817_0045
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0046"
down_revision: str | None = "20260817_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHUNKS_FK = "recruitment_knowledge_chunks_knowledge_base_id_fkey"
_DOCUMENTS_FK = "recruitment_knowledge_documents_knowledge_base_id_fkey"


def upgrade() -> None:
    op.drop_constraint(_DOCUMENTS_FK, "recruitment_knowledge_documents", type_="foreignkey")
    op.drop_constraint(_CHUNKS_FK, "recruitment_knowledge_chunks", type_="foreignkey")

    op.drop_index(
        "ix_recruitment_knowledge_documents_knowledge_base_id",
        table_name="recruitment_knowledge_documents",
    )
    op.drop_index("ix_rkd_base_category", table_name="recruitment_knowledge_documents")
    op.drop_index(
        "ix_recruitment_knowledge_chunks_knowledge_base_id",
        table_name="recruitment_knowledge_chunks",
    )

    op.drop_constraint("uq_rkd_title", "recruitment_knowledge_documents", type_="unique")
    op.create_unique_constraint("uq_rkd_title", "recruitment_knowledge_documents", ["title"])

    op.drop_column("recruitment_knowledge_documents", "knowledge_base_id")
    op.drop_column("recruitment_knowledge_chunks", "knowledge_base_id")

    op.drop_index("ix_rkb_status", table_name="recruitment_knowledge_bases")
    op.drop_index(
        "ix_recruitment_knowledge_bases_created_by_id",
        table_name="recruitment_knowledge_bases",
    )
    op.drop_table("recruitment_knowledge_bases")


def downgrade() -> None:
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

    op.add_column(
        "recruitment_knowledge_documents",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "recruitment_knowledge_chunks",
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=True),
    )

    op.create_index(
        "ix_recruitment_knowledge_documents_knowledge_base_id",
        "recruitment_knowledge_documents",
        ["knowledge_base_id"],
    )
    op.create_index(
        "ix_recruitment_knowledge_chunks_knowledge_base_id",
        "recruitment_knowledge_chunks",
        ["knowledge_base_id"],
    )
    op.create_index(
        "ix_rkd_base_category",
        "recruitment_knowledge_documents",
        ["knowledge_base_id", "category"],
    )

    op.drop_constraint("uq_rkd_title", "recruitment_knowledge_documents", type_="unique")
    op.create_unique_constraint(
        "uq_rkd_title",
        "recruitment_knowledge_documents",
        ["knowledge_base_id", "title"],
    )

    op.create_foreign_key(
        _DOCUMENTS_FK,
        "recruitment_knowledge_documents",
        "recruitment_knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        _CHUNKS_FK,
        "recruitment_knowledge_chunks",
        "recruitment_knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="RESTRICT",
    )
