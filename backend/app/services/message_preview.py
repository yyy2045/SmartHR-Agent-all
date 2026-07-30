from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    Job,
    JobApplication,
    MessageTemplate,
    MessageTemplateVersion,
    Offer,
    Onboarding,
    User,
)
from app.schemas.message import CommunicationPreviewRequest, CommunicationPreviewResponse
from app.services.onboarding import onboarding_reference_date

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PLACEHOLDER_PATTERN = re.compile(r"\{\{([a-z][a-z0-9_]{0,63})\}\}")
_OFFER_LINK_PLACEHOLDER = "[候选人专属链接已隐藏]"

_TEMPLATE_CONTEXTS = {
    "interview_invitation": "interview_round",
    "interview_reschedule": "interview_round",
    "interview_cancellation": "interview_round",
    "meeting_details": "interview_round",
    "offer_notification": "offer",
    "offer_reminder": "offer",
    "onboarding_date_confirmation": "onboarding",
}

_ALLOWED_VARIABLES = {
    "interview_invitation": frozenset(
        {
            "candidate_name",
            "job_title",
            "interview_round_name",
            "interview_start_time",
            "interview_duration_minutes",
            "meeting_info",
            "recruiter_name",
        }
    ),
    "interview_reschedule": frozenset(
        {
            "candidate_name",
            "job_title",
            "interview_round_name",
            "interview_start_time",
            "interview_duration_minutes",
            "meeting_info",
            "recruiter_name",
        }
    ),
    "interview_cancellation": frozenset(
        {
            "candidate_name",
            "job_title",
            "interview_round_name",
            "recruiter_name",
        }
    ),
    "meeting_details": frozenset(
        {
            "candidate_name",
            "job_title",
            "interview_start_time",
            "meeting_info",
            "recruiter_name",
        }
    ),
    "offer_notification": frozenset(
        {
            "candidate_name",
            "job_title",
            "offer_valid_until",
            "offer_portal_link",
            "recruiter_name",
        }
    ),
    "offer_reminder": frozenset(
        {
            "candidate_name",
            "job_title",
            "offer_valid_until",
            "offer_portal_link",
            "recruiter_name",
        }
    ),
    "onboarding_date_confirmation": frozenset(
        {"candidate_name", "job_title", "onboarding_date", "recruiter_name"}
    ),
}

_OPTIONAL_VARIABLES = {
    "interview_invitation": frozenset({"meeting_info"}),
    "interview_reschedule": frozenset({"meeting_info"}),
    "interview_cancellation": frozenset(),
    "meeting_details": frozenset(),
    "offer_notification": frozenset(),
    "offer_reminder": frozenset(),
    "onboarding_date_confirmation": frozenset(),
}


class MessagePreviewError(Exception):
    def __init__(self, detail: str | dict[str, Any], *, status_code: int) -> None:
        super().__init__(detail if isinstance(detail, str) else detail.get("message", ""))
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class PreviewContext:
    values: dict[str, str | None]


def _communication_scope_clause(user: User):
    if user.has_role("administrator"):
        return Job.id.is_not(None)
    clauses = []
    if user.has_role("recruiter"):
        clauses.append(Job.owner_id == user.id)
    if user.has_role("hiring_manager"):
        clauses.append(Job.hiring_manager_id == user.id)
    return or_(*clauses) if clauses else false()


def _ensure_preview_role(user: User) -> None:
    if user.has_role("administrator", "recruiter", "hiring_manager"):
        return
    raise MessagePreviewError("当前账号没有候选人文案预览权限", status_code=403)


def _format_date(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def _format_datetime(value: datetime) -> str:
    aware_value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    local_value = aware_value.astimezone(_SHANGHAI)
    return (
        f"{local_value.year}年{local_value.month}月{local_value.day}日 "
        f"{local_value:%H:%M}"
    )


def _base_values(application: JobApplication) -> dict[str, str | None]:
    return {
        "candidate_name": application.candidate.full_name,
        "job_title": application.job.title,
        "recruiter_name": application.job.owner.display_name,
    }


def _load_interview_context(
    db: Session,
    context_id: uuid.UUID,
    actor: User,
) -> tuple[CandidateInterviewRound, PreviewContext]:
    interview_round = db.scalar(
        select(CandidateInterviewRound)
        .join(
            CandidateInterviewSchedule,
            CandidateInterviewRound.schedule_id == CandidateInterviewSchedule.id,
        )
        .join(
            JobApplication,
            CandidateInterviewSchedule.application_id == JobApplication.id,
        )
        .join(Job, JobApplication.job_id == Job.id)
        .where(
            CandidateInterviewRound.id == context_id,
            _communication_scope_clause(actor),
        )
        .options(
            selectinload(CandidateInterviewRound.plan_round),
            selectinload(CandidateInterviewRound.schedule)
            .selectinload(CandidateInterviewSchedule.application)
            .selectinload(JobApplication.candidate),
            selectinload(CandidateInterviewRound.schedule)
            .selectinload(CandidateInterviewSchedule.application)
            .selectinload(JobApplication.job)
            .selectinload(Job.owner),
        )
    )
    if interview_round is None:
        raise MessagePreviewError("候选人面试轮次不存在", status_code=404)
    application = interview_round.schedule.application
    meeting_info = {
        "online": interview_round.meeting_url,
        "onsite": interview_round.location,
        "phone": None,
    }[interview_round.interview_method]
    values = {
        **_base_values(application),
        "interview_round_name": interview_round.plan_round.name,
        "interview_start_time": _format_datetime(interview_round.scheduled_start_at),
        "interview_duration_minutes": str(interview_round.plan_round.duration_minutes),
        "meeting_info": meeting_info,
    }
    return interview_round, PreviewContext(values=values)


def _load_offer_context(
    db: Session,
    context_id: uuid.UUID,
    actor: User,
) -> tuple[Offer, PreviewContext]:
    offer = db.scalar(
        select(Offer)
        .join(JobApplication, Offer.application_id == JobApplication.id)
        .join(Job, JobApplication.job_id == Job.id)
        .where(Offer.id == context_id, _communication_scope_clause(actor))
        .options(
            selectinload(Offer.application).selectinload(JobApplication.candidate),
            selectinload(Offer.application)
            .selectinload(JobApplication.job)
            .selectinload(Job.owner),
            selectinload(Offer.versions),
        )
    )
    if offer is None:
        raise MessagePreviewError("Offer 不存在", status_code=404)
    values = {
        **_base_values(offer.application),
        "offer_valid_until": _format_date(offer.current_version.valid_until),
        "offer_portal_link": _OFFER_LINK_PLACEHOLDER,
    }
    return offer, PreviewContext(values=values)


def _load_onboarding_context(
    db: Session,
    context_id: uuid.UUID,
    actor: User,
) -> tuple[Onboarding, PreviewContext]:
    onboarding = db.scalar(
        select(Onboarding)
        .join(JobApplication, Onboarding.application_id == JobApplication.id)
        .join(Job, JobApplication.job_id == Job.id)
        .where(Onboarding.id == context_id, _communication_scope_clause(actor))
        .options(
            selectinload(Onboarding.application).selectinload(JobApplication.candidate),
            selectinload(Onboarding.application)
            .selectinload(JobApplication.job)
            .selectinload(Job.owner),
            selectinload(Onboarding.offer).selectinload(Offer.versions),
        )
    )
    if onboarding is None:
        raise MessagePreviewError("入职记录不存在", status_code=404)
    values = {
        **_base_values(onboarding.application),
        "onboarding_date": _format_date(onboarding_reference_date(onboarding)),
    }
    return onboarding, PreviewContext(values=values)


def _load_template_version(
    db: Session,
    version_id: uuid.UUID,
) -> tuple[MessageTemplate, MessageTemplateVersion]:
    version = db.scalar(
        select(MessageTemplateVersion)
        .where(MessageTemplateVersion.id == version_id)
        .options(selectinload(MessageTemplateVersion.template))
    )
    if version is None:
        raise MessagePreviewError("沟通模板版本不存在", status_code=404)
    template = version.template
    if template.status != "active":
        raise MessagePreviewError("停用的沟通模板不能生成文案", status_code=409)
    return template, version


def _extract_variables(text: str) -> set[str]:
    variables = set(_PLACEHOLDER_PATTERN.findall(text))
    remainder = _PLACEHOLDER_PATTERN.sub("", text)
    if "{{" in remainder or "}}" in remainder:
        raise MessagePreviewError(
            "模板变量必须使用 {{variable_name}} 格式",
            status_code=422,
        )
    return variables


def _validate_template_content(
    *,
    template_type: str,
    subject: str,
    body: str,
    declared_variables: list[str] | None = None,
) -> set[str]:
    used_variables = _extract_variables(subject) | _extract_variables(body)
    allowed_variables = _ALLOWED_VARIABLES[template_type]
    unknown_variables = sorted(used_variables - allowed_variables)
    if unknown_variables:
        raise MessagePreviewError(
            {
                "code": "unknown_template_variables",
                "message": "模板包含当前类型不允许的变量",
                "variables": unknown_variables,
            },
            status_code=422,
        )
    declared_set = set(declared_variables or [])
    if declared_variables is not None and declared_set != used_variables:
        raise MessagePreviewError(
            {
                "code": "template_variable_declaration_mismatch",
                "message": "模板变量声明与文案占位符不一致",
                "undeclared_variables": sorted(used_variables - declared_set),
                "unused_variables": sorted(declared_set - used_variables),
            },
            status_code=422,
        )
    return used_variables


def _render_text(
    text: str,
    *,
    values: dict[str, str | None],
    missing_optional: set[str],
) -> str:
    lines = []
    for line in text.splitlines():
        line_variables = set(_PLACEHOLDER_PATTERN.findall(line))
        if line_variables & missing_optional:
            continue
        rendered_line = _PLACEHOLDER_PATTERN.sub(
            lambda match: values[match.group(1)] or "",
            line,
        )
        lines.append(rendered_line.rstrip())
    rendered = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", rendered)


def _validate_context_state(template_type: str, resource: object) -> None:
    if isinstance(resource, CandidateInterviewRound):
        if template_type == "interview_cancellation" and resource.status != "cancelled":
            raise MessagePreviewError("只能为已取消面试生成取消通知", status_code=409)
        if template_type == "interview_reschedule" and resource.status != "rescheduled":
            raise MessagePreviewError("只能为已改期面试生成改期通知", status_code=409)
        if template_type in {"interview_invitation", "meeting_details"} and (
            resource.status == "cancelled"
        ):
            raise MessagePreviewError("已取消面试不能生成该文案", status_code=409)
        return
    if isinstance(resource, Offer):
        if resource.status not in {"approved", "pending_response"}:
            raise MessagePreviewError("当前 Offer 状态不能生成候选人通知", status_code=409)
        return
    if isinstance(resource, Onboarding) and resource.status == "abandoned":
        raise MessagePreviewError("已放弃入职记录不能生成日期确认文案", status_code=409)


def preview_communication(
    db: Session,
    *,
    payload: CommunicationPreviewRequest,
    actor: User,
) -> CommunicationPreviewResponse:
    _ensure_preview_role(actor)
    template, version = _load_template_version(db, payload.template_version_id)
    expected_context_type = _TEMPLATE_CONTEXTS[template.template_type]
    if payload.context_type != expected_context_type:
        raise MessagePreviewError("模板类型与业务上下文不匹配", status_code=422)

    if payload.context_type == "interview_round":
        resource, context = _load_interview_context(db, payload.context_id, actor)
    elif payload.context_type == "offer":
        resource, context = _load_offer_context(db, payload.context_id, actor)
    else:
        resource, context = _load_onboarding_context(db, payload.context_id, actor)
    _validate_context_state(template.template_type, resource)

    _validate_template_content(
        template_type=template.template_type,
        declared_variables=version.variables,
        subject=version.subject,
        body=version.body,
    )
    subject = payload.subject_override or version.subject
    body = payload.body_override or version.body
    used_variables = _validate_template_content(
        template_type=template.template_type,
        subject=subject,
        body=body,
    )
    optional_variables = _OPTIONAL_VARIABLES[template.template_type]
    missing_required = sorted(
        variable
        for variable in used_variables - optional_variables
        if not context.values.get(variable)
    )
    if missing_required:
        raise MessagePreviewError(
            {
                "code": "missing_required_variables",
                "message": "生成文案所需业务信息不完整",
                "variables": missing_required,
            },
            status_code=422,
        )
    missing_optional = {
        variable
        for variable in used_variables & optional_variables
        if not context.values.get(variable)
    }
    resolved_variables = {
        variable: context.values.get(variable) or "" for variable in sorted(used_variables)
    }
    rendered_subject = _render_text(
        subject,
        values=context.values,
        missing_optional=missing_optional,
    )
    rendered_body = _render_text(
        body,
        values=context.values,
        missing_optional=missing_optional,
    )
    if not rendered_subject or not rendered_body:
        raise MessagePreviewError("渲染后的文案不能为空", status_code=422)
    return CommunicationPreviewResponse(
        template_id=template.id,
        template_version_id=version.id,
        template_type=template.template_type,  # type: ignore[arg-type]
        context_type=payload.context_type,
        context_id=payload.context_id,
        subject=rendered_subject,
        body=rendered_body,
        variables_used=sorted(used_variables),
        resolved_variables=resolved_variables,
        missing_optional_variables=sorted(missing_optional),
    )
