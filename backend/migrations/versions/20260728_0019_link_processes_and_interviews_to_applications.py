"""将流程和面试业务关联到应聘记录

Revision ID: 20260728_0019
Revises: 20260728_0018
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0019"
down_revision: str | None = "20260728_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_document_with_application(table_name: str, old_unique: str, new_unique: str) -> None:
    op.add_column(table_name, sa.Column("application_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            f"""
            UPDATE {table_name} target
            SET application_id = rd.application_id
            FROM resume_documents rd
            WHERE rd.id = target.document_id
            """
        )
    )
    op.alter_column(table_name, "application_id", nullable=False)
    op.create_foreign_key(
        f"fk_{table_name}_application_id",
        table_name,
        "job_applications",
        ["application_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(f"ix_{table_name}_application_id", table_name, ["application_id"])
    op.create_unique_constraint(new_unique, table_name, ["application_id"])
    op.drop_constraint(old_unique, table_name, type_="unique")
    op.drop_index(f"ix_{table_name}_document_id", table_name=table_name)
    op.drop_constraint(f"{table_name}_document_id_fkey", table_name, type_="foreignkey")
    op.drop_column(table_name, "document_id")


def _replace_application_with_document(table_name: str, old_unique: str, new_unique: str) -> None:
    op.add_column(table_name, sa.Column("document_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            f"""
            UPDATE {table_name} target
            SET document_id = (
                SELECT rd.id
                FROM resume_documents rd
                WHERE rd.application_id = target.application_id
                ORDER BY rd.created_at, rd.id
                LIMIT 1
            )
            """
        )
    )
    op.alter_column(table_name, "document_id", nullable=False)
    op.create_foreign_key(
        f"{table_name}_document_id_fkey",
        table_name,
        "resume_documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(f"ix_{table_name}_document_id", table_name, ["document_id"])
    op.create_unique_constraint(new_unique, table_name, ["document_id"])
    op.drop_constraint(old_unique, table_name, type_="unique")
    op.drop_index(f"ix_{table_name}_application_id", table_name=table_name)
    op.drop_constraint(
        f"fk_{table_name}_application_id", table_name, type_="foreignkey"
    )
    op.drop_column(table_name, "application_id")


def upgrade() -> None:
    _replace_document_with_application(
        "candidate_processes",
        "uq_candidate_process_document",
        "uq_candidate_process_application",
    )
    _replace_document_with_application(
        "candidate_interview_schedules",
        "uq_candidate_interview_schedule_document",
        "uq_candidate_interview_schedule_application",
    )


def downgrade() -> None:
    _replace_application_with_document(
        "candidate_interview_schedules",
        "uq_candidate_interview_schedule_application",
        "uq_candidate_interview_schedule_document",
    )
    _replace_application_with_document(
        "candidate_processes",
        "uq_candidate_process_application",
        "uq_candidate_process_document",
    )
