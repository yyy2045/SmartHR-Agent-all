from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    Job,
    JobApplication,
    Offer,
    OfferPortalLink,
    Onboarding,
    RecruitmentRequest,
    ResumeDocument,
    ScreeningBatch,
    ScreeningResult,
    User,
)
from app.schemas.workbench import (
    WorkbenchItemResponse,
    WorkbenchItemType,
    WorkbenchPriority,
    WorkbenchSection,
    WorkbenchSource,
)

logger = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")

RoleKey = Literal["administrator", "recruiter", "hiring_manager", "approver"]
AggregationMode = Literal["single", "job_type"]


@dataclass(frozen=True)
class WorkbenchState:
    key: str
    section: WorkbenchSection


@dataclass(frozen=True)
class WorkbenchRule:
    item_type: WorkbenchItemType
    source: WorkbenchSource
    roles: frozenset[RoleKey]
    states: tuple[WorkbenchState, ...]
    terminal_states: frozenset[str]
    aggregation: AggregationMode
    target_route_template: str
    default_priority: WorkbenchPriority
    survives_archived_job: bool
    appears_when: str
    disappears_when: str

    def section_for_state(self, state: str) -> WorkbenchSection | None:
        return next((item.section for item in self.states if item.key == state), None)

    def is_active(self, state: str, *, job_status: str | None = None) -> bool:
        if job_status == "archived" and not self.survives_archived_job:
            return False
        return self.section_for_state(state) is not None


ADMIN = frozenset({"administrator"})
RECRUITER = frozenset({"administrator", "recruiter"})
MANAGER = frozenset({"administrator", "hiring_manager"})
APPROVER = frozenset({"administrator", "approver"})


def _states(
    *action_required: str,
    waiting_external: tuple[str, ...] = (),
    risk_failure: tuple[str, ...] = (),
) -> tuple[WorkbenchState, ...]:
    return (
        *(WorkbenchState(key, "action_required") for key in action_required),
        *(WorkbenchState(key, "waiting_external") for key in waiting_external),
        *(WorkbenchState(key, "risk_failure") for key in risk_failure),
    )


WORKBENCH_RULES: tuple[WorkbenchRule, ...] = (
    WorkbenchRule(
        item_type="recruitment_request_revision",
        source="recruitment_requests",
        roles=MANAGER,
        states=_states("draft", "rejected"),
        terminal_states=frozenset({"pending_approval", "approved", "converted", "closed"}),
        aggregation="single",
        target_route_template="/recruitment-requests",
        default_priority="normal",
        survives_archived_job=True,
        appears_when="本人创建的需求仍为草稿，或审批驳回后等待修改重提",
        disappears_when="需求已提交、关闭或转换为职位",
    ),
    WorkbenchRule(
        item_type="recruitment_request_approval",
        source="recruitment_requests",
        roles=APPROVER,
        states=_states("pending_approval"),
        terminal_states=frozenset({"approved", "rejected", "converted", "closed"}),
        aggregation="single",
        target_route_template="/recruitment-requests",
        default_priority="high",
        survives_archived_job=True,
        appears_when="需求已经提交并等待审批",
        disappears_when="需求被批准、驳回、关闭或转换为职位",
    ),
    WorkbenchRule(
        item_type="manual_screening",
        source="screening",
        roles=RECRUITER,
        states=_states("pending_decision"),
        terminal_states=frozenset({"decided", "process_ended"}),
        aggregation="job_type",
        target_route_template="/jobs/{job_id}/results",
        default_priority="normal",
        survives_archived_job=False,
        appears_when="有效应聘已有可用筛选结果但尚无有效人工初筛结论",
        disappears_when="人工结论已记录或候选人流程终止",
    ),
    WorkbenchRule(
        item_type="interview_scheduling",
        source="interviews",
        roles=RECRUITER,
        states=_states("pending_schedule"),
        terminal_states=frozenset({"scheduled", "process_ended"}),
        aggregation="job_type",
        target_route_template="/jobs/{job_id}/pipeline",
        default_priority="normal",
        survives_archived_job=False,
        appears_when="候选人已进入面试阶段但尚无有效面试安排",
        disappears_when="已创建面试安排或候选人流程终止",
    ),
    WorkbenchRule(
        item_type="interview_evaluation",
        source="interviews",
        roles=RECRUITER,
        states=_states("pending_evaluation"),
        terminal_states=frozenset({"submitted", "cancelled", "process_ended"}),
        aggregation="job_type",
        target_route_template="/jobs/{job_id}/pipeline",
        default_priority="normal",
        survives_archived_job=False,
        appears_when="面试轮次已到计划时间、未取消且尚未提交评价",
        disappears_when="评价已提交、轮次取消或候选人流程终止",
    ),
    WorkbenchRule(
        item_type="interview_report",
        source="interviews",
        roles=RECRUITER,
        states=_states("pending_report"),
        terminal_states=frozenset({"confirmed", "process_ended"}),
        aggregation="job_type",
        target_route_template="/jobs/{job_id}/interview-reports",
        default_priority="normal",
        survives_archived_job=False,
        appears_when="应聘已有面试数据但尚无已确认面试报告",
        disappears_when="报告已确认或候选人流程终止",
    ),
    WorkbenchRule(
        item_type="offer_manager_confirmation",
        source="offers",
        roles=MANAGER,
        states=_states("pending_manager_confirmation"),
        terminal_states=frozenset({"pending_approval", "rejected", "approved"}),
        aggregation="single",
        target_route_template="/offers",
        default_priority="high",
        survives_archived_job=True,
        appears_when="Offer 当前版本等待用人经理确认",
        disappears_when="用人经理确认或驳回当前版本",
    ),
    WorkbenchRule(
        item_type="offer_approval",
        source="offers",
        roles=APPROVER,
        states=_states("pending_approval"),
        terminal_states=frozenset({"approved", "rejected"}),
        aggregation="single",
        target_route_template="/offers",
        default_priority="high",
        survives_archived_job=True,
        appears_when="Offer 当前版本已经过经理确认并等待审批",
        disappears_when="审批人批准或驳回当前版本",
    ),
    WorkbenchRule(
        item_type="offer_link",
        source="offers",
        roles=RECRUITER,
        states=_states(
            "approved_without_link",
            "link_expired",
            "link_revoked",
            waiting_external=("waiting_candidate_response",),
        ),
        terminal_states=frozenset({"accepted", "declined", "withdrawn"}),
        aggregation="single",
        target_route_template="/offers",
        default_priority="normal",
        survives_archived_job=True,
        appears_when="Offer 已批准但链接待生成或重生，或有效链接正等待候选人回应",
        disappears_when="候选人已回应，或 Offer 进入不可继续的终态",
    ),
    WorkbenchRule(
        item_type="onboarding_date",
        source="onboardings",
        roles=RECRUITER,
        states=_states(
            "candidate_proposed_date",
            waiting_external=("pending_candidate_confirmation",),
        ),
        terminal_states=frozenset({"pending_start", "onboarded", "abandoned"}),
        aggregation="single",
        target_route_template="/onboardings",
        default_priority="normal",
        survives_archived_job=True,
        appears_when="候选人日期等待招聘方处理，或招聘方日期等待候选人确认",
        disappears_when="日期已确认，或入职流程已经结束",
    ),
    WorkbenchRule(
        item_type="onboarding_outcome",
        source="onboardings",
        roles=RECRUITER,
        states=_states("start_date_due"),
        terminal_states=frozenset({"onboarded", "abandoned"}),
        aggregation="single",
        target_route_template="/onboardings",
        default_priority="urgent",
        survives_archived_job=True,
        appears_when="确认入职日期已到但尚未记录已入职或放弃",
        disappears_when="入职记录进入已入职或已放弃终态",
    ),
    WorkbenchRule(
        item_type="system_failure",
        source="system_failures",
        roles=RECRUITER,
        states=_states(risk_failure=("failed_actionable",)),
        terminal_states=frozenset({"recovered", "cancelled", "superseded"}),
        aggregation="job_type",
        target_route_template="/jobs/{job_id}",
        default_priority="high",
        survives_archived_job=False,
        appears_when="解析、AI、向量或推荐的最新有效尝试失败且仍可重试",
        disappears_when="重试成功、业务取消或更新的成功版本取代失败版本",
    ),
    WorkbenchRule(
        item_type="temporary_password_account",
        source="accounts",
        roles=ADMIN,
        states=_states("must_change_password"),
        terminal_states=frozenset({"password_changed", "disabled"}),
        aggregation="single",
        target_route_template="/settings/users",
        default_priority="normal",
        survives_archived_job=True,
        appears_when="有效内部账号仍在使用管理员创建的临时密码",
        disappears_when="用户已修改密码或账号被停用",
    ),
)

RULE_BY_TYPE = {rule.item_type: rule for rule in WORKBENCH_RULES}


def rules_for_roles(role_keys: list[str] | tuple[str, ...]) -> tuple[WorkbenchRule, ...]:
    roles = frozenset(role_keys)
    return tuple(rule for rule in WORKBENCH_RULES if rule.roles & roles)


def workbench_item_sort_key(item: WorkbenchItemResponse) -> tuple[float, float, float, str]:
    priority_rank = {"urgent": 0.0, "high": 1.0, "normal": 2.0}
    risk_timestamp = item.risk_at.timestamp() if item.risk_at is not None else float("inf")
    return (
        priority_rank[item.priority],
        risk_timestamp,
        item.occurred_at.timestamp(),
        item.stable_key,
    )


@dataclass(frozen=True)
class WorkbenchCollection:
    items: tuple[WorkbenchItemResponse, ...]
    failed_sources: tuple[WorkbenchSource, ...]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _date_end_utc(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59), _SHANGHAI).astimezone(UTC)


def _job_owner_scope(user: User):
    if user.has_role("administrator"):
        return Job.id.is_not(None)
    if user.has_role("recruiter"):
        return Job.owner_id == user.id
    return false()


def _priority_for_risk(
    default: WorkbenchPriority,
    risk_at: datetime | None,
    as_of: datetime,
    urgent_days: int,
) -> WorkbenchPriority:
    if risk_at is not None and _aware(risk_at) <= as_of + timedelta(days=urgent_days):
        return "urgent"
    return default


def _make_item(**values: object) -> WorkbenchItemResponse:
    return WorkbenchItemResponse.model_validate(values)


def _collect_recruitment_requests(
    db: Session,
    user: User,
    as_of: datetime,
) -> list[WorkbenchItemResponse]:
    if not user.has_role("administrator", "hiring_manager", "approver"):
        return []
    clauses = []
    if user.has_role("administrator"):
        clauses.append(RecruitmentRequest.id.is_not(None))
    else:
        if user.has_role("hiring_manager"):
            clauses.append(RecruitmentRequest.requester_id == user.id)
        if user.has_role("approver"):
            clauses.append(RecruitmentRequest.status == "pending_approval")
    requests = list(
        db.scalars(
            select(RecruitmentRequest)
            .where(or_(*clauses))
            .options(selectinload(RecruitmentRequest.versions))
        ).unique()
    )
    items: list[WorkbenchItemResponse] = []
    for request in requests:
        version = request.current_version
        target_path = f"/recruitment-requests?selected={request.id}"
        if (
            request.status in {"draft", "rejected"}
            and (user.has_role("administrator") or request.requester_id == user.id)
        ):
            items.append(
                _make_item(
                    stable_key=f"recruitment_request_revision:{request.id}",
                    section="action_required",
                    item_type="recruitment_request_revision",
                    source="recruitment_requests",
                    priority="normal",
                    title=f"完善招聘需求：{version.job_title}",
                    summary="草稿待提交" if request.status == "draft" else "审批驳回后待修改重提",
                    count=1,
                    occurred_at=_aware(request.updated_at),
                    risk_at=_date_end_utc(version.target_start_date),
                    target_path=target_path,
                )
            )
        if request.status == "pending_approval" and user.has_role(
            "administrator", "approver"
        ):
            items.append(
                _make_item(
                    stable_key=f"recruitment_request_approval:{request.id}",
                    section="action_required",
                    item_type="recruitment_request_approval",
                    source="recruitment_requests",
                    priority="high",
                    title=f"审批招聘需求：{version.job_title}",
                    summary=f"计划招聘 {version.headcount} 人",
                    count=1,
                    occurred_at=_aware(request.updated_at),
                    risk_at=_date_end_utc(version.target_start_date),
                    target_path=target_path,
                )
            )
    return items


def _application_query(user: User):
    return (
        select(JobApplication)
        .join(Job, JobApplication.job_id == Job.id)
        .where(
            JobApplication.status == "active",
            Job.status == "active",
            _job_owner_scope(user),
        )
        .options(
            selectinload(JobApplication.job),
            selectinload(JobApplication.process),
            selectinload(JobApplication.documents)
            .selectinload(ResumeDocument.screening_results)
            .selectinload(ScreeningResult.recruiter_decisions),
            selectinload(JobApplication.interview_schedule)
            .selectinload(CandidateInterviewSchedule.rounds)
            .selectinload(CandidateInterviewRound.evaluation),
            selectinload(JobApplication.interview_report),
        )
    )


def _aggregate_application_items(
    occurrences: dict[tuple[WorkbenchItemType, uuid.UUID], list[tuple[Job, datetime]]],
) -> list[WorkbenchItemResponse]:
    labels = {
        "manual_screening": ("待人工初筛", "名候选人等待人工结论", "results"),
        "interview_scheduling": ("待安排面试", "名候选人等待面试安排", "pipeline"),
        "interview_evaluation": ("待提交面试评价", "个面试轮次等待评价", "pipeline"),
        "interview_report": ("待确认面试报告", "名候选人等待报告确认", "interview-reports"),
    }
    items: list[WorkbenchItemResponse] = []
    for (item_type, job_id), rows in occurrences.items():
        job = rows[0][0]
        title, summary_suffix, route = labels[item_type]
        items.append(
            _make_item(
                stable_key=f"{item_type}:{job_id}",
                section="action_required",
                item_type=item_type,
                source="screening" if item_type == "manual_screening" else "interviews",
                priority="normal",
                title=f"{title} · {job.title}",
                summary=f"{len(rows)} {summary_suffix}",
                count=len(rows),
                occurred_at=min(_aware(row[1]) for row in rows),
                risk_at=None,
                job_id=job.id,
                job_title=job.title,
                target_path=f"/jobs/{job.id}/{route}",
            )
        )
    return items


def _collect_applications(
    db: Session,
    user: User,
    as_of: datetime,
) -> list[WorkbenchItemResponse]:
    if not user.has_role("administrator", "recruiter"):
        return []
    cache_key = "workbench_application_snapshot"
    cached = db.info.get(cache_key)
    if (
        isinstance(cached, tuple)
        and len(cached) == 3
        and cached[0] == user.id
        and cached[1] == as_of
    ):
        applications = cached[2]
    else:
        applications = list(db.scalars(_application_query(user)).unique())
        db.info[cache_key] = (user.id, as_of, applications)
    occurrences: dict[
        tuple[WorkbenchItemType, uuid.UUID], list[tuple[Job, datetime]]
    ] = defaultdict(list)
    for application in applications:
        process = application.process
        completed_results = [
            result
            for document in application.documents
            for result in document.screening_results
            if result.status == "completed"
        ]
        if completed_results and (
            process is None or process.current_stage == "unprocessed"
        ):
            occurred_at = min(
                _aware(result.completed_at or result.created_at) for result in completed_results
            )
            occurrences[("manual_screening", application.job_id)].append(
                (application.job, occurred_at)
            )

        if process is not None and process.current_stage == "to_interview":
            if application.interview_schedule is None:
                occurrences[("interview_scheduling", application.job_id)].append(
                    (application.job, _aware(process.stage_entered_at))
                )

        schedule = application.interview_schedule
        if schedule is None:
            continue
        pending_rounds = [
            round_item
            for round_item in schedule.rounds
            if round_item.status != "cancelled"
            and _aware(round_item.scheduled_start_at) <= as_of
            and (
                round_item.evaluation is None
                or round_item.evaluation.status != "submitted"
            )
        ]
        for round_item in pending_rounds:
            occurrences[("interview_evaluation", application.job_id)].append(
                (application.job, _aware(round_item.scheduled_start_at))
            )
        submitted_rounds = [
            round_item
            for round_item in schedule.rounds
            if round_item.evaluation is not None
            and round_item.evaluation.status == "submitted"
        ]
        if submitted_rounds and (
            application.interview_report is None
            or application.interview_report.status != "confirmed"
        ):
            occurred_at = min(
                _aware(round_item.evaluation.submitted_at or round_item.updated_at)
                for round_item in submitted_rounds
                if round_item.evaluation is not None
            )
            occurrences[("interview_report", application.job_id)].append(
                (application.job, occurred_at)
            )
    return _aggregate_application_items(occurrences)


def _collect_screening(
    db: Session,
    user: User,
    as_of: datetime,
) -> list[WorkbenchItemResponse]:
    return [
        item
        for item in _collect_applications(db, user, as_of)
        if item.source == "screening"
    ]


def _collect_interviews(
    db: Session,
    user: User,
    as_of: datetime,
) -> list[WorkbenchItemResponse]:
    return [
        item
        for item in _collect_applications(db, user, as_of)
        if item.source == "interviews"
    ]


def _offer_scope(user: User):
    if user.has_role("administrator"):
        return Offer.id.is_not(None)
    clauses = []
    if user.has_role("recruiter"):
        clauses.append(Job.owner_id == user.id)
    if user.has_role("hiring_manager"):
        clauses.append(Job.hiring_manager_id == user.id)
    if user.has_role("approver"):
        clauses.append(Offer.status == "pending_approval")
    return or_(*clauses) if clauses else false()


def _collect_offers(
    db: Session,
    user: User,
    as_of: datetime,
) -> list[WorkbenchItemResponse]:
    if not user.has_role("administrator", "recruiter", "hiring_manager", "approver"):
        return []
    offers = list(
        db.scalars(
            select(Offer)
            .join(JobApplication, Offer.application_id == JobApplication.id)
            .join(Job, JobApplication.job_id == Job.id)
            .where(JobApplication.status == "active", _offer_scope(user))
            .options(
                selectinload(Offer.application).selectinload(JobApplication.job),
                selectinload(Offer.application).selectinload(JobApplication.candidate),
                selectinload(Offer.versions),
                selectinload(Offer.portal_links).selectinload(OfferPortalLink.response),
                selectinload(Offer.candidate_response),
            )
        ).unique()
    )
    items: list[WorkbenchItemResponse] = []
    for offer in offers:
        job = offer.application.job
        candidate = offer.application.candidate
        target_path = f"/offers?selected={offer.id}"
        common = {
            "source": "offers",
            "count": 1,
            "occurred_at": _aware(offer.updated_at),
            "job_id": job.id,
            "job_title": job.title,
            "target_path": target_path,
        }
        if offer.status == "pending_manager_confirmation" and (
            user.has_role("administrator")
            or (user.has_role("hiring_manager") and job.hiring_manager_id == user.id)
        ):
            risk_at = _date_end_utc(offer.current_version.valid_until)
            items.append(
                _make_item(
                    stable_key=f"offer_manager_confirmation:{offer.id}",
                    section="action_required",
                    item_type="offer_manager_confirmation",
                    priority=_priority_for_risk(
                        "high",
                        risk_at,
                        as_of,
                        settings.workbench_offer_urgent_days,
                    ),
                    title=f"确认录用方案：{candidate.full_name or candidate.candidate_code}",
                    summary=job.title,
                    risk_at=risk_at,
                    **common,
                )
            )
        if offer.status == "pending_approval" and user.has_role(
            "administrator", "approver"
        ):
            risk_at = _date_end_utc(offer.current_version.valid_until)
            items.append(
                _make_item(
                    stable_key=f"offer_approval:{offer.id}",
                    section="action_required",
                    item_type="offer_approval",
                    priority=_priority_for_risk(
                        "high",
                        risk_at,
                        as_of,
                        settings.workbench_offer_urgent_days,
                    ),
                    title=f"审批 Offer：{candidate.full_name or candidate.candidate_code}",
                    summary=job.title,
                    risk_at=risk_at,
                    **common,
                )
            )
        if not (
            user.has_role("administrator")
            or (user.has_role("recruiter") and job.owner_id == user.id)
        ):
            continue
        if offer.candidate_response is not None or offer.status in {"accepted", "declined"}:
            continue
        if offer.status not in {"approved", "pending_response"}:
            continue
        if _date_end_utc(offer.current_version.valid_until) <= as_of:
            continue
        active_link = next(
            (link for link in reversed(offer.portal_links) if link.revoked_at is None),
            None,
        )
        risk_at = (
            _aware(active_link.expires_at)
            if active_link is not None
            else _date_end_utc(offer.current_version.valid_until)
        )
        if active_link is not None and _aware(active_link.expires_at) > as_of:
            section = "waiting_external"
            summary = "有效链接已生成，等待候选人回应"
        elif active_link is not None:
            section = "action_required"
            summary = "候选人链接已过期，需检查或重新生成"
        elif offer.portal_links:
            section = "action_required"
            summary = "候选人链接已撤回，需检查或重新生成"
        else:
            section = "action_required"
            summary = "Offer 已批准，尚未生成候选人链接"
        items.append(
            _make_item(
                stable_key=f"offer_link:{offer.id}",
                section=section,
                item_type="offer_link",
                priority=_priority_for_risk(
                    "normal",
                    risk_at,
                    as_of,
                    settings.workbench_offer_urgent_days,
                ),
                title=f"候选人 Offer：{candidate.full_name or candidate.candidate_code}",
                summary=summary,
                risk_at=risk_at,
                **common,
            )
        )
    return items


def _collect_onboardings(
    db: Session,
    user: User,
    as_of: datetime,
) -> list[WorkbenchItemResponse]:
    if not user.has_role("administrator", "recruiter"):
        return []
    onboardings = list(
        db.scalars(
            select(Onboarding)
            .join(JobApplication, Onboarding.application_id == JobApplication.id)
            .join(Job, JobApplication.job_id == Job.id)
            .where(JobApplication.status == "active", _job_owner_scope(user))
            .options(
                selectinload(Onboarding.application).selectinload(JobApplication.job),
                selectinload(Onboarding.application).selectinload(JobApplication.candidate),
                selectinload(Onboarding.offer).selectinload(Offer.versions),
            )
        ).unique()
    )
    items: list[WorkbenchItemResponse] = []
    today = as_of.astimezone(_SHANGHAI).date()
    for onboarding in onboardings:
        job = onboarding.application.job
        candidate = onboarding.application.candidate
        common = {
            "source": "onboardings",
            "count": 1,
            "occurred_at": _aware(onboarding.updated_at),
            "job_id": job.id,
            "job_title": job.title,
            "target_path": f"/onboardings?selected={onboarding.id}",
        }
        if onboarding.status in {"candidate_proposed_date", "pending_confirmation"}:
            waiting = onboarding.status == "pending_confirmation"
            reference_date = (
                onboarding.candidate_proposed_date
                or onboarding.recruiter_proposed_date
                or onboarding.offer.current_version.expected_start_date
            )
            risk_at = _date_end_utc(reference_date)
            items.append(
                _make_item(
                    stable_key=f"onboarding_date:{onboarding.id}",
                    section="waiting_external" if waiting else "action_required",
                    item_type="onboarding_date",
                    priority=_priority_for_risk(
                        "normal",
                        risk_at,
                        as_of,
                        settings.workbench_onboarding_urgent_days,
                    ),
                    title=f"确认入职日期：{candidate.full_name or candidate.candidate_code}",
                    summary=(
                        "等待候选人确认招聘方日期"
                        if waiting
                        else "候选人提出新日期，等待招聘方处理"
                    ),
                    risk_at=risk_at,
                    **common,
                )
            )
        if (
            onboarding.status == "pending_start"
            and onboarding.confirmed_start_date is not None
            and onboarding.confirmed_start_date <= today
        ):
            risk_at = _date_end_utc(onboarding.confirmed_start_date)
            items.append(
                _make_item(
                    stable_key=f"onboarding_outcome:{onboarding.id}",
                    section="action_required",
                    item_type="onboarding_outcome",
                    priority=_priority_for_risk(
                        "normal",
                        risk_at,
                        as_of,
                        settings.workbench_onboarding_urgent_days,
                    ),
                    title=f"记录入职结果：{candidate.full_name or candidate.candidate_code}",
                    summary="确认入职日期已到，等待记录已入职或放弃",
                    risk_at=risk_at,
                    **common,
                )
            )
    return items


def _collect_system_failures(
    db: Session,
    user: User,
    as_of: datetime,
) -> list[WorkbenchItemResponse]:
    if not user.has_role("administrator", "recruiter"):
        return []
    documents = list(
        db.scalars(
            select(ResumeDocument)
            .join(ScreeningBatch, ResumeDocument.batch_id == ScreeningBatch.id)
            .join(Job, ScreeningBatch.job_id == Job.id)
            .where(Job.status == "active", _job_owner_scope(user))
            .options(
                selectinload(ResumeDocument.batch).selectinload(ScreeningBatch.job),
                selectinload(ResumeDocument.screening_results),
                selectinload(ResumeDocument.embedding_chunks),
            )
        ).unique()
    )
    grouped: dict[tuple[uuid.UUID, str], list[tuple[ResumeDocument, datetime]]] = defaultdict(
        list
    )
    for document in documents:
        if document.status == "failed":
            grouped[(document.batch.job_id, "resume")].append(
                (document, _aware(document.updated_at))
            )
        if document.screening_results:
            latest_result = max(
                document.screening_results,
                key=lambda result: (_aware(result.created_at), result.analysis_version),
            )
            if latest_result.status == "failed":
                grouped[(document.batch.job_id, "ai")].append(
                    (document, _aware(latest_result.completed_at or latest_result.created_at))
                )
        if any(chunk.status == "failed" for chunk in document.embedding_chunks):
            failed_at = min(
                _aware(chunk.updated_at)
                for chunk in document.embedding_chunks
                if chunk.status == "failed"
            )
            grouped[(document.batch.job_id, "embedding")].append((document, failed_at))

    labels = {
        "resume": ("简历解析失败", "batches"),
        "ai": ("AI 筛选失败", "results"),
        "embedding": ("向量索引失败", "results"),
    }
    items: list[WorkbenchItemResponse] = []
    for (job_id, failure_type), rows in grouped.items():
        job = rows[0][0].batch.job
        label, route = labels[failure_type]
        items.append(
            _make_item(
                stable_key=f"system_failure:{failure_type}:{job_id}",
                section="risk_failure",
                item_type="system_failure",
                source="system_failures",
                priority="high",
                title=f"{label} · {job.title}",
                summary=f"{len(rows)} 份简历仍需处理",
                count=len(rows),
                occurred_at=min(row[1] for row in rows),
                risk_at=None,
                job_id=job.id,
                job_title=job.title,
                target_path=f"/jobs/{job.id}/{route}",
            )
        )
    return items


def _collect_accounts(
    db: Session,
    user: User,
    as_of: datetime,
) -> list[WorkbenchItemResponse]:
    if not user.has_role("administrator"):
        return []
    users = list(
        db.scalars(
            select(User).where(User.is_active.is_(True), User.must_change_password.is_(True))
        )
    )
    return [
        _make_item(
            stable_key=f"temporary_password_account:{item.id}",
            section="action_required",
            item_type="temporary_password_account",
            source="accounts",
            priority="normal",
            title=f"临时密码账号：{item.display_name}",
            summary=f"账号 {item.username} 尚未完成首次改密",
            count=1,
            occurred_at=_aware(item.created_at),
            risk_at=None,
            target_path=f"/settings/users?selected={item.id}",
        )
        for item in users
    ]


Collector = Callable[[Session, User, datetime], list[WorkbenchItemResponse]]
WORKBENCH_COLLECTORS: tuple[tuple[WorkbenchSource, Collector], ...] = (
    ("recruitment_requests", _collect_recruitment_requests),
    ("screening", _collect_screening),
    ("interviews", _collect_interviews),
    ("offers", _collect_offers),
    ("onboardings", _collect_onboardings),
    ("system_failures", _collect_system_failures),
    ("accounts", _collect_accounts),
)


def collect_workbench(
    db: Session,
    user: User,
    *,
    as_of: datetime | None = None,
) -> WorkbenchCollection:
    snapshot_at = _aware(as_of or datetime.now(UTC))
    collected: dict[str, WorkbenchItemResponse] = {}
    failed_sources: list[WorkbenchSource] = []
    for source, collector in WORKBENCH_COLLECTORS:
        try:
            for item in collector(db, user, snapshot_at):
                collected[item.stable_key] = item
        except Exception:
            db.rollback()
            failed_sources.append(source)
            logger.exception("工作台来源聚合失败", extra={"workbench_source": source})
    return WorkbenchCollection(
        items=tuple(sorted(collected.values(), key=workbench_item_sort_key)),
        failed_sources=tuple(failed_sources),
    )
