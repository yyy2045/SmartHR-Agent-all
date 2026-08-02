"""Create internal notifications.

Revision ID: 20260730_0039
Revises: 20260730_0038
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0039"
down_revision: str | None = "20260730_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "internal_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(length=160), nullable=False),
        sa.Column("notification_type", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.String(length=60), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("route_path", sa.String(length=500), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(event_key)) BETWEEN 1 AND 160",
            name="ck_internal_notifications_event_key",
        ),
        sa.CheckConstraint(
            "length(trim(notification_type)) BETWEEN 1 AND 60",
            name="ck_internal_notifications_type",
        ),
        sa.CheckConstraint(
            "length(trim(title)) BETWEEN 1 AND 200",
            name="ck_internal_notifications_title",
        ),
        sa.CheckConstraint(
            "length(summary) <= 500",
            name="ck_internal_notifications_summary_length",
        ),
        sa.CheckConstraint(
            "length(trim(resource_type)) BETWEEN 1 AND 60",
            name="ck_internal_notifications_resource_type",
        ),
        sa.CheckConstraint(
            "route_path LIKE '/%' AND length(trim(route_path)) BETWEEN 1 AND 500",
            name="ck_internal_notifications_route_path",
        ),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipient_user_id",
            "event_key",
            "notification_type",
            name="uq_internal_notifications_event_recipient",
        ),
    )
    op.create_index(
        "ix_internal_notifications_recipient_user_id",
        "internal_notifications",
        ["recipient_user_id"],
    )
    op.create_index(
        "ix_internal_notifications_notification_type",
        "internal_notifications",
        ["notification_type"],
    )
    op.create_index(
        "ix_internal_notifications_resource_id",
        "internal_notifications",
        ["resource_id"],
    )
    op.create_index(
        "ix_internal_notifications_read_at",
        "internal_notifications",
        ["read_at"],
    )
    op.create_index(
        "ix_internal_notifications_created_at",
        "internal_notifications",
        ["created_at"],
    )
    op.create_index(
        "ix_internal_notifications_recipient_unread_created",
        "internal_notifications",
        ["recipient_user_id", "read_at", "created_at"],
    )
    op.create_index(
        "ix_internal_notifications_resource",
        "internal_notifications",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_internal_notifications_resource", table_name="internal_notifications")
    op.drop_index(
        "ix_internal_notifications_recipient_unread_created",
        table_name="internal_notifications",
    )
    op.drop_index("ix_internal_notifications_created_at", table_name="internal_notifications")
    op.drop_index("ix_internal_notifications_read_at", table_name="internal_notifications")
    op.drop_index("ix_internal_notifications_resource_id", table_name="internal_notifications")
    op.drop_index(
        "ix_internal_notifications_notification_type",
        table_name="internal_notifications",
    )
    op.drop_index(
        "ix_internal_notifications_recipient_user_id",
        table_name="internal_notifications",
    )
    op.drop_table("internal_notifications")