"""Create Prompt template versioning tables.

Revision ID: 20260804_0041
Revises: 20260804_0040
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0041"
down_revision: str | None = "20260804_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=True),
        sa.Column("resource_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "scenario IN ('jd_generation', 'resume_analysis', 'resume_analysis_repair', "
            "'interview_report', 'offer_copy', 'candidate_comparison', 'candidate_qa')",
            name="ck_prompt_templates_scenario",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_prompt_templates_status",
        ),
        sa.CheckConstraint(
            "length(trim(name)) BETWEEN 1 AND 120",
            name="ck_prompt_templates_name",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 1000",
            name="ck_prompt_templates_description",
        ),
        sa.CheckConstraint(
            "current_version_number IS NULL OR current_version_number >= 1",
            name="ck_prompt_templates_current_version",
        ),
        sa.CheckConstraint(
            "resource_version >= 1",
            name="ck_prompt_templates_resource_version",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scenario", name="uq_prompt_templates_scenario"),
    )
    op.create_index("ix_prompt_templates_scenario", "prompt_templates", ["scenario"])
    op.create_index("ix_prompt_templates_status", "prompt_templates", ["status"])
    op.create_index("ix_prompt_templates_created_by_id", "prompt_templates", ["created_by_id"])

    op.create_table(
        "prompt_template_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("change_note", sa.String(length=500), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt_template", sa.Text(), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=True),
        sa.Column("model_parameters", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column("published_by_id", sa.Uuid(), nullable=True),
        sa.Column("published_by_username", sa.String(length=64), nullable=True),
        sa.Column("published_by_display_name", sa.String(length=100), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_prompt_template_versions_number",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')",
            name="ck_prompt_template_versions_status",
        ),
        sa.CheckConstraint(
            "length(trim(change_note)) BETWEEN 1 AND 500",
            name="ck_prompt_template_versions_change_note",
        ),
        sa.CheckConstraint(
            "length(trim(system_prompt)) BETWEEN 1 AND 20000",
            name="ck_prompt_template_versions_system_prompt",
        ),
        sa.CheckConstraint(
            "length(trim(user_prompt_template)) BETWEEN 1 AND 20000",
            name="ck_prompt_template_versions_user_prompt",
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR status IN ('published', 'retired')",
            name="ck_prompt_template_versions_published_at",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["prompt_template_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_prompt_template_versions_number",
        ),
        sa.UniqueConstraint(
            "template_id",
            "idempotency_key",
            name="uq_prompt_template_versions_idempotency",
        ),
    )
    op.create_index(
        "ix_prompt_template_versions_template_id",
        "prompt_template_versions",
        ["template_id"],
    )
    op.create_index("ix_prompt_template_versions_status", "prompt_template_versions", ["status"])
    op.create_index(
        "ix_prompt_template_versions_source_version_id",
        "prompt_template_versions",
        ["source_version_id"],
    )
    op.create_index(
        "ix_prompt_template_versions_created_by_id",
        "prompt_template_versions",
        ["created_by_id"],
    )
    op.create_index(
        "ix_prompt_template_versions_published_by_id",
        "prompt_template_versions",
        ["published_by_id"],
    )
    op.create_index(
        "ix_prompt_template_versions_template_status",
        "prompt_template_versions",
        ["template_id", "status"],
    )

    op.add_column(
        "ai_call_logs",
        sa.Column("prompt_template_version_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ai_call_logs_prompt_template_version_id",
        "ai_call_logs",
        "prompt_template_versions",
        ["prompt_template_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ai_call_logs_prompt_template_version_id",
        "ai_call_logs",
        ["prompt_template_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_call_logs_prompt_template_version_id", table_name="ai_call_logs")
    op.drop_constraint(
        "fk_ai_call_logs_prompt_template_version_id",
        "ai_call_logs",
        type_="foreignkey",
    )
    op.drop_column("ai_call_logs", "prompt_template_version_id")

    op.drop_index(
        "ix_prompt_template_versions_template_status",
        table_name="prompt_template_versions",
    )
    op.drop_index(
        "ix_prompt_template_versions_published_by_id",
        table_name="prompt_template_versions",
    )
    op.drop_index(
        "ix_prompt_template_versions_created_by_id",
        table_name="prompt_template_versions",
    )
    op.drop_index(
        "ix_prompt_template_versions_source_version_id",
        table_name="prompt_template_versions",
    )
    op.drop_index("ix_prompt_template_versions_status", table_name="prompt_template_versions")
    op.drop_index("ix_prompt_template_versions_template_id", table_name="prompt_template_versions")
    op.drop_table("prompt_template_versions")

    op.drop_index("ix_prompt_templates_created_by_id", table_name="prompt_templates")
    op.drop_index("ix_prompt_templates_status", table_name="prompt_templates")
    op.drop_index("ix_prompt_templates_scenario", table_name="prompt_templates")
    op.drop_table("prompt_templates")
