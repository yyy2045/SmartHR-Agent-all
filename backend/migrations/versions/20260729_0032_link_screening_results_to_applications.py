"""Link screening results directly to job applications.

Revision ID: 20260729_0032
Revises: 20260729_0031
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0032"
down_revision: str | None = "20260729_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "screening_results",
        sa.Column("application_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE screening_results AS result
            SET application_id = document.application_id
            FROM resume_documents AS document
            WHERE result.document_id = document.id
              AND document.application_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE screening_results AS result
            SET application_id = single_link.application_id
            FROM (
                SELECT document_id, min(application_id::text)::uuid AS application_id
                FROM application_resume_documents
                GROUP BY document_id
                HAVING count(*) = 1
            ) AS single_link
            WHERE result.document_id = single_link.document_id
              AND result.application_id IS NULL
            """
        )
    )
    orphaned_results = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM screening_results WHERE application_id IS NULL")
    )
    if orphaned_results:
        raise RuntimeError(
            "Cannot link screening results because one or more resume documents "
            "do not have an unambiguous job application."
        )

    op.alter_column("screening_results", "application_id", nullable=False)
    op.create_index(
        "ix_screening_results_application_id",
        "screening_results",
        ["application_id"],
    )
    op.create_foreign_key(
        "fk_screening_results_application_id",
        "screening_results",
        "job_applications",
        ["application_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_screening_results_application_document",
        "screening_results",
        "application_resume_documents",
        ["application_id", "document_id"],
        ["application_id", "document_id"],
        ondelete="CASCADE",
        deferrable=True,
        initially="DEFERRED",
    )
    op.drop_constraint(
        "uq_screening_result_analysis_version",
        "screening_results",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_screening_result_analysis_version",
        "screening_results",
        ["application_id", "criteria_version_id", "analysis_version"],
    )


def downgrade() -> None:
    duplicate_versions = op.get_bind().scalar(
        sa.text(
            """
            SELECT count(*)
            FROM (
                SELECT document_id, criteria_version_id, analysis_version
                FROM screening_results
                GROUP BY document_id, criteria_version_id, analysis_version
                HAVING count(*) > 1
            ) AS duplicates
            """
        )
    )
    if duplicate_versions:
        raise RuntimeError(
            "Cannot downgrade application-level screening results while the same "
            "resume has overlapping analysis versions across applications."
        )

    op.drop_constraint(
        "uq_screening_result_analysis_version",
        "screening_results",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_screening_result_analysis_version",
        "screening_results",
        ["document_id", "criteria_version_id", "analysis_version"],
    )
    op.drop_constraint(
        "fk_screening_results_application_document",
        "screening_results",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_screening_results_application_id",
        "screening_results",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_screening_results_application_id",
        table_name="screening_results",
    )
    op.drop_column("screening_results", "application_id")
