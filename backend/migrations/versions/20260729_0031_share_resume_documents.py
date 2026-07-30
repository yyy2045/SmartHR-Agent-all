"""Share resume documents across job applications.

Revision ID: 20260729_0031
Revises: 20260729_0030
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0031"
down_revision: str | None = "20260729_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "resume_documents_batch_id_fkey",
        "resume_documents",
        type_="foreignkey",
    )
    op.alter_column("resume_documents", "batch_id", nullable=True)
    op.create_foreign_key(
        "fk_resume_documents_batch_id",
        "resume_documents",
        "screening_batches",
        ["batch_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "application_resume_documents",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["job_applications.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["resume_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("application_id", "document_id"),
    )
    op.create_index(
        "ix_application_resume_documents_document_id",
        "application_resume_documents",
        ["document_id"],
    )

    op.add_column(
        "job_applications",
        sa.Column("primary_document_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_job_applications_primary_document_id",
        "job_applications",
        ["primary_document_id"],
    )
    op.create_foreign_key(
        "fk_job_applications_primary_document_id",
        "job_applications",
        "resume_documents",
        ["primary_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        sa.text(
            """
            INSERT INTO application_resume_documents (
                application_id,
                document_id,
                created_at
            )
            SELECT
                rd.application_id,
                rd.id,
                rd.created_at
            FROM resume_documents rd
            WHERE rd.application_id IS NOT NULL
            ON CONFLICT (application_id, document_id) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE job_applications AS application
            SET primary_document_id = latest.document_id
            FROM (
                SELECT DISTINCT ON (rd.application_id)
                    rd.application_id,
                    rd.id AS document_id
                FROM resume_documents rd
                WHERE rd.application_id IS NOT NULL
                ORDER BY rd.application_id, rd.created_at DESC, rd.id DESC
            ) AS latest
            WHERE application.id = latest.application_id
              AND application.primary_document_id IS NULL
            """
        )
    )
    op.create_foreign_key(
        "fk_job_applications_primary_document_link",
        "job_applications",
        "application_resume_documents",
        ["id", "primary_document_id"],
        ["application_id", "document_id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    orphaned_documents = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM resume_documents WHERE batch_id IS NULL")
    )
    if orphaned_documents:
        raise RuntimeError(
            "Cannot downgrade shared resume migration while resume documents "
            "without a source batch exist."
        )

    op.drop_constraint(
        "fk_job_applications_primary_document_link",
        "job_applications",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_job_applications_primary_document_id",
        "job_applications",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_job_applications_primary_document_id",
        table_name="job_applications",
    )
    op.drop_column("job_applications", "primary_document_id")

    op.drop_index(
        "ix_application_resume_documents_document_id",
        table_name="application_resume_documents",
    )
    op.drop_table("application_resume_documents")

    op.drop_constraint(
        "fk_resume_documents_batch_id",
        "resume_documents",
        type_="foreignkey",
    )
    op.alter_column("resume_documents", "batch_id", nullable=False)
    op.create_foreign_key(
        "resume_documents_batch_id_fkey",
        "resume_documents",
        "screening_batches",
        ["batch_id"],
        ["id"],
        ondelete="CASCADE",
    )
