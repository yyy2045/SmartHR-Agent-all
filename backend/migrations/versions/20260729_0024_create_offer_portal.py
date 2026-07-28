"""Create Offer portal links and candidate responses.

Revision ID: 20260729_0024
Revises: 20260728_0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0024"
down_revision: str | None = "20260728_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_OFFER_STATUS = (
    "status IN ('draft', 'pending_manager_confirmation', "
    "'pending_approval', 'approved', 'rejected')"
)
_NEW_OFFER_STATUS = (
    "status IN ('draft', 'pending_manager_confirmation', "
    "'pending_approval', 'approved', 'rejected', "
    "'pending_response', 'accepted', 'declined')"
)
_OLD_PROCESS_STAGES = (
    "'unprocessed', 'pending', 'shortlisted', 'to_contact', "
    "'contacted', 'to_interview', 'completed', 'rejected'"
)
_NEW_PROCESS_STAGES = (
    f"{_OLD_PROCESS_STAGES}, 'offer_pending_response', "
    "'offer_rejected', 'onboarding_pending_confirmation'"
)


def _replace_stage_constraints(stage_values: str) -> None:
    op.drop_constraint(
        "ck_candidate_process_events_to_stage",
        "candidate_process_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_candidate_process_events_from_stage",
        "candidate_process_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_candidate_processes_stage",
        "candidate_processes",
        type_="check",
    )
    op.create_check_constraint(
        "ck_candidate_processes_stage",
        "candidate_processes",
        f"current_stage IN ({stage_values})",
    )
    op.create_check_constraint(
        "ck_candidate_process_events_from_stage",
        "candidate_process_events",
        f"from_stage IN ({stage_values})",
    )
    op.create_check_constraint(
        "ck_candidate_process_events_to_stage",
        "candidate_process_events",
        f"to_stage IN ({stage_values})",
    )


def upgrade() -> None:
    op.drop_constraint("ck_offers_status", "offers", type_="check")
    op.create_check_constraint("ck_offers_status", "offers", _NEW_OFFER_STATUS)
    _replace_stage_constraints(_NEW_PROCESS_STAGES)
    op.create_unique_constraint(
        "uq_offer_versions_offer_id_id",
        "offer_versions",
        ["offer_id", "id"],
    )

    op.create_table(
        "offer_portal_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_by_username", sa.String(length=64), nullable=True),
        sa.Column("revoked_by_display_name", sa.String(length=100), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_offer_portal_links_expiry",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by_id IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="ck_offer_portal_links_revocation",
        ),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["offer_id", "version_id"],
            ["offer_versions.offer_id", "offer_versions.id"],
            ondelete="CASCADE",
            name="fk_offer_portal_links_offer_version",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "offer_id",
            "idempotency_key",
            name="uq_offer_portal_links_idempotency",
        ),
        sa.UniqueConstraint(
            "offer_id",
            "id",
            name="uq_offer_portal_links_offer_id_id",
        ),
        sa.UniqueConstraint("token_hash", name="uq_offer_portal_links_token_hash"),
    )
    op.create_index(
        "ix_offer_portal_links_created_by_id",
        "offer_portal_links",
        ["created_by_id"],
    )
    op.create_index(
        "ix_offer_portal_links_expires_at",
        "offer_portal_links",
        ["expires_at"],
    )
    op.create_index(
        "ix_offer_portal_links_offer_id",
        "offer_portal_links",
        ["offer_id"],
    )
    op.create_index(
        "ix_offer_portal_links_revoked_at",
        "offer_portal_links",
        ["revoked_at"],
    )
    op.create_index(
        "ix_offer_portal_links_revoked_by_id",
        "offer_portal_links",
        ["revoked_by_id"],
    )
    op.create_index(
        "ix_offer_portal_links_version_id",
        "offer_portal_links",
        ["version_id"],
    )
    op.create_index(
        "uq_offer_portal_links_active_offer",
        "offer_portal_links",
        ["offer_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "offer_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("portal_link_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("rejection_reason_code", sa.String(length=30), nullable=True),
        sa.Column("rejection_note", sa.Text(), nullable=True),
        sa.Column(
            "verification_completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "responded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_offer_responses_decision",
        ),
        sa.CheckConstraint(
            "(decision = 'accepted' AND rejection_reason_code IS NULL "
            "AND rejection_note IS NULL) OR "
            "(decision = 'rejected' AND rejection_reason_code IS NOT NULL "
            "AND rejection_reason_code IN "
            "('compensation', 'career', 'location', 'timing', 'other'))",
            name="ck_offer_responses_rejection",
        ),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["offer_id", "portal_link_id"],
            ["offer_portal_links.offer_id", "offer_portal_links.id"],
            ondelete="CASCADE",
            name="fk_offer_responses_offer_portal_link",
        ),
        sa.ForeignKeyConstraint(
            ["offer_id", "version_id"],
            ["offer_versions.offer_id", "offer_versions.id"],
            ondelete="CASCADE",
            name="fk_offer_responses_offer_version",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "offer_id",
            "idempotency_key",
            name="uq_offer_responses_idempotency",
        ),
        sa.UniqueConstraint("offer_id", name="uq_offer_responses_offer"),
        sa.UniqueConstraint("portal_link_id", name="uq_offer_responses_portal_link"),
    )
    op.create_index(
        "ix_offer_responses_decision", "offer_responses", ["decision"]
    )
    op.create_index("ix_offer_responses_offer_id", "offer_responses", ["offer_id"])
    op.create_index(
        "ix_offer_responses_portal_link_id",
        "offer_responses",
        ["portal_link_id"],
    )
    op.create_index(
        "ix_offer_responses_version_id", "offer_responses", ["version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_offer_responses_version_id", table_name="offer_responses")
    op.drop_index("ix_offer_responses_portal_link_id", table_name="offer_responses")
    op.drop_index("ix_offer_responses_offer_id", table_name="offer_responses")
    op.drop_index("ix_offer_responses_decision", table_name="offer_responses")
    op.drop_table("offer_responses")

    op.drop_index(
        "uq_offer_portal_links_active_offer", table_name="offer_portal_links"
    )
    op.drop_index("ix_offer_portal_links_version_id", table_name="offer_portal_links")
    op.drop_index(
        "ix_offer_portal_links_revoked_by_id", table_name="offer_portal_links"
    )
    op.drop_index("ix_offer_portal_links_revoked_at", table_name="offer_portal_links")
    op.drop_index("ix_offer_portal_links_offer_id", table_name="offer_portal_links")
    op.drop_index("ix_offer_portal_links_expires_at", table_name="offer_portal_links")
    op.drop_index(
        "ix_offer_portal_links_created_by_id", table_name="offer_portal_links"
    )
    op.drop_table("offer_portal_links")
    op.drop_constraint(
        "uq_offer_versions_offer_id_id",
        "offer_versions",
        type_="unique",
    )

    op.execute(
        sa.text(
            "UPDATE offers SET status = 'approved' "
            "WHERE status IN ('pending_response', 'accepted', 'declined')"
        )
    )
    op.drop_constraint("ck_offers_status", "offers", type_="check")
    op.create_check_constraint("ck_offers_status", "offers", _OLD_OFFER_STATUS)

    op.execute(
        sa.text(
            "UPDATE candidate_processes SET current_stage = CASE "
            "WHEN current_stage = 'offer_rejected' THEN 'rejected' ELSE 'completed' END "
            "WHERE current_stage IN ('offer_pending_response', 'offer_rejected', "
            "'onboarding_pending_confirmation')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE candidate_process_events SET from_stage = CASE "
            "WHEN from_stage = 'offer_rejected' THEN 'rejected' ELSE 'completed' END "
            "WHERE from_stage IN ('offer_pending_response', 'offer_rejected', "
            "'onboarding_pending_confirmation')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE candidate_process_events SET to_stage = CASE "
            "WHEN to_stage = 'offer_rejected' THEN 'rejected' ELSE 'completed' END "
            "WHERE to_stage IN ('offer_pending_response', 'offer_rejected', "
            "'onboarding_pending_confirmation')"
        )
    )
    _replace_stage_constraints(_OLD_PROCESS_STAGES)
