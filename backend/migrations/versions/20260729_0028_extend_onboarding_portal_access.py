"""Extend accepted Offer links for onboarding access.

Revision ID: 20260729_0028
Revises: 20260729_0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0028"
down_revision: str | None = "20260729_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE offer_portal_links AS link
            SET expires_at = GREATEST(
                link.expires_at,
                (
                    (offer_version.expected_start_date + 30)::date
                    + time '23:59:59'
                ) AT TIME ZONE 'Asia/Shanghai'
            )
            FROM offer_responses AS response
            JOIN offer_versions AS offer_version
              ON offer_version.id = response.version_id
             AND offer_version.offer_id = response.offer_id
            WHERE response.decision = 'accepted'
              AND link.id = response.portal_link_id
              AND link.offer_id = response.offer_id
              AND link.revoked_at IS NULL
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE offer_portal_links AS link
            SET expires_at = (
                offer_version.valid_until
                + time '23:59:59'
            ) AT TIME ZONE 'Asia/Shanghai'
            FROM offer_responses AS response
            JOIN offer_versions AS offer_version
              ON offer_version.id = response.version_id
             AND offer_version.offer_id = response.offer_id
            WHERE response.decision = 'accepted'
              AND link.id = response.portal_link_id
              AND link.offer_id = response.offer_id
              AND link.revoked_at IS NULL
            """
        )
    )
