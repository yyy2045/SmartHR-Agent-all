"""创建职位内候选人流程看板

Revision ID: 20260726_0011
Revises: 20260725_0010
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0011"
down_revision: str | None = "20260725_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAGE_CHECK = (
    "'unprocessed', 'pending', 'shortlisted', 'to_contact', "
    "'contacted', 'to_interview', 'completed', 'rejected'"
)


def upgrade() -> None:
    op.create_table(
        "candidate_processes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("current_stage", sa.String(length=30), nullable=False),
        sa.Column(
            "stage_entered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
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
            f"current_stage IN ({STAGE_CHECK})",
            name="ck_candidate_processes_stage",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["resume_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="uq_candidate_process_document"),
    )
    op.create_index(
        op.f("ix_candidate_processes_current_stage"),
        "candidate_processes",
        ["current_stage"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_processes_document_id"),
        "candidate_processes",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_processes_updated_by_id"),
        "candidate_processes",
        ["updated_by_id"],
        unique=False,
    )

    op.create_table(
        "candidate_process_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("process_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("from_stage", sa.String(length=30), nullable=False),
        sa.Column("to_stage", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"from_stage IN ({STAGE_CHECK})",
            name="ck_candidate_process_events_from_stage",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_candidate_process_events_sequence",
        ),
        sa.CheckConstraint(
            f"to_stage IN ({STAGE_CHECK})",
            name="ck_candidate_process_events_to_stage",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["candidate_processes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "process_id",
            "sequence_number",
            name="uq_candidate_process_event_sequence",
        ),
    )
    op.create_index(
        op.f("ix_candidate_process_events_operator_id"),
        "candidate_process_events",
        ["operator_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_process_events_process_id"),
        "candidate_process_events",
        ["process_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_candidate_process_events_process_id"),
        table_name="candidate_process_events",
    )
    op.drop_index(
        op.f("ix_candidate_process_events_operator_id"),
        table_name="candidate_process_events",
    )
    op.drop_table("candidate_process_events")
    op.drop_index(
        op.f("ix_candidate_processes_updated_by_id"),
        table_name="candidate_processes",
    )
    op.drop_index(
        op.f("ix_candidate_processes_document_id"),
        table_name="candidate_processes",
    )
    op.drop_index(
        op.f("ix_candidate_processes_current_stage"),
        table_name="candidate_processes",
    )
    op.drop_table("candidate_processes")
