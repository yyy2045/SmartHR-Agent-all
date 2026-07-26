"""创建候选人面试场次与轮次安排

Revision ID: 20260726_0013
Revises: 20260726_0012
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0013"
down_revision: str | None = "20260726_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_interview_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
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
            "status IN ('scheduled', 'partially_cancelled', 'cancelled')",
            name="ck_candidate_interview_schedules_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["resume_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["plan_version_id"], ["interview_plan_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", name="uq_candidate_interview_schedule_document"
        ),
    )
    op.create_index(
        op.f("ix_candidate_interview_schedules_created_by_id"),
        "candidate_interview_schedules",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_interview_schedules_document_id"),
        "candidate_interview_schedules",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_interview_schedules_plan_version_id"),
        "candidate_interview_schedules",
        ["plan_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_interview_schedules_status"),
        "candidate_interview_schedules",
        ["status"],
        unique=False,
    )

    op.create_table(
        "candidate_interview_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("plan_round_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interview_method", sa.String(length=20), nullable=False),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("meeting_url", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reschedule_count", sa.Integer(), nullable=False),
        sa.Column("last_change_reason", sa.Text(), nullable=True),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
            "interview_method IN ('onsite', 'online', 'phone')",
            name="ck_candidate_interview_rounds_method",
        ),
        sa.CheckConstraint(
            "reschedule_count >= 0",
            name="ck_candidate_interview_rounds_reschedule_count",
        ),
        sa.CheckConstraint(
            "sort_order >= 0", name="ck_candidate_interview_rounds_sort_order"
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'rescheduled', 'cancelled')",
            name="ck_candidate_interview_rounds_status",
        ),
        sa.ForeignKeyConstraint(
            ["plan_round_id"], ["interview_rounds.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["candidate_interview_schedules.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "schedule_id",
            "plan_round_id",
            name="uq_candidate_interview_round_plan_round",
        ),
        sa.UniqueConstraint(
            "schedule_id",
            "sort_order",
            name="uq_candidate_interview_round_sort_order",
        ),
    )
    op.create_index(
        op.f("ix_candidate_interview_rounds_plan_round_id"),
        "candidate_interview_rounds",
        ["plan_round_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_interview_rounds_schedule_id"),
        "candidate_interview_rounds",
        ["schedule_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_interview_rounds_status"),
        "candidate_interview_rounds",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_interview_rounds_updated_by_id"),
        "candidate_interview_rounds",
        ["updated_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_candidate_interview_rounds_updated_by_id"),
        table_name="candidate_interview_rounds",
    )
    op.drop_index(
        op.f("ix_candidate_interview_rounds_status"),
        table_name="candidate_interview_rounds",
    )
    op.drop_index(
        op.f("ix_candidate_interview_rounds_schedule_id"),
        table_name="candidate_interview_rounds",
    )
    op.drop_index(
        op.f("ix_candidate_interview_rounds_plan_round_id"),
        table_name="candidate_interview_rounds",
    )
    op.drop_table("candidate_interview_rounds")
    op.drop_index(
        op.f("ix_candidate_interview_schedules_status"),
        table_name="candidate_interview_schedules",
    )
    op.drop_index(
        op.f("ix_candidate_interview_schedules_plan_version_id"),
        table_name="candidate_interview_schedules",
    )
    op.drop_index(
        op.f("ix_candidate_interview_schedules_document_id"),
        table_name="candidate_interview_schedules",
    )
    op.drop_index(
        op.f("ix_candidate_interview_schedules_created_by_id"),
        table_name="candidate_interview_schedules",
    )
    op.drop_table("candidate_interview_schedules")
