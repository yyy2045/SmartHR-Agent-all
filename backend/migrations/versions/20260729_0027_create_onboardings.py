"""Create onboarding records and immutable events.

Revision ID: 20260729_0027
Revises: 20260729_0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0027"
down_revision: str | None = "20260729_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ONBOARDING_STATUSES = (
    "'pending_confirmation', 'candidate_proposed_date', 'pending_start', "
    "'onboarded', 'abandoned'"
)
_EVENT_ACTIONS = (
    "'created', 'candidate_confirmed_date', 'candidate_proposed_date', "
    "'recruiter_accepted_date', 'recruiter_proposed_date', 'onboarded', "
    "'abandoned', 'onboarded_corrected'"
)
_ABANDONMENT_SOURCES = "'candidate_withdrew', 'company_cancelled', 'other'"
_ABANDONMENT_REASONS = (
    "'compensation', 'career', 'location', 'start_date', 'personal', "
    "'position_cancelled', 'business_change', 'other'"
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_offers_application_id_id",
        "offers",
        ["application_id", "id"],
    )
    op.create_unique_constraint(
        "uq_offer_responses_offer_id_id",
        "offer_responses",
        ["offer_id", "id"],
    )

    op.create_table(
        "onboardings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("offer_id", sa.Uuid(), nullable=False),
        sa.Column("offer_response_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="pending_confirmation",
            nullable=False,
        ),
        sa.Column("candidate_proposed_date", sa.Date(), nullable=True),
        sa.Column("recruiter_proposed_date", sa.Date(), nullable=True),
        sa.Column("confirmed_start_date", sa.Date(), nullable=True),
        sa.Column("actual_start_date", sa.Date(), nullable=True),
        sa.Column("abandonment_source", sa.String(length=30), nullable=True),
        sa.Column("abandonment_reason_code", sa.String(length=40), nullable=True),
        sa.Column("abandonment_note", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
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
            f"status IN ({_ONBOARDING_STATUSES})",
            name="ck_onboardings_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_onboardings_version"),
        sa.CheckConstraint(
            "status <> 'candidate_proposed_date' OR candidate_proposed_date IS NOT NULL",
            name="ck_onboardings_candidate_proposal",
        ),
        sa.CheckConstraint(
            "status NOT IN ('pending_start', 'onboarded') "
            "OR confirmed_start_date IS NOT NULL",
            name="ck_onboardings_confirmed_start",
        ),
        sa.CheckConstraint(
            "(status = 'onboarded' AND actual_start_date IS NOT NULL) OR "
            "(status <> 'onboarded' AND actual_start_date IS NULL)",
            name="ck_onboardings_actual_start",
        ),
        sa.CheckConstraint(
            "(status = 'abandoned' "
            "AND abandonment_source IS NOT NULL "
            "AND abandonment_reason_code IS NOT NULL "
            "AND abandonment_note IS NOT NULL "
            "AND length(trim(abandonment_note)) > 0) OR "
            "(status <> 'abandoned' "
            "AND abandonment_source IS NULL "
            "AND abandonment_reason_code IS NULL "
            "AND abandonment_note IS NULL)",
            name="ck_onboardings_abandonment_fields",
        ),
        sa.CheckConstraint(
            "abandonment_source IS NULL OR "
            f"abandonment_source IN ({_ABANDONMENT_SOURCES})",
            name="ck_onboardings_abandonment_source",
        ),
        sa.CheckConstraint(
            "abandonment_reason_code IS NULL OR "
            f"abandonment_reason_code IN ({_ABANDONMENT_REASONS})",
            name="ck_onboardings_abandonment_reason",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["job_applications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "offer_id"],
            ["offers.application_id", "offers.id"],
            ondelete="CASCADE",
            name="fk_onboardings_application_offer",
        ),
        sa.ForeignKeyConstraint(
            ["offer_id", "offer_response_id"],
            ["offer_responses.offer_id", "offer_responses.id"],
            ondelete="CASCADE",
            name="fk_onboardings_offer_response",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id", name="uq_onboardings_application"),
        sa.UniqueConstraint("offer_id", name="uq_onboardings_offer"),
        sa.UniqueConstraint("offer_response_id", name="uq_onboardings_offer_response"),
    )
    op.create_index("ix_onboardings_application_id", "onboardings", ["application_id"])
    op.create_index("ix_onboardings_offer_id", "onboardings", ["offer_id"])
    op.create_index(
        "ix_onboardings_offer_response_id",
        "onboardings",
        ["offer_response_id"],
    )
    op.create_index("ix_onboardings_status", "onboardings", ["status"])

    op.create_table(
        "onboarding_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("onboarding_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("date_before", sa.Date(), nullable=True),
        sa.Column("date_after", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
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
            f"action IN ({_EVENT_ACTIONS})",
            name="ck_onboarding_events_action",
        ),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_ONBOARDING_STATUSES})",
            name="ck_onboarding_events_from_status",
        ),
        sa.CheckConstraint(
            f"to_status IN ({_ONBOARDING_STATUSES})",
            name="ck_onboarding_events_to_status",
        ),
        sa.CheckConstraint(
            "actor_type IN ('system', 'candidate', 'recruiter', 'admin')",
            name="ck_onboarding_events_actor_type",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_onboarding_events_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["onboarding_id"],
            ["onboardings.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "onboarding_id",
            "idempotency_key",
            name="uq_onboarding_events_idempotency",
        ),
        sa.UniqueConstraint(
            "onboarding_id",
            "sequence_number",
            name="uq_onboarding_events_sequence",
        ),
    )
    op.create_index("ix_onboarding_events_action", "onboarding_events", ["action"])
    op.create_index(
        "ix_onboarding_events_actor_type",
        "onboarding_events",
        ["actor_type"],
    )
    op.create_index(
        "ix_onboarding_events_actor_user_id",
        "onboarding_events",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_onboarding_events_onboarding_id",
        "onboarding_events",
        ["onboarding_id"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO onboardings (
                id,
                application_id,
                offer_id,
                offer_response_id,
                status,
                version,
                created_at,
                updated_at
            )
            SELECT
                CAST(md5(offer_response.id::text || '-onboarding') AS uuid),
                offer.application_id,
                offer.id,
                offer_response.id,
                'pending_confirmation',
                1,
                offer_response.responded_at,
                offer_response.responded_at
            FROM offer_responses AS offer_response
            JOIN offers AS offer ON offer.id = offer_response.offer_id
            WHERE offer_response.decision = 'accepted'
              AND offer.status = 'accepted'
              AND NOT EXISTS (
                  SELECT 1
                  FROM onboardings AS existing
                  WHERE existing.offer_response_id = offer_response.id
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO onboarding_events (
                id,
                onboarding_id,
                sequence_number,
                idempotency_key,
                action,
                from_status,
                to_status,
                reason,
                actor_type,
                created_at
            )
            SELECT
                CAST(md5(onboarding.id::text || '-created-event') AS uuid),
                onboarding.id,
                1,
                CAST(md5(onboarding.id::text || '-created-idempotency') AS uuid),
                'created',
                NULL,
                'pending_confirmation',
                '候选人接受 Offer，系统回填入职记录',
                'system',
                onboarding.created_at
            FROM onboardings AS onboarding
            WHERE NOT EXISTS (
                SELECT 1
                FROM onboarding_events AS existing
                WHERE existing.onboarding_id = onboarding.id
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_onboarding_events_onboarding_id", table_name="onboarding_events")
    op.drop_index("ix_onboarding_events_actor_user_id", table_name="onboarding_events")
    op.drop_index("ix_onboarding_events_actor_type", table_name="onboarding_events")
    op.drop_index("ix_onboarding_events_action", table_name="onboarding_events")
    op.drop_table("onboarding_events")
    op.drop_index("ix_onboardings_status", table_name="onboardings")
    op.drop_index("ix_onboardings_offer_response_id", table_name="onboardings")
    op.drop_index("ix_onboardings_offer_id", table_name="onboardings")
    op.drop_index("ix_onboardings_application_id", table_name="onboardings")
    op.drop_table("onboardings")
    op.drop_constraint(
        "uq_offer_responses_offer_id_id",
        "offer_responses",
        type_="unique",
    )
    op.drop_constraint(
        "uq_offers_application_id_id",
        "offers",
        type_="unique",
    )
