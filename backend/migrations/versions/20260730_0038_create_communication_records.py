"""Create immutable candidate communication records.

Revision ID: 20260730_0038
Revises: 20260730_0037
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0038"
down_revision: str | None = "20260730_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "communication_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("context_type", sa.String(length=30), nullable=False),
        sa.Column("context_id", sa.Uuid(), nullable=False),
        sa.Column("template_version_id", sa.Uuid(), nullable=True),
        sa.Column("record_kind", sa.String(length=20), server_default="sent", nullable=False),
        sa.Column("root_record_id", sa.Uuid(), nullable=True),
        sa.Column("corrects_record_id", sa.Uuid(), nullable=True),
        sa.Column("correction_sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("channel_detail", sa.String(length=100), nullable=True),
        sa.Column("recipient_type", sa.String(length=20), nullable=False),
        sa.Column("recipient_masked", sa.String(length=320), nullable=False),
        sa.Column("candidate_name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("subject_snapshot", sa.String(length=500), nullable=False),
        sa.Column("body_snapshot", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_historical", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("historical_note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username_snapshot", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name_snapshot", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "record_kind IN ('sent', 'correction')",
            name="ck_communication_records_kind",
        ),
        sa.CheckConstraint(
            "context_type IN ('interview_round', 'offer', 'onboarding')",
            name="ck_communication_records_context_type",
        ),
        sa.CheckConstraint(
            "channel IN ('wechat', 'phone', 'sms', 'email', 'other')",
            name="ck_communication_records_channel",
        ),
        sa.CheckConstraint(
            "recipient_type IN ('phone', 'email', 'other')",
            name="ck_communication_records_recipient_type",
        ),
        sa.CheckConstraint(
            "(channel IN ('wechat', 'phone', 'sms') AND recipient_type = 'phone') OR "
            "(channel = 'email' AND recipient_type = 'email') OR "
            "(channel = 'other' AND recipient_type = 'other')",
            name="ck_communication_records_channel_recipient",
        ),
        sa.CheckConstraint(
            "(channel = 'other' AND channel_detail IS NOT NULL "
            "AND length(trim(channel_detail)) > 0) OR "
            "(channel <> 'other' AND channel_detail IS NULL)",
            name="ck_communication_records_channel_detail",
        ),
        sa.CheckConstraint(
            "recipient_type = 'other' OR recipient_masked LIKE '%*%'",
            name="ck_communication_records_recipient_masked",
        ),
        sa.CheckConstraint(
            "length(trim(candidate_name_snapshot)) BETWEEN 1 AND 200",
            name="ck_communication_records_candidate_name",
        ),
        sa.CheckConstraint(
            "length(trim(recipient_masked)) BETWEEN 1 AND 320",
            name="ck_communication_records_recipient_length",
        ),
        sa.CheckConstraint(
            "length(trim(subject_snapshot)) BETWEEN 1 AND 500",
            name="ck_communication_records_subject_length",
        ),
        sa.CheckConstraint(
            "length(trim(body_snapshot)) BETWEEN 1 AND 10000",
            name="ck_communication_records_body_length",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_communication_records_fingerprint_length",
        ),
        sa.CheckConstraint(
            "(NOT is_historical AND historical_note IS NULL) OR "
            "(is_historical AND historical_note IS NOT NULL "
            "AND length(trim(historical_note)) > 0)",
            name="ck_communication_records_historical_note",
        ),
        sa.CheckConstraint(
            "(record_kind = 'sent' AND root_record_id IS NULL "
            "AND corrects_record_id IS NULL AND correction_sequence = 0 "
            "AND correction_reason IS NULL) OR "
            "(record_kind = 'correction' AND root_record_id IS NOT NULL "
            "AND corrects_record_id IS NOT NULL AND correction_sequence >= 1 "
            "AND correction_reason IS NOT NULL "
            "AND length(trim(correction_reason)) > 0)",
            name="ck_communication_records_correction_fields",
        ),
        sa.CheckConstraint(
            "root_record_id IS NULL OR root_record_id <> id",
            name="ck_communication_records_root_not_self",
        ),
        sa.CheckConstraint(
            "corrects_record_id IS NULL OR corrects_record_id <> id",
            name="ck_communication_records_corrects_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["job_applications.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["template_version_id"], ["message_template_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["root_record_id"], ["communication_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["corrects_record_id"], ["communication_records.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_communication_records_idempotency"
        ),
        sa.UniqueConstraint(
            "corrects_record_id", name="uq_communication_records_corrects"
        ),
        sa.UniqueConstraint(
            "root_record_id",
            "correction_sequence",
            name="uq_communication_records_root_sequence",
        ),
    )
    op.create_index(
        "ix_communication_records_application_id",
        "communication_records",
        ["application_id"],
    )
    op.create_index(
        "ix_communication_records_candidate_id",
        "communication_records",
        ["candidate_id"],
    )
    op.create_index(
        "ix_communication_records_template_version_id",
        "communication_records",
        ["template_version_id"],
    )
    op.create_index(
        "ix_communication_records_record_kind", "communication_records", ["record_kind"]
    )
    op.create_index(
        "ix_communication_records_root_record_id",
        "communication_records",
        ["root_record_id"],
    )
    op.create_index(
        "ix_communication_records_corrects_record_id",
        "communication_records",
        ["corrects_record_id"],
    )
    op.create_index(
        "ix_communication_records_channel", "communication_records", ["channel"]
    )
    op.create_index(
        "ix_communication_records_sent_at", "communication_records", ["sent_at"]
    )
    op.create_index(
        "ix_communication_records_created_by_id",
        "communication_records",
        ["created_by_id"],
    )
    op.create_index(
        "ix_communication_records_context",
        "communication_records",
        ["context_type", "context_id"],
    )
    op.create_index(
        "ix_communication_records_application_sent",
        "communication_records",
        ["application_id", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_communication_records_application_sent", table_name="communication_records"
    )
    op.drop_index("ix_communication_records_context", table_name="communication_records")
    op.drop_index(
        "ix_communication_records_created_by_id", table_name="communication_records"
    )
    op.drop_index("ix_communication_records_sent_at", table_name="communication_records")
    op.drop_index("ix_communication_records_channel", table_name="communication_records")
    op.drop_index(
        "ix_communication_records_corrects_record_id", table_name="communication_records"
    )
    op.drop_index(
        "ix_communication_records_root_record_id", table_name="communication_records"
    )
    op.drop_index(
        "ix_communication_records_record_kind", table_name="communication_records"
    )
    op.drop_index(
        "ix_communication_records_template_version_id", table_name="communication_records"
    )
    op.drop_index(
        "ix_communication_records_candidate_id", table_name="communication_records"
    )
    op.drop_index(
        "ix_communication_records_application_id", table_name="communication_records"
    )
    op.drop_table("communication_records")
