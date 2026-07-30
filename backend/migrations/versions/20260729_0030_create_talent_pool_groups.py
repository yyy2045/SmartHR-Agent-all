"""Create talent pool groups and membership history.

Revision ID: 20260729_0030
Revises: 20260729_0029
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0030"
down_revision: str | None = "20260729_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "talent_pool_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_talent_pool_groups_name_not_blank",
        ),
        sa.CheckConstraint("version >= 1", name="ck_talent_pool_groups_version"),
        sa.ForeignKeyConstraint(
            ["archived_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_talent_pool_groups_archived_at",
        "talent_pool_groups",
        ["archived_at"],
    )
    op.create_index(
        "ix_talent_pool_groups_archived_by_id",
        "talent_pool_groups",
        ["archived_by_id"],
    )
    op.create_index(
        "ix_talent_pool_groups_created_by_id",
        "talent_pool_groups",
        ["created_by_id"],
    )
    op.create_index(
        "uq_talent_pool_groups_active_name_ci",
        "talent_pool_groups",
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
        sqlite_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "talent_pool_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("source_application_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'removed')",
            name="ck_talent_pool_memberships_status",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_talent_pool_memberships_reason_not_blank",
        ),
        sa.CheckConstraint("version >= 1", name="ck_talent_pool_memberships_version"),
        sa.CheckConstraint(
            "(status = 'active' AND removed_at IS NULL) OR "
            "(status = 'removed' AND removed_at IS NOT NULL)",
            name="ck_talent_pool_memberships_removed_at",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidates.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["talent_pool_groups.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_application_id"],
            ["job_applications.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id",
            "candidate_id",
            name="uq_talent_pool_memberships_group_candidate",
        ),
    )
    op.create_index(
        "ix_talent_pool_memberships_candidate_status",
        "talent_pool_memberships",
        ["candidate_id", "status"],
    )
    op.create_index(
        "ix_talent_pool_memberships_group_status",
        "talent_pool_memberships",
        ["group_id", "status"],
    )
    op.create_index(
        "ix_talent_pool_memberships_source_application_id",
        "talent_pool_memberships",
        ["source_application_id"],
    )
    op.create_index(
        "ix_talent_pool_memberships_updated_by_id",
        "talent_pool_memberships",
        ["updated_by_id"],
    )

    op.create_table(
        "talent_pool_membership_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("candidate_id_snapshot", sa.Uuid(), nullable=False),
        sa.Column("target_candidate_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column("source_application_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=True),
        sa.Column("actor_display_name", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('added', 'removed', 'candidate_merged')",
            name="ck_talent_pool_membership_events_action",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('active', 'removed')",
            name="ck_talent_pool_membership_events_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('active', 'removed')",
            name="ck_talent_pool_membership_events_to_status",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_talent_pool_membership_events_reason_not_blank",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_talent_pool_membership_events_sequence",
        ),
        sa.CheckConstraint(
            "(action = 'candidate_merged' AND target_candidate_id_snapshot IS NOT NULL) "
            "OR (action <> 'candidate_merged' AND target_candidate_id_snapshot IS NULL)",
            name="ck_talent_pool_membership_events_merge_target",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["talent_pool_memberships.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "membership_id",
            "idempotency_key",
            name="uq_talent_pool_membership_events_idempotency",
        ),
        sa.UniqueConstraint(
            "membership_id",
            "sequence_number",
            name="uq_talent_pool_membership_events_sequence",
        ),
    )
    op.create_index(
        "ix_talent_pool_membership_events_action",
        "talent_pool_membership_events",
        ["action"],
    )
    op.create_index(
        "ix_talent_pool_membership_events_actor_user_id",
        "talent_pool_membership_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_talent_pool_membership_events_candidate_id_snapshot",
        "talent_pool_membership_events",
        ["candidate_id_snapshot"],
    )
    op.create_index(
        "ix_talent_pool_membership_events_membership_id",
        "talent_pool_membership_events",
        ["membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_talent_pool_membership_events_membership_id",
        table_name="talent_pool_membership_events",
    )
    op.drop_index(
        "ix_talent_pool_membership_events_candidate_id_snapshot",
        table_name="talent_pool_membership_events",
    )
    op.drop_index(
        "ix_talent_pool_membership_events_actor_user_id",
        table_name="talent_pool_membership_events",
    )
    op.drop_index(
        "ix_talent_pool_membership_events_action",
        table_name="talent_pool_membership_events",
    )
    op.drop_table("talent_pool_membership_events")

    op.drop_index(
        "ix_talent_pool_memberships_updated_by_id",
        table_name="talent_pool_memberships",
    )
    op.drop_index(
        "ix_talent_pool_memberships_source_application_id",
        table_name="talent_pool_memberships",
    )
    op.drop_index(
        "ix_talent_pool_memberships_group_status",
        table_name="talent_pool_memberships",
    )
    op.drop_index(
        "ix_talent_pool_memberships_candidate_status",
        table_name="talent_pool_memberships",
    )
    op.drop_table("talent_pool_memberships")

    op.drop_index(
        "uq_talent_pool_groups_active_name_ci",
        table_name="talent_pool_groups",
    )
    op.drop_index(
        "ix_talent_pool_groups_created_by_id",
        table_name="talent_pool_groups",
    )
    op.drop_index(
        "ix_talent_pool_groups_archived_by_id",
        table_name="talent_pool_groups",
    )
    op.drop_index(
        "ix_talent_pool_groups_archived_at",
        table_name="talent_pool_groups",
    )
    op.drop_table("talent_pool_groups")
