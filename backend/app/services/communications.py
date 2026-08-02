from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AuditLog,
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    CommunicationRecord,
    Job,
    JobApplication,
    MessageTemplateVersion,
    Offer,
    Onboarding,
    User,
)
from app.schemas.message import (
    CommunicationCopyAuditRequest,
    CommunicationCopyAuditResponse,
    CommunicationCorrectionCreateRequest,
    CommunicationRecordCreateRequest,
    CommunicationRecordDetailResponse,
    CommunicationRecordListResponse,
    CommunicationRecordResponse,
    CommunicationRecordSummaryResponse,
)
from app.services.audit import record_audit
from app.services.message_preview import TEMPLATE_CONTEXTS

_OFFER_PORTAL_TOKEN_PATTERN = re.compile(r"/portal/offers/[A-Za-z0-9_-]{16,}")


class CommunicationServiceError(Exception):
    def __init__(self, detail: str | dict[str, Any], *, status_code: int) -> None:
        super().__init__(detail if isinstance(detail, str) else detail.get("message", ""))
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class CommunicationContext:
    application: JobApplication
    template_type: str | None = None


def _fingerprint(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scope_clause(actor: User):
    if actor.has_role("administrator"):
        return Job.id.is_not(None)
    clauses = []
    if actor.has_role("recruiter"):
        clauses.append(Job.owner_id == actor.id)
    if actor.has_role("hiring_manager"):
        clauses.append(Job.hiring_manager_id == actor.id)
    return or_(*clauses) if clauses else false()


def _ensure_read_role(actor: User) -> None:
    if actor.has_role("administrator", "recruiter", "hiring_manager"):
        return
    raise CommunicationServiceError("当前账号没有候选人沟通访问权限", status_code=403)


def _ensure_write_allowed(application: JobApplication, actor: User) -> None:
    if actor.has_role("administrator") or application.job.owner_id == actor.id:
        return
    if actor.has_role("hiring_manager"):
        raise CommunicationServiceError("用人经理只能查看和复制沟通文案", status_code=403)
    raise CommunicationServiceError("当前账号没有登记候选人沟通权限", status_code=403)


def _load_context(
    db: Session,
    *,
    context_type: str,
    context_id: uuid.UUID,
    actor: User,
    for_update: bool = False,
) -> CommunicationContext:
    _ensure_read_role(actor)
    if context_type == "interview_round":
        statement = (
            select(CandidateInterviewRound)
            .join(
                CandidateInterviewSchedule,
                CandidateInterviewRound.schedule_id == CandidateInterviewSchedule.id,
            )
            .join(JobApplication, CandidateInterviewSchedule.application_id == JobApplication.id)
            .join(Job, JobApplication.job_id == Job.id)
            .where(CandidateInterviewRound.id == context_id, _scope_clause(actor))
            .options(
                selectinload(CandidateInterviewRound.schedule)
                .selectinload(CandidateInterviewSchedule.application)
                .selectinload(JobApplication.candidate),
                selectinload(CandidateInterviewRound.schedule)
                .selectinload(CandidateInterviewSchedule.application)
                .selectinload(JobApplication.job),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        interview_round = db.scalar(statement)
        if interview_round is None:
            raise CommunicationServiceError("候选人面试轮次不存在", status_code=404)
        return CommunicationContext(application=interview_round.schedule.application)
    if context_type == "offer":
        statement = (
            select(Offer)
            .join(JobApplication, Offer.application_id == JobApplication.id)
            .join(Job, JobApplication.job_id == Job.id)
            .where(Offer.id == context_id, _scope_clause(actor))
            .options(
                selectinload(Offer.application).selectinload(JobApplication.candidate),
                selectinload(Offer.application).selectinload(JobApplication.job),
                selectinload(Offer.versions),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        offer = db.scalar(statement)
        if offer is None:
            raise CommunicationServiceError("Offer 不存在", status_code=404)
        return CommunicationContext(application=offer.application)
    if context_type == "onboarding":
        statement = (
            select(Onboarding)
            .join(JobApplication, Onboarding.application_id == JobApplication.id)
            .join(Job, JobApplication.job_id == Job.id)
            .where(Onboarding.id == context_id, _scope_clause(actor))
            .options(
                selectinload(Onboarding.application).selectinload(JobApplication.candidate),
                selectinload(Onboarding.application).selectinload(JobApplication.job),
                selectinload(Onboarding.offer).selectinload(Offer.versions),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        onboarding = db.scalar(statement)
        if onboarding is None:
            raise CommunicationServiceError("入职记录不存在", status_code=404)
        return CommunicationContext(application=onboarding.application)
    raise CommunicationServiceError("不支持的候选人沟通上下文", status_code=422)


def _load_template_version(
    db: Session,
    *,
    version_id: uuid.UUID,
    context_type: str,
    require_active: bool,
) -> MessageTemplateVersion:
    version = db.scalar(
        select(MessageTemplateVersion)
        .where(MessageTemplateVersion.id == version_id)
        .options(selectinload(MessageTemplateVersion.template))
    )
    if version is None:
        raise CommunicationServiceError("沟通模板版本不存在", status_code=404)
    template = version.template
    if require_active and template.status != "active":
        raise CommunicationServiceError("停用模板不能用于实时发送记录", status_code=409)
    if TEMPLATE_CONTEXTS[template.template_type] != context_type:
        raise CommunicationServiceError("模板类型与业务上下文不匹配", status_code=422)
    return version


def _recipient_for_channel(application: JobApplication, channel: str) -> tuple[str, str]:
    candidate = application.candidate
    if channel in {"wechat", "phone", "sms"}:
        digits = "".join(ch for ch in (candidate.phone or "") if ch.isdigit())
        if not digits:
            raise CommunicationServiceError("候选人缺少手机号，不能登记该渠道沟通", status_code=422)
        masked = f"{digits[:3]}****{digits[-4:]}" if len(digits) >= 7 else f"****{digits[-4:]}"
        return "phone", masked
    if channel == "email":
        email = (candidate.email or "").strip()
        if not email:
            raise CommunicationServiceError("候选人缺少邮箱，不能登记邮件沟通", status_code=422)
        local, _, domain = email.partition("@")
        if not local or not domain:
            raise CommunicationServiceError(
                "候选人邮箱格式不完整，不能登记邮件沟通",
                status_code=422,
            )
        return "email", f"{local[:1]}***@{domain}"
    return "other", "外部渠道"


def _validate_channel(channel: str, channel_detail: str | None) -> None:
    if channel == "other" and not channel_detail:
        raise CommunicationServiceError("其他渠道必须填写渠道说明", status_code=422)
    if channel != "other" and channel_detail is not None:
        raise CommunicationServiceError("非其他渠道不能填写渠道说明", status_code=422)


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _validate_sent_at(value: datetime) -> None:
    if _as_aware(value) > datetime.now(UTC):
        raise CommunicationServiceError("沟通发送时间不能晚于当前时间", status_code=422)


def _decimal_tokens(value: Decimal | None) -> set[str]:
    if value is None:
        return set()
    normalized = value.normalize()
    tokens = {format(value, "f"), format(normalized, "f")}
    if value == value.to_integral_value():
        tokens.add(str(int(value)))
    return {item for item in tokens if item and item != "0"}


def _validate_safe_snapshot(application: JobApplication, *, subject: str, body: str) -> None:
    text = f"{subject}\n{body}"
    if _OFFER_PORTAL_TOKEN_PATTERN.search(text):
        raise CommunicationServiceError("沟通安全快照不能保存 Offer 原始链接", status_code=422)
    candidate = application.candidate
    phone = (candidate.phone or "").strip()
    if phone and phone in text:
        raise CommunicationServiceError("沟通安全快照不能保存完整手机号", status_code=422)
    email = (candidate.email or "").strip()
    if email and email.lower() in text.lower():
        raise CommunicationServiceError("沟通安全快照不能保存完整邮箱", status_code=422)
    offer = application.offer
    if offer is None:
        return
    current_version = offer.current_version
    salary_tokens = set()
    salary_tokens.update(_decimal_tokens(current_version.monthly_salary))
    salary_tokens.update(_decimal_tokens(current_version.probation_monthly_salary))
    if any(token in text for token in salary_tokens):
        raise CommunicationServiceError("沟通安全快照不能保存薪酬明细", status_code=422)


def _load_visible_record(
    db: Session,
    record_id: uuid.UUID,
    actor: User,
    *,
    for_update: bool = False,
) -> CommunicationRecord:
    _ensure_read_role(actor)
    statement = (
        select(CommunicationRecord)
        .join(JobApplication, CommunicationRecord.application_id == JobApplication.id)
        .join(Job, JobApplication.job_id == Job.id)
        .where(CommunicationRecord.id == record_id, _scope_clause(actor))
        .options(
            selectinload(CommunicationRecord.application).selectinload(JobApplication.job),
            selectinload(CommunicationRecord.application).selectinload(JobApplication.candidate),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    record = db.scalar(statement)
    if record is None:
        raise CommunicationServiceError("候选人沟通记录不存在", status_code=404)
    return record


def _find_record_by_key(db: Session, idempotency_key: uuid.UUID) -> CommunicationRecord | None:
    return db.scalar(
        select(CommunicationRecord)
        .where(CommunicationRecord.idempotency_key == idempotency_key)
        .options(
            selectinload(CommunicationRecord.application).selectinload(JobApplication.job),
            selectinload(CommunicationRecord.application).selectinload(JobApplication.candidate),
        )
    )


def _check_record_replay(
    db: Session,
    *,
    idempotency_key: uuid.UUID,
    fingerprint: str,
    actor: User,
) -> CommunicationRecord | None:
    existing = _find_record_by_key(db, idempotency_key)
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise CommunicationServiceError("幂等键已被不同请求使用", status_code=409)
    _ensure_record_visible(existing, actor)
    return existing


def _ensure_record_visible(record: CommunicationRecord, actor: User) -> None:
    _ensure_read_role(actor)
    job = record.application.job
    if actor.has_role("administrator"):
        return
    if actor.has_role("recruiter") and job.owner_id == actor.id:
        return
    if actor.has_role("hiring_manager") and job.hiring_manager_id == actor.id:
        return
    raise CommunicationServiceError("候选人沟通记录不存在", status_code=404)


def _find_copy_audit(
    db: Session,
    *,
    context_type: str,
    context_id: uuid.UUID,
    idempotency_key: uuid.UUID,
) -> AuditLog | None:
    logs = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.action == "communication.copied",
            AuditLog.target_type == "communication",
            AuditLog.target_id == context_id,
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    ).all()
    expected_key = str(idempotency_key)
    return next(
        (
            log
            for log in logs
            if isinstance(log.details, dict)
            and log.details.get("context_type") == context_type
            and log.details.get("idempotency_key") == expected_key
        ),
        None,
    )


def _record_response(record: CommunicationRecord, actor: User) -> CommunicationRecordResponse:
    return CommunicationRecordResponse(
        id=record.id,
        application_id=record.application_id,
        candidate_id=record.candidate_id,
        job_id=record.application.job_id,
        context_type=record.context_type,  # type: ignore[arg-type]
        context_id=record.context_id,
        template_version_id=record.template_version_id,
        record_kind=record.record_kind,  # type: ignore[arg-type]
        root_record_id=record.root_record_id,
        corrects_record_id=record.corrects_record_id,
        correction_sequence=record.correction_sequence,
        correction_reason=record.correction_reason,
        channel=record.channel,  # type: ignore[arg-type]
        channel_detail=record.channel_detail,
        recipient_type=record.recipient_type,  # type: ignore[arg-type]
        recipient_masked=record.recipient_masked,
        candidate_name_snapshot=record.candidate_name_snapshot,
        subject_snapshot=record.subject_snapshot,
        body_snapshot=record.body_snapshot,
        sent_at=record.sent_at,
        is_historical=record.is_historical,
        historical_note=record.historical_note,
        created_by_id=record.created_by_id,
        created_by_username=record.created_by_username_snapshot,
        created_by_display_name=record.created_by_display_name_snapshot,
        created_at=record.created_at,
        allowed_actions=_allowed_record_actions(record, actor),
    )


def _allowed_record_actions(record: CommunicationRecord, actor: User) -> list[str]:
    actions = ["copy"]
    if actor.has_role("administrator") or record.application.job.owner_id == actor.id:
        actions.append("correct")
    return actions


def _summary_response(
    record: CommunicationRecord,
    *,
    actor: User,
    correction_count: int,
    latest_correction_id: uuid.UUID | None,
) -> CommunicationRecordSummaryResponse:
    return CommunicationRecordSummaryResponse(
        id=record.id,
        application_id=record.application_id,
        candidate_id=record.candidate_id,
        job_id=record.application.job_id,
        context_type=record.context_type,  # type: ignore[arg-type]
        context_id=record.context_id,
        record_kind=record.record_kind,  # type: ignore[arg-type]
        channel=record.channel,  # type: ignore[arg-type]
        channel_detail=record.channel_detail,
        recipient_masked=record.recipient_masked,
        candidate_name_snapshot=record.candidate_name_snapshot,
        subject_snapshot=record.subject_snapshot,
        sent_at=record.sent_at,
        correction_count=correction_count,
        latest_correction_id=latest_correction_id,
        allowed_actions=_allowed_record_actions(record, actor),
    )


def create_communication_record(
    db: Session,
    *,
    payload: CommunicationRecordCreateRequest,
    actor: User,
) -> CommunicationRecordResponse:
    context = _load_context(
        db,
        context_type=payload.context_type,
        context_id=payload.context_id,
        actor=actor,
        for_update=True,
    )
    _ensure_write_allowed(context.application, actor)
    _validate_channel(payload.channel, payload.channel_detail)
    _validate_sent_at(payload.sent_at)
    if payload.is_historical and not payload.historical_note:
        raise CommunicationServiceError("历史补录必须填写说明", status_code=422)
    if not payload.is_historical and payload.template_version_id is None:
        raise CommunicationServiceError("实时发送记录必须关联启用模板版本", status_code=422)
    if payload.template_version_id is not None:
        _load_template_version(
            db,
            version_id=payload.template_version_id,
            context_type=payload.context_type,
            require_active=not payload.is_historical,
        )
    _validate_safe_snapshot(context.application, subject=payload.subject, body=payload.body)
    recipient_type, recipient_masked = _recipient_for_channel(context.application, payload.channel)
    request_fingerprint = _fingerprint(
        {
            "action": "sent",
            "context_type": payload.context_type,
            "context_id": str(payload.context_id),
            "template_version_id": str(payload.template_version_id),
            "channel": payload.channel,
            "channel_detail": payload.channel_detail,
            "subject_hash": _content_hash(payload.subject),
            "body_hash": _content_hash(payload.body),
            "sent_at": _as_aware(payload.sent_at).isoformat(),
            "is_historical": payload.is_historical,
            "historical_note_hash": _content_hash(payload.historical_note or ""),
        }
    )
    replay = _check_record_replay(
        db,
        idempotency_key=payload.idempotency_key,
        fingerprint=request_fingerprint,
        actor=actor,
    )
    if replay is not None:
        return _record_response(replay, actor)
    record = CommunicationRecord(
        application_id=context.application.id,
        candidate_id=context.application.candidate_id,
        context_type=payload.context_type,
        context_id=payload.context_id,
        template_version_id=payload.template_version_id,
        record_kind="sent",
        correction_sequence=0,
        channel=payload.channel,
        channel_detail=payload.channel_detail,
        recipient_type=recipient_type,
        recipient_masked=recipient_masked,
        candidate_name_snapshot=(
            context.application.candidate.full_name
            or context.application.candidate.candidate_code
        ),
        subject_snapshot=payload.subject,
        body_snapshot=payload.body,
        sent_at=_as_aware(payload.sent_at),
        is_historical=payload.is_historical,
        historical_note=payload.historical_note,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=request_fingerprint,
        created_by_id=actor.id,
        created_by_username_snapshot=actor.username,
        created_by_display_name_snapshot=actor.display_name,
    )
    db.add(record)
    db.flush()
    record_audit(
        db,
        action="communication.sent_recorded",
        target_type="communication",
        target_id=record.id,
        job_id=context.application.job_id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(payload.idempotency_key),
            "fingerprint": request_fingerprint,
            "context_type": payload.context_type,
            "context_id": str(payload.context_id),
            "application_id": str(context.application.id),
            "candidate_id": str(context.application.candidate_id),
            "channel": payload.channel,
            "recipient_masked": recipient_masked,
            "subject_sha256": _content_hash(payload.subject),
            "body_sha256": _content_hash(payload.body),
            "is_historical": payload.is_historical,
        },
    )
    db.commit()
    db.refresh(record)
    return _record_response(record, actor)


def create_correction(
    db: Session,
    *,
    record_id: uuid.UUID,
    payload: CommunicationCorrectionCreateRequest,
    actor: User,
) -> CommunicationRecordResponse:
    target = _load_visible_record(db, record_id, actor, for_update=True)
    _ensure_write_allowed(target.application, actor)
    _validate_channel(payload.channel, payload.channel_detail)
    _validate_sent_at(payload.sent_at)
    template_version_id = payload.template_version_id or target.template_version_id
    if template_version_id is not None:
        _load_template_version(
            db,
            version_id=template_version_id,
            context_type=target.context_type,
            require_active=False,
        )
    _validate_safe_snapshot(target.application, subject=payload.subject, body=payload.body)
    recipient_type, recipient_masked = _recipient_for_channel(target.application, payload.channel)
    root_id = target.id if target.record_kind == "sent" else target.root_record_id
    if root_id is None:
        raise CommunicationServiceError("沟通更正根记录不存在", status_code=409)
    request_fingerprint = _fingerprint(
        {
            "action": "correction",
            "corrects_record_id": str(target.id),
            "template_version_id": str(template_version_id),
            "channel": payload.channel,
            "channel_detail": payload.channel_detail,
            "subject_hash": _content_hash(payload.subject),
            "body_hash": _content_hash(payload.body),
            "sent_at": _as_aware(payload.sent_at).isoformat(),
            "correction_reason_hash": _content_hash(payload.correction_reason),
        }
    )
    replay = _check_record_replay(
        db,
        idempotency_key=payload.idempotency_key,
        fingerprint=request_fingerprint,
        actor=actor,
    )
    if replay is not None:
        return _record_response(replay, actor)
    existing_correction = db.scalar(
        select(CommunicationRecord).where(CommunicationRecord.corrects_record_id == target.id)
    )
    if existing_correction is not None:
        raise CommunicationServiceError("该沟通记录已经存在更正记录", status_code=409)
    correction = CommunicationRecord(
        application_id=target.application_id,
        candidate_id=target.candidate_id,
        context_type=target.context_type,
        context_id=target.context_id,
        template_version_id=template_version_id,
        record_kind="correction",
        root_record_id=root_id,
        corrects_record_id=target.id,
        correction_sequence=target.correction_sequence + 1,
        correction_reason=payload.correction_reason,
        channel=payload.channel,
        channel_detail=payload.channel_detail,
        recipient_type=recipient_type,
        recipient_masked=recipient_masked,
        candidate_name_snapshot=target.candidate_name_snapshot,
        subject_snapshot=payload.subject,
        body_snapshot=payload.body,
        sent_at=_as_aware(payload.sent_at),
        is_historical=False,
        idempotency_key=payload.idempotency_key,
        request_fingerprint=request_fingerprint,
        created_by_id=actor.id,
        created_by_username_snapshot=actor.username,
        created_by_display_name_snapshot=actor.display_name,
    )
    db.add(correction)
    db.flush()
    record_audit(
        db,
        action="communication.corrected",
        target_type="communication",
        target_id=correction.id,
        job_id=target.application.job_id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(payload.idempotency_key),
            "fingerprint": request_fingerprint,
            "root_record_id": str(root_id),
            "corrects_record_id": str(target.id),
            "correction_sequence": correction.correction_sequence,
            "channel": payload.channel,
            "recipient_masked": recipient_masked,
            "subject_sha256": _content_hash(payload.subject),
            "body_sha256": _content_hash(payload.body),
            "reason_sha256": _content_hash(payload.correction_reason),
        },
    )
    db.commit()
    db.refresh(correction)
    return _record_response(correction, actor)


def record_copy_audit(
    db: Session,
    *,
    payload: CommunicationCopyAuditRequest,
    actor: User,
) -> CommunicationCopyAuditResponse:
    context = _load_context(
        db,
        context_type=payload.context_type,
        context_id=payload.context_id,
        actor=actor,
    )
    if payload.template_version_id is not None:
        _load_template_version(
            db,
            version_id=payload.template_version_id,
            context_type=payload.context_type,
            require_active=False,
        )
    request_fingerprint = _fingerprint(
        {
            "action": "copy",
            "context_type": payload.context_type,
            "context_id": str(payload.context_id),
            "template_version_id": str(payload.template_version_id),
            "subject_hash": _content_hash(payload.subject),
            "body_hash": _content_hash(payload.body),
        }
    )
    replay = _find_copy_audit(
        db,
        context_type=payload.context_type,
        context_id=payload.context_id,
        idempotency_key=payload.idempotency_key,
    )
    if replay is not None:
        details = replay.details if isinstance(replay.details, dict) else {}
        if details.get("fingerprint") != request_fingerprint:
            raise CommunicationServiceError("幂等键已被不同请求使用", status_code=409)
        return CommunicationCopyAuditResponse(
            audit_id=replay.id,
            context_type=payload.context_type,  # type: ignore[arg-type]
            context_id=payload.context_id,
            template_version_id=payload.template_version_id,
            copied_at=replay.created_at,
        )
    audit = record_audit(
        db,
        action="communication.copied",
        target_type="communication",
        target_id=payload.context_id,
        job_id=context.application.job_id,
        result="success",
        actor=actor,
        details={
            "idempotency_key": str(payload.idempotency_key),
            "fingerprint": request_fingerprint,
            "context_type": payload.context_type,
            "context_id": str(payload.context_id),
            "application_id": str(context.application.id),
            "candidate_id": str(context.application.candidate_id),
            "template_version_id": (
                str(payload.template_version_id) if payload.template_version_id else None
            ),
            "subject_sha256": _content_hash(payload.subject),
            "body_sha256": _content_hash(payload.body),
        },
    )
    db.commit()
    db.refresh(audit)
    return CommunicationCopyAuditResponse(
        audit_id=audit.id,
        context_type=payload.context_type,
        context_id=payload.context_id,
        template_version_id=payload.template_version_id,
        copied_at=audit.created_at,
    )


def list_communications(
    db: Session,
    *,
    actor: User,
    context_type: str | None = None,
    context_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    limit: int = 20,
    offset: int = 0,
) -> CommunicationRecordListResponse:
    _ensure_read_role(actor)
    filters = [CommunicationRecord.record_kind == "sent", _scope_clause(actor)]
    if context_type is not None:
        filters.append(CommunicationRecord.context_type == context_type)
    if context_id is not None:
        filters.append(CommunicationRecord.context_id == context_id)
    if application_id is not None:
        filters.append(CommunicationRecord.application_id == application_id)
    total = db.scalar(
        select(func.count(CommunicationRecord.id))
        .join(JobApplication, CommunicationRecord.application_id == JobApplication.id)
        .join(Job, JobApplication.job_id == Job.id)
        .where(*filters)
    ) or 0
    records = list(
        db.scalars(
            select(CommunicationRecord)
            .join(JobApplication, CommunicationRecord.application_id == JobApplication.id)
            .join(Job, JobApplication.job_id == Job.id)
            .where(*filters)
            .options(
                selectinload(CommunicationRecord.application).selectinload(JobApplication.job),
                selectinload(CommunicationRecord.application).selectinload(JobApplication.candidate),
            )
            .order_by(CommunicationRecord.sent_at.desc(), CommunicationRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    correction_rows = db.execute(
        select(
            CommunicationRecord.root_record_id,
            func.count(CommunicationRecord.id),
            func.max(CommunicationRecord.correction_sequence),
        )
        .where(
            CommunicationRecord.root_record_id.in_([record.id for record in records])
            if records
            else false()
        )
        .group_by(CommunicationRecord.root_record_id)
    ).all()
    correction_counts = {row[0]: row[1] for row in correction_rows}
    latest_sequences = {row[0]: row[2] for row in correction_rows}
    latest_ids: dict[uuid.UUID, uuid.UUID] = {}
    if latest_sequences:
        for latest in db.scalars(
            select(CommunicationRecord).where(
                or_(
                    *[
                        (
                            (CommunicationRecord.root_record_id == root_id)
                            & (CommunicationRecord.correction_sequence == sequence)
                        )
                        for root_id, sequence in latest_sequences.items()
                    ]
                )
            )
        ):
            if latest.root_record_id is not None:
                latest_ids[latest.root_record_id] = latest.id
    return CommunicationRecordListResponse(
        items=[
            _summary_response(
                record,
                actor=actor,
                correction_count=correction_counts.get(record.id, 0),
                latest_correction_id=latest_ids.get(record.id),
            )
            for record in records
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_communication_detail(
    db: Session,
    *,
    record_id: uuid.UUID,
    actor: User,
) -> CommunicationRecordDetailResponse:
    record = _load_visible_record(db, record_id, actor)
    root_id = record.id if record.record_kind == "sent" else record.root_record_id
    corrections = []
    if root_id is not None:
        corrections = list(
            db.scalars(
                select(CommunicationRecord)
                .where(CommunicationRecord.root_record_id == root_id)
                .options(
                    selectinload(CommunicationRecord.application).selectinload(JobApplication.job),
                    selectinload(CommunicationRecord.application).selectinload(JobApplication.candidate),
                )
                .order_by(CommunicationRecord.correction_sequence.asc())
            )
        )
    base = _record_response(record, actor).model_dump()
    base["corrections"] = [_record_response(item, actor) for item in corrections]
    return CommunicationRecordDetailResponse(**base)