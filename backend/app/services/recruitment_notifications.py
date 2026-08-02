from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Job,
    Offer,
    OfferResponse,
    Onboarding,
    OnboardingEvent,
    RecruitmentRequest,
    Role,
    User,
    UserRole,
)
from app.services.internal_notifications import (
    InternalNotificationPayload,
    create_internal_notifications,
)


def _active_users_with_role(db: Session, role_key: str) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.is_active.is_(True), Role.key == role_key)
            .order_by(User.username)
        )
    )


def _compact_title(value: str | None, *, fallback: str = "相关职位") -> str:
    normalized = (value or "").strip()
    if not normalized:
        return fallback
    return normalized[:80]


def _recipients(*users: User | None) -> list[User]:
    return [user for user in users if user is not None]


def _request_route(request_id: uuid.UUID) -> str:
    return f"/recruitment-requests?selected={request_id}"


def _offer_route(offer_id: uuid.UUID) -> str:
    return f"/offers?selected={offer_id}"


def _onboarding_route(onboarding_id: uuid.UUID) -> str:
    return f"/onboardings?selected={onboarding_id}"


def notify_recruitment_request_submitted(
    db: Session,
    request: RecruitmentRequest,
) -> None:
    version = request.current_version
    create_internal_notifications(
        db,
        recipients=_active_users_with_role(db, "approver"),
        payload=InternalNotificationPayload(
            notification_type="recruitment_request_submitted",
            event_key=f"recruitment_request:{request.id}:submitted:v{version.version_number}",
            title="招聘需求待审批",
            summary=f"{_compact_title(version.job_title)} 有一条招聘需求待处理",
            resource_type="recruitment_request",
            resource_id=request.id,
            route_path=_request_route(request.id),
        ),
    )


def notify_recruitment_request_decided(
    db: Session,
    request: RecruitmentRequest,
    *,
    decision: str,
) -> None:
    version = request.current_version
    approved = decision == "approved"
    create_internal_notifications(
        db,
        recipients=_recipients(request.requester, request.recruiter),
        payload=InternalNotificationPayload(
            notification_type=(
                "recruitment_request_approved"
                if approved
                else "recruitment_request_rejected"
            ),
            event_key=(
                f"recruitment_request:{request.id}:{decision}:v{version.version_number}"
            ),
            title="招聘需求已批准" if approved else "招聘需求已驳回",
            summary=(
                f"{_compact_title(version.job_title)} 的招聘需求已批准"
                if approved
                else f"{_compact_title(version.job_title)} 的招聘需求已驳回，请查看处理意见"
            ),
            resource_type="recruitment_request",
            resource_id=request.id,
            route_path=_request_route(request.id),
        ),
    )


def notify_offer_submitted(db: Session, offer: Offer) -> None:
    job = offer.application.job
    version = offer.current_version
    create_internal_notifications(
        db,
        recipients=_recipients(job.hiring_manager),
        payload=InternalNotificationPayload(
            notification_type="offer_manager_confirmation_requested",
            event_key=f"offer:{offer.id}:submitted:v{version.version_number}",
            title="Offer 待用人经理确认",
            summary=f"{_compact_title(job.title)} 有一条 Offer 等待录用确认",
            resource_type="offer",
            resource_id=offer.id,
            route_path=_offer_route(offer.id),
        ),
    )


def notify_offer_manager_decided(
    db: Session,
    offer: Offer,
    *,
    decision: str,
) -> None:
    job = offer.application.job
    version = offer.current_version
    if decision == "confirmed":
        create_internal_notifications(
            db,
            recipients=_active_users_with_role(db, "approver"),
            payload=InternalNotificationPayload(
                notification_type="offer_approval_requested",
                event_key=f"offer:{offer.id}:manager:{decision}:v{version.version_number}",
                title="Offer 待最终审批",
                summary=f"{_compact_title(job.title)} 有一条 Offer 等待审批",
                resource_type="offer",
                resource_id=offer.id,
                route_path=_offer_route(offer.id),
            ),
        )
        return

    create_internal_notifications(
        db,
        recipients=_recipients(job.owner),
        payload=InternalNotificationPayload(
            notification_type="offer_rejected",
            event_key=f"offer:{offer.id}:manager:{decision}:v{version.version_number}",
            title="Offer 确认未通过",
            summary=f"{_compact_title(job.title)} 的 Offer 未通过用人经理确认",
            resource_type="offer",
            resource_id=offer.id,
            route_path=_offer_route(offer.id),
        ),
    )


def notify_offer_approval_decided(
    db: Session,
    offer: Offer,
    *,
    decision: str,
) -> None:
    job = offer.application.job
    approved = decision == "approved"
    create_internal_notifications(
        db,
        recipients=_recipients(job.owner, job.hiring_manager),
        payload=InternalNotificationPayload(
            notification_type="offer_approved" if approved else "offer_rejected",
            event_key=f"offer:{offer.id}:approval:{decision}:v{offer.current_version.version_number}",
            title="Offer 已批准" if approved else "Offer 审批未通过",
            summary=(
                f"{_compact_title(job.title)} 的 Offer 已批准，可继续发送候选人链接"
                if approved
                else f"{_compact_title(job.title)} 的 Offer 审批未通过，请查看审批意见"
            ),
            resource_type="offer",
            resource_id=offer.id,
            route_path=_offer_route(offer.id),
        ),
    )


def notify_offer_candidate_responded(
    db: Session,
    offer: Offer,
    response: OfferResponse,
) -> None:
    job = offer.application.job
    accepted = response.decision == "accepted"
    create_internal_notifications(
        db,
        recipients=_recipients(job.owner, job.hiring_manager),
        payload=InternalNotificationPayload(
            notification_type=(
                "offer_candidate_accepted"
                if accepted
                else "offer_candidate_rejected"
            ),
            event_key=(
                f"offer:{offer.id}:candidate_response:{response.id}:{response.decision}"
            ),
            title="候选人已接受 Offer" if accepted else "候选人已拒绝 Offer",
            summary=(
                f"{_compact_title(job.title)} 的候选人已接受 Offer"
                if accepted
                else f"{_compact_title(job.title)} 的候选人已拒绝 Offer，请查看原因"
            ),
            resource_type="offer",
            resource_id=offer.id,
            route_path=_offer_route(offer.id),
        ),
    )


def notify_onboarding_event(
    db: Session,
    onboarding: Onboarding,
    event: OnboardingEvent,
) -> None:
    job = onboarding.application.job
    notification_type, title, summary, recipients = _onboarding_notification_details(
        job,
        event,
    )
    if notification_type is None:
        return
    create_internal_notifications(
        db,
        recipients=recipients,
        payload=InternalNotificationPayload(
            notification_type=notification_type,
            event_key=(
                f"onboarding:{onboarding.id}:event:{event.sequence_number}:{event.action}"
            ),
            title=title,
            summary=summary,
            resource_type="onboarding",
            resource_id=onboarding.id,
            route_path=_onboarding_route(onboarding.id),
        ),
    )


def _onboarding_notification_details(
    job: Job,
    event: OnboardingEvent,
) -> tuple[str | None, str, str, list[User]]:
    job_title = _compact_title(job.title)
    if event.action == "candidate_confirmed_date":
        return (
            "onboarding_date_changed",
            "候选人已确认入职日期",
            f"{job_title} 的候选人已确认入职日期",
            _recipients(job.owner),
        )
    if event.action == "candidate_proposed_date":
        return (
            "onboarding_date_changed",
            "候选人提出新的入职日期",
            f"{job_title} 的候选人提出了新的入职日期，请处理",
            _recipients(job.owner),
        )
    if event.action == "recruiter_accepted_date":
        return (
            "onboarding_date_changed",
            "招聘方已确认入职日期",
            f"{job_title} 的入职日期已由招聘方确认",
            _recipients(job.hiring_manager),
        )
    if event.action == "recruiter_proposed_date":
        return (
            "onboarding_date_changed",
            "招聘方提出新的入职日期",
            f"{job_title} 的招聘方已提出新的入职日期",
            _recipients(job.hiring_manager),
        )
    if event.action == "onboarded":
        return (
            "onboarding_completed",
            "候选人已入职",
            f"{job_title} 的候选人已标记为入职",
            _recipients(job.owner, job.hiring_manager),
        )
    if event.action == "abandoned":
        return (
            "onboarding_abandoned",
            "候选人放弃入职",
            f"{job_title} 的入职流程已标记为放弃",
            _recipients(job.owner, job.hiring_manager),
        )
    if event.action == "onboarded_corrected":
        return (
            "onboarding_date_changed",
            "入职状态已更正",
            f"{job_title} 的入职状态已由管理员更正",
            _recipients(job.owner),
        )
    return None, "", "", []
