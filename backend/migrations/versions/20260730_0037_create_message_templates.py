"""Create versioned communication templates.

Revision ID: 20260730_0037
Revises: 20260730_0036
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0037"
down_revision: str | None = "20260730_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SEEDS = (
    (
        "interview_invitation",
        "面试通知",
        "{{candidate_name}} - {{job_title}} 面试通知",
        "{{candidate_name}}，您好：\n\n诚邀您参加 {{job_title}} 的 {{interview_round_name}}。\n"
        "面试时间：{{interview_start_time}}\n预计时长：{{interview_duration_minutes}} 分钟\n"
        "会议信息：{{meeting_info}}\n\n招聘专员：{{recruiter_name}}",
        [
            "candidate_name",
            "job_title",
            "interview_round_name",
            "interview_start_time",
            "interview_duration_minutes",
            "meeting_info",
            "recruiter_name",
        ],
    ),
    (
        "interview_reschedule",
        "面试改期通知",
        "{{candidate_name}} - {{job_title}} 面试改期通知",
        "{{candidate_name}}，您好：\n\n{{job_title}} 的 {{interview_round_name}} 已调整至 "
        "{{interview_start_time}}。\n预计时长：{{interview_duration_minutes}} 分钟\n"
        "会议信息：{{meeting_info}}\n\n招聘专员：{{recruiter_name}}",
        [
            "candidate_name",
            "job_title",
            "interview_round_name",
            "interview_start_time",
            "interview_duration_minutes",
            "meeting_info",
            "recruiter_name",
        ],
    ),
    (
        "interview_cancellation",
        "面试取消通知",
        "{{candidate_name}} - {{job_title}} 面试取消通知",
        "{{candidate_name}}，您好：\n\n原定的 {{job_title}} {{interview_round_name}} 已取消。\n"
        "如有后续安排，我们将再次与您联系。\n\n招聘专员：{{recruiter_name}}",
        ["candidate_name", "job_title", "interview_round_name", "recruiter_name"],
    ),
    (
        "meeting_details",
        "腾讯会议信息",
        "{{candidate_name}} - {{job_title}} 腾讯会议信息",
        "{{candidate_name}}，您好：\n\n{{job_title}} 面试时间：{{interview_start_time}}\n"
        "腾讯会议信息：{{meeting_info}}\n\n招聘专员：{{recruiter_name}}",
        [
            "candidate_name",
            "job_title",
            "interview_start_time",
            "meeting_info",
            "recruiter_name",
        ],
    ),
    (
        "offer_notification",
        "Offer 通知",
        "{{candidate_name}} - {{job_title}} Offer 通知",
        "{{candidate_name}}，您好：\n\n您的 {{job_title}} Offer 已准备完成，有效期至 "
        "{{offer_valid_until}}。\n请通过候选人专属入口查看并回应：{{offer_portal_link}}\n\n"
        "招聘专员：{{recruiter_name}}",
        [
            "candidate_name",
            "job_title",
            "offer_valid_until",
            "offer_portal_link",
            "recruiter_name",
        ],
    ),
    (
        "offer_reminder",
        "Offer 回应提醒",
        "{{candidate_name}} - {{job_title}} Offer 回应提醒",
        "{{candidate_name}}，您好：\n\n提醒您在 {{offer_valid_until}} 前查看并回应 "
        "{{job_title}} Offer。\n候选人专属入口：{{offer_portal_link}}\n\n"
        "招聘专员：{{recruiter_name}}",
        [
            "candidate_name",
            "job_title",
            "offer_valid_until",
            "offer_portal_link",
            "recruiter_name",
        ],
    ),
    (
        "onboarding_date_confirmation",
        "入职日期确认",
        "{{candidate_name}} - {{job_title}} 入职日期确认",
        "{{candidate_name}}，您好：\n\n现与您确认 {{job_title}} 的入职日期为 "
        "{{onboarding_date}}。\n如日期需要调整，请及时与招聘专员沟通。\n\n"
        "招聘专员：{{recruiter_name}}",
        ["candidate_name", "job_title", "onboarding_date", "recruiter_name"],
    ),
)


def upgrade() -> None:
    op.create_table(
        "message_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("system_key", sa.String(length=60), nullable=True),
        sa.Column("template_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("current_version_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("resource_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "template_type IN ("
            "'interview_invitation', 'interview_reschedule', "
            "'interview_cancellation', 'meeting_details', "
            "'offer_notification', 'offer_reminder', "
            "'onboarding_date_confirmation')",
            name="ck_message_templates_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name="ck_message_templates_status"
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0", name="ck_message_templates_name_not_blank"
        ),
        sa.CheckConstraint(
            "current_version_number >= 1", name="ck_message_templates_current_version"
        ),
        sa.CheckConstraint(
            "resource_version >= 1", name="ck_message_templates_resource_version"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("system_key", name="uq_message_templates_system_key"),
    )
    op.create_index(
        "ix_message_templates_created_by_id", "message_templates", ["created_by_id"]
    )
    op.create_index(
        "ix_message_templates_status", "message_templates", ["status"]
    )
    op.create_index(
        "ix_message_templates_template_type", "message_templates", ["template_type"]
    )
    op.create_index(
        "uq_message_templates_active_name_ci",
        "message_templates",
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "message_template_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_message_template_versions_number"
        ),
        sa.CheckConstraint(
            "length(trim(subject)) BETWEEN 1 AND 100",
            name="ck_message_template_versions_subject_length",
        ),
        sa.CheckConstraint(
            "length(trim(body)) BETWEEN 1 AND 5000",
            name="ck_message_template_versions_body_length",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["message_template_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["message_templates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "idempotency_key",
            name="uq_message_template_versions_idempotency",
        ),
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_message_template_versions_number",
        ),
    )
    op.create_index(
        "ix_message_template_versions_created_by_id",
        "message_template_versions",
        ["created_by_id"],
    )
    op.create_index(
        "ix_message_template_versions_source_version_id",
        "message_template_versions",
        ["source_version_id"],
    )
    op.create_index(
        "ix_message_template_versions_template_id",
        "message_template_versions",
        ["template_id"],
    )

    templates_table = sa.table(
        "message_templates",
        sa.column("id", sa.Uuid()),
        sa.column("system_key", sa.String()),
        sa.column("template_type", sa.String()),
        sa.column("name", sa.String()),
        sa.column("status", sa.String()),
        sa.column("current_version_number", sa.Integer()),
        sa.column("resource_version", sa.Integer()),
        sa.column("created_by_username", sa.String()),
        sa.column("created_by_display_name", sa.String()),
    )
    versions_table = sa.table(
        "message_template_versions",
        sa.column("id", sa.Uuid()),
        sa.column("template_id", sa.Uuid()),
        sa.column("version_number", sa.Integer()),
        sa.column("idempotency_key", sa.Uuid()),
        sa.column("subject", sa.String()),
        sa.column("body", sa.Text()),
        sa.column("variables", sa.JSON()),
        sa.column("created_by_username", sa.String()),
        sa.column("created_by_display_name", sa.String()),
    )
    op.bulk_insert(
        templates_table,
        [
            {
                "id": uuid.UUID(f"20000000-0000-0000-0000-{index:012d}"),
                "system_key": f"default_{template_type}",
                "template_type": template_type,
                "name": name,
                "status": "active",
                "current_version_number": 1,
                "resource_version": 1,
                "created_by_username": "system",
                "created_by_display_name": "系统",
            }
            for index, (template_type, name, _subject, _body, _variables) in enumerate(
                SEEDS, start=1
            )
        ],
    )
    op.bulk_insert(
        versions_table,
        [
            {
                "id": uuid.UUID(f"21000000-0000-0000-0000-{index:012d}"),
                "template_id": uuid.UUID(f"20000000-0000-0000-0000-{index:012d}"),
                "version_number": 1,
                "idempotency_key": uuid.UUID(
                    f"22000000-0000-0000-0000-{index:012d}"
                ),
                "subject": subject,
                "body": body,
                "variables": variables,
                "created_by_username": "system",
                "created_by_display_name": "系统",
            }
            for index, (_template_type, _name, subject, body, variables) in enumerate(
                SEEDS, start=1
            )
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_message_template_versions_template_id", table_name="message_template_versions"
    )
    op.drop_index(
        "ix_message_template_versions_source_version_id",
        table_name="message_template_versions",
    )
    op.drop_index(
        "ix_message_template_versions_created_by_id",
        table_name="message_template_versions",
    )
    op.drop_table("message_template_versions")
    op.drop_index("uq_message_templates_active_name_ci", table_name="message_templates")
    op.drop_index("ix_message_templates_template_type", table_name="message_templates")
    op.drop_index("ix_message_templates_status", table_name="message_templates")
    op.drop_index("ix_message_templates_created_by_id", table_name="message_templates")
    op.drop_table("message_templates")
