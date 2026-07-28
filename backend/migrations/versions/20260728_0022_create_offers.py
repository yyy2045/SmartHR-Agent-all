"""创建薪酬 Offer 与审批版本数据

Revision ID: 20260728_0022
Revises: 20260728_0021
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0022"
down_revision: str | None = "20260728_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "offers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="draft", nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "current_version_number >= 1",
            name="ck_offers_current_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_manager_confirmation', "
            "'pending_approval', 'approved', 'rejected')",
            name="ck_offers_status",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["job_applications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", name="uq_offers_application"),
    )
    op.create_index("ix_offers_application_id", "offers", ["application_id"])
    op.create_index("ix_offers_created_by_id", "offers", ["created_by_id"])
    op.create_index("ix_offers_status", "offers", ["status"])

    op.create_table(
        "offer_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("source_interview_report_version_id", sa.Uuid(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("monthly_salary", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("annual_salary_months", sa.Numeric(precision=4, scale=2), nullable=False),
        sa.Column("probation_months", sa.Integer(), nullable=False),
        sa.Column(
            "probation_monthly_salary", sa.Numeric(precision=12, scale=2), nullable=True
        ),
        sa.Column("bonus_description", sa.Text(), nullable=False),
        sa.Column("expected_start_date", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "annual_salary_months >= 1 AND annual_salary_months <= 36",
            name="ck_offer_versions_annual_salary_months",
        ),
        sa.CheckConstraint("currency = 'CNY'", name="ck_offer_versions_currency"),
        sa.CheckConstraint(
            "monthly_salary > 0", name="ck_offer_versions_monthly_salary"
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_offer_versions_number"),
        sa.CheckConstraint(
            "probation_months >= 0 AND probation_months <= 12",
            name="ck_offer_versions_probation_months",
        ),
        sa.CheckConstraint(
            "(probation_months = 0 AND probation_monthly_salary IS NULL) OR "
            "(probation_months > 0 AND probation_monthly_salary > 0)",
            name="ck_offer_versions_probation_salary",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_interview_report_version_id"],
            ["interview_report_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["offer_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "offer_id", "idempotency_key", name="uq_offer_version_idempotency"
        ),
        sa.UniqueConstraint(
            "offer_id", "version_number", name="uq_offer_version_number"
        ),
    )
    op.create_index("ix_offer_versions_created_by_id", "offer_versions", ["created_by_id"])
    op.create_index("ix_offer_versions_offer_id", "offer_versions", ["offer_id"])
    op.create_index(
        "ix_offer_versions_source_interview_report_version_id",
        "offer_versions",
        ["source_interview_report_version_id"],
    )
    op.create_index(
        "ix_offer_versions_source_version_id", "offer_versions", ["source_version_id"]
    )

    op.create_table(
        "offer_manager_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("confirmer_id", sa.Uuid(), nullable=True),
        sa.Column("confirmer_username", sa.String(length=64), nullable=False),
        sa.Column("confirmer_display_name", sa.String(length=100), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "decision IN ('confirmed', 'rejected')",
            name="ck_offer_manager_confirmations_decision",
        ),
        sa.ForeignKeyConstraint(["confirmer_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["offer_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "version_id", name="uq_offer_manager_confirmation_version"
        ),
    )
    op.create_index(
        "ix_offer_manager_confirmations_confirmer_id",
        "offer_manager_confirmations",
        ["confirmer_id"],
    )
    op.create_index(
        "ix_offer_manager_confirmations_version_id",
        "offer_manager_confirmations",
        ["version_id"],
    )

    op.create_table(
        "offer_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approver_username", sa.String(length=64), nullable=False),
        sa.Column("approver_display_name", sa.String(length=100), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_offer_approvals_decision",
        ),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["offer_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", name="uq_offer_approval_version"),
    )
    op.create_index("ix_offer_approvals_approver_id", "offer_approvals", ["approver_id"])
    op.create_index("ix_offer_approvals_version_id", "offer_approvals", ["version_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_approvals_version_id", table_name="offer_approvals")
    op.drop_index("ix_offer_approvals_approver_id", table_name="offer_approvals")
    op.drop_table("offer_approvals")
    op.drop_index(
        "ix_offer_manager_confirmations_version_id",
        table_name="offer_manager_confirmations",
    )
    op.drop_index(
        "ix_offer_manager_confirmations_confirmer_id",
        table_name="offer_manager_confirmations",
    )
    op.drop_table("offer_manager_confirmations")
    op.drop_index(
        "ix_offer_versions_source_version_id", table_name="offer_versions"
    )
    op.drop_index(
        "ix_offer_versions_source_interview_report_version_id",
        table_name="offer_versions",
    )
    op.drop_index("ix_offer_versions_offer_id", table_name="offer_versions")
    op.drop_index("ix_offer_versions_created_by_id", table_name="offer_versions")
    op.drop_table("offer_versions")
    op.drop_index("ix_offers_status", table_name="offers")
    op.drop_index("ix_offers_created_by_id", table_name="offers")
    op.drop_index("ix_offers_application_id", table_name="offers")
    op.drop_table("offers")
