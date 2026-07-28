"""Add immutable phone verification digest to Offer portal links.

Revision ID: 20260729_0025
Revises: 20260729_0024
"""

import hashlib
import hmac
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.config import settings

revision: str = "20260729_0025"
down_revision: str | None = "20260729_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _phone_digest(link_id: object, phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    verification_value = digits[-4:] if len(digits) >= 4 else f"unavailable:{link_id}"
    message = f"offer-portal-phone:{link_id}:{verification_value}"
    return hmac.new(
        settings.app_secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def upgrade() -> None:
    op.add_column(
        "offer_portal_links",
        sa.Column("verification_phone_digest", sa.String(length=64), nullable=True),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT links.id, candidates.phone "
            "FROM offer_portal_links AS links "
            "JOIN offers ON offers.id = links.offer_id "
            "JOIN job_applications ON job_applications.id = offers.application_id "
            "JOIN candidates ON candidates.id = job_applications.candidate_id"
        )
    ).mappings()
    for row in rows:
        connection.execute(
            sa.text(
                "UPDATE offer_portal_links "
                "SET verification_phone_digest = :digest WHERE id = :link_id"
            ),
            {
                "digest": _phone_digest(row["id"], row["phone"]),
                "link_id": row["id"],
            },
        )
    op.alter_column(
        "offer_portal_links",
        "verification_phone_digest",
        existing_type=sa.String(length=64),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("offer_portal_links", "verification_phone_digest")
