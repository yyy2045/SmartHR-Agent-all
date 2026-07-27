"""建立候选人主档案与职位应聘记录

Revision ID: 20260728_0018
Revises: 20260728_0017
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0018"
down_revision: str | None = "20260728_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("merged_into_candidate_id", sa.Uuid(), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'merged')", name="ck_candidates_status"),
        sa.ForeignKeyConstraint(
            ["merged_into_candidate_id"],
            ["candidates.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_candidates_status", "candidates", ["status"])
    op.create_index(
        "ix_candidates_merged_into_candidate_id",
        "candidates",
        ["merged_into_candidate_id"],
    )

    op.create_table(
        "job_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("merged_into_application_id", sa.Uuid(), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'merged')",
            name="ck_job_applications_status",
        ),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["merged_into_application_id"],
            ["job_applications.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_applications_candidate_id", "job_applications", ["candidate_id"])
    op.create_index("ix_job_applications_job_id", "job_applications", ["job_id"])
    op.create_index("ix_job_applications_status", "job_applications", ["status"])
    op.create_index(
        "ix_job_applications_merged_into_application_id",
        "job_applications",
        ["merged_into_application_id"],
    )
    op.create_index(
        "uq_job_applications_active_candidate_job",
        "job_applications",
        ["candidate_id", "job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.add_column("resume_documents", sa.Column("candidate_id", sa.Uuid(), nullable=True))
    op.add_column("resume_documents", sa.Column("application_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_resume_documents_candidate_id",
        "resume_documents",
        "candidates",
        ["candidate_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_resume_documents_application_id",
        "resume_documents",
        "job_applications",
        ["application_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_resume_documents_candidate_id", "resume_documents", ["candidate_id"])
    op.create_index("ix_resume_documents_application_id", "resume_documents", ["application_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO candidates (
                id, full_name, phone, email, status, created_at, updated_at
            )
            SELECT
                rd.id,
                (
                    SELECT rr.original_text
                    FROM resume_redactions rr
                    JOIN resume_text_segments rts ON rts.id = rr.segment_id
                    WHERE rts.document_id = rd.id AND rr.entity_type = 'name'
                    ORDER BY rts.sort_order, rr.start_offset
                    LIMIT 1
                ),
                (
                    SELECT rr.original_text
                    FROM resume_redactions rr
                    JOIN resume_text_segments rts ON rts.id = rr.segment_id
                    WHERE rts.document_id = rd.id
                      AND rr.entity_type = 'phone'
                      AND (
                          regexp_replace(rr.original_text, '[^0-9]', '', 'g')
                              ~ '^1[3-9][0-9]{9}$'
                          OR (
                              left(trim(rr.original_text), 1) = '+'
                              AND length(regexp_replace(rr.original_text, '[^0-9]', '', 'g'))
                                  BETWEEN 8 AND 15
                          )
                          OR trim(rr.original_text) ~ '^0[0-9]{2,3}[- ][0-9]{7,8}$'
                      )
                    ORDER BY
                        CASE WHEN regexp_replace(rr.original_text, '[^0-9]', '', 'g')
                            ~ '^1[3-9][0-9]{9}$' THEN 0 ELSE 1 END,
                        rts.sort_order,
                        rr.start_offset
                    LIMIT 1
                ),
                (
                    SELECT lower(rr.original_text)
                    FROM resume_redactions rr
                    JOIN resume_text_segments rts ON rts.id = rr.segment_id
                    WHERE rts.document_id = rd.id AND rr.entity_type = 'email'
                    ORDER BY rts.sort_order, rr.start_offset
                    LIMIT 1
                ),
                'active',
                rd.created_at,
                rd.updated_at
            FROM resume_documents rd
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO job_applications (
                id, candidate_id, job_id, status, created_at, updated_at
            )
            SELECT
                CAST(md5(rd.id::text || '-job-application') AS uuid),
                rd.id,
                sb.job_id,
                'active',
                rd.created_at,
                rd.updated_at
            FROM resume_documents rd
            JOIN screening_batches sb ON sb.id = rd.batch_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE resume_documents
            SET
                candidate_id = id,
                application_id = CAST(md5(id::text || '-job-application') AS uuid)
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_resume_documents_application_id", table_name="resume_documents")
    op.drop_index("ix_resume_documents_candidate_id", table_name="resume_documents")
    op.drop_constraint(
        "fk_resume_documents_application_id", "resume_documents", type_="foreignkey"
    )
    op.drop_constraint("fk_resume_documents_candidate_id", "resume_documents", type_="foreignkey")
    op.drop_column("resume_documents", "application_id")
    op.drop_column("resume_documents", "candidate_id")
    op.drop_index("uq_job_applications_active_candidate_job", table_name="job_applications")
    op.drop_index(
        "ix_job_applications_merged_into_application_id", table_name="job_applications"
    )
    op.drop_index("ix_job_applications_status", table_name="job_applications")
    op.drop_index("ix_job_applications_job_id", table_name="job_applications")
    op.drop_index("ix_job_applications_candidate_id", table_name="job_applications")
    op.drop_table("job_applications")
    op.drop_index("ix_candidates_merged_into_candidate_id", table_name="candidates")
    op.drop_index("ix_candidates_status", table_name="candidates")
    op.drop_table("candidates")
