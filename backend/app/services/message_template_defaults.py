from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import SessionLocal
from app.models.message import MessageTemplate, MessageTemplateVersion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DefaultMessageTemplate:
    template_id: uuid.UUID
    version_id: uuid.UUID
    idempotency_key: uuid.UUID
    system_key: str
    template_type: str
    name: str
    subject: str
    body: str
    variables: tuple[str, ...]


DEFAULT_MESSAGE_TEMPLATES = (
    DefaultMessageTemplate(
        uuid.UUID("20000000-0000-0000-0000-000000000001"),
        uuid.UUID("21000000-0000-0000-0000-000000000001"),
        uuid.UUID("22000000-0000-0000-0000-000000000001"),
        "default_interview_invitation",
        "interview_invitation",
        "面试通知",
        "{{candidate_name}} - {{job_title}} 面试通知",
        "{{candidate_name}}，您好：\n\n"
        "诚邀您参加 {{job_title}} 的 {{interview_round_name}}。\n"
        "面试时间：{{interview_start_time}}\n"
        "预计时长：{{interview_duration_minutes}} 分钟\n"
        "会议信息：{{meeting_info}}\n\n"
        "招聘专员：{{recruiter_name}}",
        (
            "candidate_name",
            "job_title",
            "interview_round_name",
            "interview_start_time",
            "interview_duration_minutes",
            "meeting_info",
            "recruiter_name",
        ),
    ),
    DefaultMessageTemplate(
        uuid.UUID("20000000-0000-0000-0000-000000000002"),
        uuid.UUID("21000000-0000-0000-0000-000000000002"),
        uuid.UUID("22000000-0000-0000-0000-000000000002"),
        "default_interview_reschedule",
        "interview_reschedule",
        "面试改期通知",
        "{{candidate_name}} - {{job_title}} 面试改期通知",
        "{{candidate_name}}，您好：\n\n"
        "{{job_title}} 的 {{interview_round_name}} 已调整至 {{interview_start_time}}。\n"
        "预计时长：{{interview_duration_minutes}} 分钟\n"
        "会议信息：{{meeting_info}}\n\n"
        "招聘专员：{{recruiter_name}}",
        (
            "candidate_name",
            "job_title",
            "interview_round_name",
            "interview_start_time",
            "interview_duration_minutes",
            "meeting_info",
            "recruiter_name",
        ),
    ),
    DefaultMessageTemplate(
        uuid.UUID("20000000-0000-0000-0000-000000000003"),
        uuid.UUID("21000000-0000-0000-0000-000000000003"),
        uuid.UUID("22000000-0000-0000-0000-000000000003"),
        "default_interview_cancellation",
        "interview_cancellation",
        "面试取消通知",
        "{{candidate_name}} - {{job_title}} 面试取消通知",
        "{{candidate_name}}，您好：\n\n"
        "原定的 {{job_title}} {{interview_round_name}} 已取消。\n"
        "如有后续安排，我们将再次与您联系。\n\n"
        "招聘专员：{{recruiter_name}}",
        ("candidate_name", "job_title", "interview_round_name", "recruiter_name"),
    ),
    DefaultMessageTemplate(
        uuid.UUID("20000000-0000-0000-0000-000000000004"),
        uuid.UUID("21000000-0000-0000-0000-000000000004"),
        uuid.UUID("22000000-0000-0000-0000-000000000004"),
        "default_meeting_details",
        "meeting_details",
        "腾讯会议信息",
        "{{candidate_name}} - {{job_title}} 腾讯会议信息",
        "{{candidate_name}}，您好：\n\n"
        "{{job_title}} 面试时间：{{interview_start_time}}\n"
        "腾讯会议信息：{{meeting_info}}\n\n"
        "招聘专员：{{recruiter_name}}",
        (
            "candidate_name",
            "job_title",
            "interview_start_time",
            "meeting_info",
            "recruiter_name",
        ),
    ),
    DefaultMessageTemplate(
        uuid.UUID("20000000-0000-0000-0000-000000000005"),
        uuid.UUID("21000000-0000-0000-0000-000000000005"),
        uuid.UUID("22000000-0000-0000-0000-000000000005"),
        "default_offer_notification",
        "offer_notification",
        "Offer 通知",
        "{{candidate_name}} - {{job_title}} Offer 通知",
        "{{candidate_name}}，您好：\n\n"
        "您的 {{job_title}} Offer 已准备完成，有效期至 {{offer_valid_until}}。\n"
        "请通过候选人专属入口查看并回应：{{offer_portal_link}}\n\n"
        "招聘专员：{{recruiter_name}}",
        (
            "candidate_name",
            "job_title",
            "offer_valid_until",
            "offer_portal_link",
            "recruiter_name",
        ),
    ),
    DefaultMessageTemplate(
        uuid.UUID("20000000-0000-0000-0000-000000000006"),
        uuid.UUID("21000000-0000-0000-0000-000000000006"),
        uuid.UUID("22000000-0000-0000-0000-000000000006"),
        "default_offer_reminder",
        "offer_reminder",
        "Offer 回应提醒",
        "{{candidate_name}} - {{job_title}} Offer 回应提醒",
        "{{candidate_name}}，您好：\n\n"
        "提醒您在 {{offer_valid_until}} 前查看并回应 {{job_title}} Offer。\n"
        "候选人专属入口：{{offer_portal_link}}\n\n"
        "招聘专员：{{recruiter_name}}",
        (
            "candidate_name",
            "job_title",
            "offer_valid_until",
            "offer_portal_link",
            "recruiter_name",
        ),
    ),
    DefaultMessageTemplate(
        uuid.UUID("20000000-0000-0000-0000-000000000007"),
        uuid.UUID("21000000-0000-0000-0000-000000000007"),
        uuid.UUID("22000000-0000-0000-0000-000000000007"),
        "default_onboarding_date_confirmation",
        "onboarding_date_confirmation",
        "入职日期确认",
        "{{candidate_name}} - {{job_title}} 入职日期确认",
        "{{candidate_name}}，您好：\n\n"
        "现与您确认 {{job_title}} 的入职日期为 {{onboarding_date}}。\n"
        "如日期需要调整，请及时与招聘专员沟通。\n\n"
        "招聘专员：{{recruiter_name}}",
        ("candidate_name", "job_title", "onboarding_date", "recruiter_name"),
    ),
)


def ensure_default_message_templates(
    session_factory: sessionmaker[Session] = SessionLocal,
) -> None:
    created_count = 0
    with session_factory() as db:
        for seed in DEFAULT_MESSAGE_TEMPLATES:
            if db.get(MessageTemplate, seed.template_id) is not None:
                continue
            try:
                with db.begin_nested():
                    template = MessageTemplate(
                        id=seed.template_id,
                        system_key=seed.system_key,
                        template_type=seed.template_type,
                        name=seed.name,
                        status="active",
                        current_version_number=1,
                        resource_version=1,
                        created_by_username="system",
                        created_by_display_name="系统",
                    )
                    template.versions.append(
                        MessageTemplateVersion(
                            id=seed.version_id,
                            version_number=1,
                            idempotency_key=seed.idempotency_key,
                            subject=seed.subject,
                            body=seed.body,
                            variables=list(seed.variables),
                            created_by_username="system",
                            created_by_display_name="系统",
                        )
                    )
                    db.add(template)
                    db.flush()
                    created_count += 1
            except IntegrityError:
                # Another API process may have inserted the deterministic seed first.
                continue
        db.commit()
    if created_count:
        logger.info("已初始化 %s 个沟通模板", created_count)
