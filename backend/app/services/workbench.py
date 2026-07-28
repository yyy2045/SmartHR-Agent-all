from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.schemas.workbench import (
    WorkbenchItemResponse,
    WorkbenchItemType,
    WorkbenchPriority,
    WorkbenchSection,
    WorkbenchSource,
)

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
