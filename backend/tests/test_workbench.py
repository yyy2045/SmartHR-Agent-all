import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.workbench import WorkbenchItemResponse, WorkbenchSummaryResponse
from app.services.workbench import WORKBENCH_RULES, rules_for_roles, workbench_item_sort_key


def make_item(
    *,
    stable_key: str,
    priority: str = "normal",
    risk_at: datetime | None = None,
    occurred_at: datetime | None = None,
) -> WorkbenchItemResponse:
    return WorkbenchItemResponse(
        stable_key=stable_key,
        section="action_required",
        item_type="manual_screening",
        source="screening",
        priority=priority,
        title="待人工初筛",
        summary="1 名候选人等待人工结论",
        count=1,
        occurred_at=occurred_at or datetime(2026, 7, 29, tzinfo=UTC),
        risk_at=risk_at,
        job_id=uuid.uuid4(),
        job_title="后端工程师",
        target_path="/jobs/00000000-0000-0000-0000-000000000001/results",
    )


def test_registry_freezes_all_confirmed_workbench_types() -> None:
    expected_types = {
        "recruitment_request_revision",
        "recruitment_request_approval",
        "manual_screening",
        "interview_scheduling",
        "interview_evaluation",
        "interview_report",
        "offer_manager_confirmation",
        "offer_approval",
        "offer_link",
        "onboarding_date",
        "onboarding_outcome",
        "system_failure",
        "temporary_password_account",
    }

    assert {rule.item_type for rule in WORKBENCH_RULES} == expected_types
    assert len(WORKBENCH_RULES) == len(expected_types)
    for rule in WORKBENCH_RULES:
        assert rule.roles
        assert rule.states
        assert rule.terminal_states
        assert rule.appears_when
        assert rule.disappears_when
        assert rule.target_route_template.startswith("/")


@pytest.mark.parametrize("rule", WORKBENCH_RULES, ids=lambda rule: rule.item_type)
def test_each_rule_defines_appearance_and_disappearance(rule) -> None:
    for state in rule.states:
        assert rule.is_active(state.key)
        assert rule.section_for_state(state.key) == state.section
    for terminal_state in rule.terminal_states:
        assert not rule.is_active(terminal_state)
        assert rule.section_for_state(terminal_state) is None


def test_waiting_external_is_separate_from_action_required() -> None:
    rules = {rule.item_type: rule for rule in WORKBENCH_RULES}

    assert rules["offer_link"].section_for_state("waiting_candidate_response") == (
        "waiting_external"
    )
    assert rules["onboarding_date"].section_for_state(
        "pending_candidate_confirmation"
    ) == "waiting_external"
    assert rules["offer_link"].section_for_state("approved_without_link") == (
        "action_required"
    )
    assert rules["onboarding_date"].section_for_state("candidate_proposed_date") == (
        "action_required"
    )


def test_archived_jobs_only_keep_offer_and_onboarding_work() -> None:
    rules = {rule.item_type: rule for rule in WORKBENCH_RULES}

    for item_type in (
        "manual_screening",
        "interview_scheduling",
        "interview_evaluation",
        "interview_report",
        "system_failure",
    ):
        assert not rules[item_type].is_active(
            rules[item_type].states[0].key,
            job_status="archived",
        )

    for item_type in (
        "offer_manager_confirmation",
        "offer_approval",
        "offer_link",
        "onboarding_date",
        "onboarding_outcome",
    ):
        assert rules[item_type].is_active(
            rules[item_type].states[0].key,
            job_status="archived",
        )


def test_multi_role_registry_is_deduplicated_and_role_scoped() -> None:
    manager_rules = rules_for_roles(["hiring_manager"])
    combined_rules = rules_for_roles(["hiring_manager", "approver"])
    admin_rules = rules_for_roles(["administrator", "recruiter"])

    assert {rule.item_type for rule in manager_rules} == {
        "recruitment_request_revision",
        "offer_manager_confirmation",
    }
    assert {rule.item_type for rule in combined_rules} == {
        "recruitment_request_revision",
        "recruitment_request_approval",
        "offer_manager_confirmation",
        "offer_approval",
    }
    assert len(admin_rules) == len(WORKBENCH_RULES)
    assert len({rule.item_type for rule in admin_rules}) == len(admin_rules)


def test_items_have_stable_priority_risk_and_age_order() -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    items = [
        make_item(stable_key="normal", priority="normal", occurred_at=now),
        make_item(stable_key="high-later", priority="high", occurred_at=now),
        make_item(
            stable_key="urgent-later",
            priority="urgent",
            risk_at=now + timedelta(days=2),
            occurred_at=now - timedelta(days=2),
        ),
        make_item(
            stable_key="urgent-earlier",
            priority="urgent",
            risk_at=now + timedelta(days=1),
            occurred_at=now - timedelta(days=1),
        ),
    ]

    assert [item.stable_key for item in sorted(items, key=workbench_item_sort_key)] == [
        "urgent-earlier",
        "urgent-later",
        "high-later",
        "normal",
    ]


def test_item_contract_rejects_external_target_and_zero_count() -> None:
    with pytest.raises(ValidationError, match="站内路径"):
        WorkbenchItemResponse.model_validate(
            {
                **make_item(stable_key="external").model_dump(),
                "target_path": "https://example.com",
            }
        )

    with pytest.raises(ValidationError):
        WorkbenchItemResponse.model_validate(
            {**make_item(stable_key="empty").model_dump(), "count": 0}
        )


def test_summary_contract_rejects_inconsistent_or_silent_partial_counts() -> None:
    base = {
        "as_of": datetime(2026, 7, 29, tzinfo=UTC),
        "total_count": 3,
        "action_required_count": 2,
        "sections": [
            {"section": "action_required", "count": 2},
            {"section": "waiting_external", "count": 1},
            {"section": "risk_failure", "count": 0},
        ],
        "priorities": [
            {"priority": "urgent", "count": 0},
            {"priority": "high", "count": 1},
            {"priority": "normal", "count": 2},
        ],
        "types": [{"item_type": "manual_screening", "count": 3}],
        "partial": False,
        "failed_sources": [],
    }
    assert WorkbenchSummaryResponse.model_validate(base).total_count == 3

    with pytest.raises(ValidationError, match="分区合计"):
        WorkbenchSummaryResponse.model_validate({**base, "total_count": 4})
    with pytest.raises(ValidationError, match="部分失败标记"):
        WorkbenchSummaryResponse.model_validate(
            {**base, "partial": True, "failed_sources": []}
        )
