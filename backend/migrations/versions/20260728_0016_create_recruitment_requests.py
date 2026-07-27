"""创建招聘需求与审批版本数据

Revision ID: 20260728_0016
Revises: 20260727_0015
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0016"
down_revision: str | None = "20260727_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recruitment_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("recruiter_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
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
            "current_version_number >= 1",
            name="ck_recruitment_requests_current_version",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'pending_approval', 'approved', 'rejected', 'converted')",
            name="ck_recruitment_requests_status",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recruiter_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "created_by_id",
            "idempotency_key",
            name="uq_recruitment_requests_creator_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_recruitment_requests_created_by_id"),
        "recruitment_requests",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recruitment_requests_recruiter_id"),
        "recruitment_requests",
        ["recruiter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recruitment_requests_requester_id"),
        "recruitment_requests",
        ["requester_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recruitment_requests_status"),
        "recruitment_requests",
        ["status"],
        unique=False,
    )

    op.create_table(
        "recruitment_request_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column("job_title", sa.String(length=200), nullable=False),
        sa.Column("headcount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("target_start_date", sa.Date(), nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=False),
        sa.Column("salary_max", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("headcount >= 1", name="ck_recruitment_request_headcount"),
        sa.CheckConstraint(
            "priority IN ('urgent', 'high', 'normal', 'low')",
            name="ck_recruitment_request_priority",
        ),
        sa.CheckConstraint(
            "salary_min >= 0 AND salary_max >= salary_min",
            name="ck_recruitment_request_salary_range",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_recruitment_request_version_number",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["request_id"], ["recruitment_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["recruitment_request_versions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            "version_number",
            name="uq_recruitment_request_version_number",
        ),
    )
    op.create_index(
        op.f("ix_recruitment_request_versions_created_by_id"),
        "recruitment_request_versions",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recruitment_request_versions_request_id"),
        "recruitment_request_versions",
        ["request_id"],
        unique=False,
    )

    op.create_table(
        "recruitment_request_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=True),
        sa.Column("approver_username", sa.String(length=64), nullable=False),
        sa.Column("approver_display_name", sa.String(length=100), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_recruitment_request_approval_decision",
        ),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["request_id"], ["recruitment_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["recruitment_request_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "version_id",
            name="uq_recruitment_request_approval_version",
        ),
    )
    op.create_index(
        op.f("ix_recruitment_request_approvals_approver_id"),
        "recruitment_request_approvals",
        ["approver_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recruitment_request_approvals_request_id"),
        "recruitment_request_approvals",
        ["request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_recruitment_request_approvals_request_id"),
        table_name="recruitment_request_approvals",
    )
    op.drop_index(
        op.f("ix_recruitment_request_approvals_approver_id"),
        table_name="recruitment_request_approvals",
    )
    op.drop_table("recruitment_request_approvals")
    op.drop_index(
        op.f("ix_recruitment_request_versions_request_id"),
        table_name="recruitment_request_versions",
    )
    op.drop_index(
        op.f("ix_recruitment_request_versions_created_by_id"),
        table_name="recruitment_request_versions",
    )
    op.drop_table("recruitment_request_versions")
    op.drop_index(op.f("ix_recruitment_requests_status"), table_name="recruitment_requests")
    op.drop_index(
        op.f("ix_recruitment_requests_requester_id"),
        table_name="recruitment_requests",
    )
    op.drop_index(
        op.f("ix_recruitment_requests_recruiter_id"),
        table_name="recruitment_requests",
    )
    op.drop_index(
        op.f("ix_recruitment_requests_created_by_id"),
        table_name="recruitment_requests",
    )
    op.drop_table("recruitment_requests")
