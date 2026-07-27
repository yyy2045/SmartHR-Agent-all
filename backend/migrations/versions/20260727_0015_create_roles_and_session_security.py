"""创建固定角色与会话安全基础

Revision ID: 20260727_0015
Revises: 20260726_0014
Create Date: 2026-07-27
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0015"
down_revision: str | None = "20260726_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_IDS = {
    "administrator": uuid.UUID("10000000-0000-0000-0000-000000000001"),
    "recruiter": uuid.UUID("10000000-0000-0000-0000-000000000002"),
    "hiring_manager": uuid.UUID("10000000-0000-0000-0000-000000000003"),
    "approver": uuid.UUID("10000000-0000-0000-0000-000000000004"),
}


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("session_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_check_constraint("ck_users_session_version", "users", "session_version >= 1")

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_roles_key"), "roles", ["key"], unique=True)

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )
    op.create_index(
        op.f("ix_user_roles_assigned_by_id"),
        "user_roles",
        ["assigned_by_id"],
        unique=False,
    )

    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("display_name", sa.String()),
    )
    op.bulk_insert(
        roles_table,
        [
            {
                "id": ROLE_IDS["administrator"],
                "key": "administrator",
                "display_name": "企业管理员",
            },
            {
                "id": ROLE_IDS["recruiter"],
                "key": "recruiter",
                "display_name": "招聘专员",
            },
            {
                "id": ROLE_IDS["hiring_manager"],
                "key": "hiring_manager",
                "display_name": "用人经理",
            },
            {
                "id": ROLE_IDS["approver"],
                "key": "approver",
                "display_name": "审批人",
            },
        ],
    )
    connection = op.get_bind()
    for key in ("administrator", "recruiter"):
        connection.execute(
            sa.text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT id, :role_id FROM users"
            ),
            {"role_id": ROLE_IDS[key]},
        )

    op.add_column("jobs", sa.Column("hiring_manager_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_jobs_hiring_manager_id_users",
        "jobs",
        "users",
        ["hiring_manager_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_jobs_hiring_manager_id"),
        "jobs",
        ["hiring_manager_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_jobs_hiring_manager_id"), table_name="jobs")
    op.drop_constraint("fk_jobs_hiring_manager_id_users", "jobs", type_="foreignkey")
    op.drop_column("jobs", "hiring_manager_id")
    op.drop_index(op.f("ix_user_roles_assigned_by_id"), table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index(op.f("ix_roles_key"), table_name="roles")
    op.drop_table("roles")
    op.drop_constraint("ck_users_session_version", "users", type_="check")
    op.drop_column("users", "session_version")
    op.drop_column("users", "must_change_password")
