"""创建面试报告与不可变版本

Revision ID: 20260728_0021
Revises: 20260728_0020
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0021"
down_revision: str | None = "20260728_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_by_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "current_version_number >= 1",
            name="ck_interview_reports_current_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed')",
            name="ck_interview_reports_status",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["job_applications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", name="uq_interview_reports_application"),
    )
    op.create_index(
        "ix_interview_reports_application_id", "interview_reports", ["application_id"]
    )
    op.create_index(
        "ix_interview_reports_confirmed_by_id", "interview_reports", ["confirmed_by_id"]
    )
    op.create_index(
        "ix_interview_reports_created_by_id", "interview_reports", ["created_by_id"]
    )
    op.create_index("ix_interview_reports_status", "interview_reports", ["status"])

    op.create_table(
        "interview_report_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("generation_mode", sa.String(length=20), nullable=False),
        sa.Column("conclusion", sa.String(length=20), nullable=True),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("concerns", sa.JSON(), nullable=False),
        sa.Column("follow_up_actions", sa.JSON(), nullable=False),
        sa.Column("screening_result_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("missing_rounds", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("ai_failure_code", sa.String(length=50), nullable=True),
        sa.Column("ai_failure_message", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "conclusion IS NULL OR conclusion IN ('hire', 'next_round', 'reserve', 'reject')",
            name="ck_interview_report_versions_conclusion",
        ),
        sa.CheckConstraint(
            "generation_mode IN ('ai', 'manual')",
            name="ck_interview_report_versions_generation_mode",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_interview_report_versions_number",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["report_id"], ["interview_reports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["screening_result_id"], ["screening_results.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["interview_report_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_id",
            "idempotency_key",
            name="uq_interview_report_version_idempotency",
        ),
        sa.UniqueConstraint(
            "report_id",
            "version_number",
            name="uq_interview_report_version_number",
        ),
    )
    op.create_index(
        "ix_interview_report_versions_created_by_id",
        "interview_report_versions",
        ["created_by_id"],
    )
    op.create_index(
        "ix_interview_report_versions_report_id",
        "interview_report_versions",
        ["report_id"],
    )
    op.create_index(
        "ix_interview_report_versions_screening_result_id",
        "interview_report_versions",
        ["screening_result_id"],
    )
    op.create_index(
        "ix_interview_report_versions_source_version_id",
        "interview_report_versions",
        ["source_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_report_versions_source_version_id",
        table_name="interview_report_versions",
    )
    op.drop_index(
        "ix_interview_report_versions_screening_result_id",
        table_name="interview_report_versions",
    )
    op.drop_index(
        "ix_interview_report_versions_report_id",
        table_name="interview_report_versions",
    )
    op.drop_index(
        "ix_interview_report_versions_created_by_id",
        table_name="interview_report_versions",
    )
    op.drop_table("interview_report_versions")
    op.drop_index("ix_interview_reports_status", table_name="interview_reports")
    op.drop_index("ix_interview_reports_created_by_id", table_name="interview_reports")
    op.drop_index("ix_interview_reports_confirmed_by_id", table_name="interview_reports")
    op.drop_index("ix_interview_reports_application_id", table_name="interview_reports")
    op.drop_table("interview_reports")
