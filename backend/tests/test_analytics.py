import uuid
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.schemas.analytics import (
    CURRENT_STAGE_ORDER,
    DECISION_DIFFERENCE_ORDER,
    FUNNEL_STAGE_ORDER,
    OFFER_STATUS_ORDER,
    ONBOARDING_STATUS_ORDER,
    AnalyticsCurrentDistributionResponse,
    AnalyticsDecisionDifferenceResponse,
    AnalyticsFunnelResponse,
    AnalyticsInterviewResponse,
    AnalyticsMeta,
    AnalyticsOfferResponse,
    AnalyticsOnboardingResponse,
    AnalyticsOverviewResponse,
    AnalyticsQuery,
    AnalyticsRatioMetric,
    AnalyticsStageDurationResponse,
    AnalyticsTrendResponse,
)


def _meta() -> AnalyticsMeta:
    return AnalyticsMeta(
        as_of=datetime(2026, 7, 29, 8, tzinfo=UTC),
        query=AnalyticsQuery(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 30),
        ),
        visible_job_count=2,
    )


def _ratio(
    key: str,
    numerator: int,
    denominator: int,
    *,
    label: str = "指标",
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "numerator": numerator,
        "denominator": denominator,
        "percentage": (
            None if denominator == 0 else round(numerator / denominator * 100, 1)
        ),
        "small_sample": 0 < denominator < 5,
    }


def test_query_uses_inclusive_shanghai_days_and_limits_range() -> None:
    query = AnalyticsQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2026, 8, 1),
        job_id=uuid.uuid4(),
    )
    assert (query.end_date - query.start_date).days + 1 == 366

    with pytest.raises(ValidationError, match="不能早于"):
        AnalyticsQuery(start_date=date(2026, 7, 2), end_date=date(2026, 7, 1))
    with pytest.raises(ValidationError, match="不能超过 366 天"):
        AnalyticsQuery(start_date=date(2025, 7, 31), end_date=date(2026, 8, 1))


def test_meta_requires_timezone_aware_snapshot() -> None:
    with pytest.raises(ValidationError, match="必须包含时区"):
        AnalyticsMeta(
            as_of=datetime(2026, 7, 29, 8),
            query=AnalyticsQuery(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 30),
            ),
            visible_job_count=1,
        )


def test_ratio_contract_keeps_raw_counts_zero_denominator_and_sample_warning() -> None:
    metric = AnalyticsRatioMetric.model_validate(_ratio("offer_acceptance_rate", 2, 3))
    assert metric.percentage == 66.7
    assert metric.small_sample is True

    zero = AnalyticsRatioMetric.model_validate(_ratio("empty", 0, 0))
    assert zero.percentage is None
    assert zero.small_sample is False

    with pytest.raises(ValidationError, match="分子不能大于分母"):
        AnalyticsRatioMetric.model_validate(
            {**_ratio("invalid", 1, 1), "numerator": 2}
        )
    with pytest.raises(ValidationError, match="与分子分母不一致"):
        AnalyticsRatioMetric.model_validate(
            {**_ratio("invalid", 1, 2), "percentage": 49.9}
        )


def test_fixed_overview_contract_counts_applications_and_people_separately() -> None:
    response = AnalyticsOverviewResponse(
        meta=_meta(),
        active_job_count=1,
        selected_job_count=2,
        application_count=8,
        unique_candidate_count=7,
        approved_headcount=5,
        hired_count=2,
        hiring_completion_rate=_ratio("hiring_completion_rate", 2, 5),
    )

    assert response.application_count == 8
    assert response.unique_candidate_count == 7
    assert response.hiring_completion_rate.percentage == 40.0


def test_fixed_eight_stage_historical_funnel_is_monotonic() -> None:
    counts = (8, 7, 6, 5, 4, 3, 2, 1)
    response = AnalyticsFunnelResponse(
        meta=_meta(),
        cohort_size=8,
        stages=[
            {
                "key": key,
                "label": key,
                "count": count,
                "cohort_percentage": round(count / 8 * 100, 1),
            }
            for key, count in zip(FUNNEL_STAGE_ORDER, counts, strict=True)
        ],
    )
    assert [item.key for item in response.stages] == list(FUNNEL_STAGE_ORDER)

    payload = response.model_dump()
    payload["stages"][3]["count"] = 7
    with pytest.raises(ValidationError, match="后续阶段人数不能增加"):
        AnalyticsFunnelResponse.model_validate(payload)


def test_current_distribution_is_mutually_exclusive_and_complete() -> None:
    counts = {key: 0 for key in CURRENT_STAGE_ORDER}
    counts.update(
        {
            "unprocessed": 1,
            "pending": 1,
            "shortlisted": 1,
            "to_interview": 1,
            "offer_pending_response": 1,
            "onboarding_pending_start": 1,
            "onboarding_completed": 1,
            "rejected": 1,
        }
    )
    response = AnalyticsCurrentDistributionResponse(
        meta=_meta(),
        total=8,
        stages=[
            {"key": key, "label": key, "count": counts[key]}
            for key in CURRENT_STAGE_ORDER
        ],
    )
    assert sum(item.count for item in response.stages) == 8

    payload = response.model_dump()
    payload["stages"][0]["count"] = 2
    with pytest.raises(ValidationError, match="合计"):
        AnalyticsCurrentDistributionResponse.model_validate(payload)


def test_trend_buckets_are_ordered_bounded_and_use_fixed_series() -> None:
    response = AnalyticsTrendResponse(
        meta=_meta(),
        interval="day",
        points=[
            {
                "bucket_start": date(2026, 7, 1),
                "bucket_end": date(2026, 7, 1),
                "applications_created": 2,
                "offers_accepted": 1,
                "onboardings_completed": 0,
            },
            {
                "bucket_start": date(2026, 7, 2),
                "bucket_end": date(2026, 7, 2),
                "applications_created": 1,
                "offers_accepted": 0,
                "onboardings_completed": 1,
            },
        ],
    )
    assert response.points[1].onboardings_completed == 1

    payload = response.model_dump()
    payload["points"][1]["bucket_start"] = date(2026, 7, 1)
    payload["points"][1]["bucket_end"] = date(2026, 7, 1)
    with pytest.raises(ValidationError, match="不能重叠"):
        AnalyticsTrendResponse.model_validate(payload)


def test_stage_duration_contract_separates_completed_and_open_samples() -> None:
    response = AnalyticsStageDurationResponse(
        meta=_meta(),
        quality={
            "complete": False,
            "excluded_count": 1,
            "reasons": ["缺少下一阶段事件"],
        },
        stages=[
            {
                "stage": "application_created",
                "label": "应聘创建",
                "sample_size": 5,
                "p50_seconds": 3600,
                "p90_seconds": 7200,
                "excluded_count": 1,
                "current_open_count": 2,
            },
            {
                "stage": "ai_screening_completed",
                "label": "AI 筛选完成",
                "sample_size": 0,
                "p50_seconds": None,
                "p90_seconds": None,
                "excluded_count": 0,
                "current_open_count": 3,
            },
        ],
    )
    assert response.stages[0].p90_seconds == 7200

    payload = response.model_dump()
    payload["stages"][0]["p90_seconds"] = 3000
    with pytest.raises(ValidationError, match="P90"):
        AnalyticsStageDurationResponse.model_validate(payload)


def test_interview_contract_keeps_round_and_candidate_rates_separate() -> None:
    response = AnalyticsInterviewResponse(
        meta=_meta(),
        round_pass_rate=_ratio("interview_round_pass_rate", 3, 4),
        candidate_pass_rate=_ratio("interview_candidate_pass_rate", 2, 3),
    )
    assert response.round_pass_rate.percentage == 75.0
    assert response.candidate_pass_rate.percentage == 66.7


def test_offer_and_onboarding_contracts_keep_statuses_and_conversion_denominators() -> None:
    offer_counts = {key: 0 for key in OFFER_STATUS_ORDER}
    offer_counts.update({"approved": 1, "pending_response": 1, "accepted": 2})
    offers = AnalyticsOfferResponse(
        meta=_meta(),
        total_offers=4,
        statuses=[
            {"key": key, "label": key, "count": offer_counts[key]}
            for key in OFFER_STATUS_ORDER
        ],
        acceptance_rate=_ratio("offer_acceptance_rate", 2, 3),
    )
    assert offers.acceptance_rate.denominator == 3

    onboarding_counts = {key: 0 for key in ONBOARDING_STATUS_ORDER}
    onboarding_counts.update(
        {"pending_confirmation": 1, "onboarded": 1, "abandoned": 1}
    )
    onboardings = AnalyticsOnboardingResponse(
        meta=_meta(),
        total_records=3,
        statuses=[
            {"key": key, "label": key, "count": onboarding_counts[key]}
            for key in ONBOARDING_STATUS_ORDER
        ],
        completion_rate=_ratio("onboarding_completion_rate", 1, 3),
        abandonment_sources=[
            {"key": "candidate_withdrew", "label": "候选人放弃", "count": 1}
        ],
    )
    assert onboardings.completion_rate.percentage == 33.3


def test_ai_human_difference_uses_four_exhaustive_categories() -> None:
    counts = dict(
        zip(DECISION_DIFFERENCE_ORDER, (3, 1, 1, 1), strict=True)
    )
    response = AnalyticsDecisionDifferenceResponse(
        meta=_meta(),
        ai_screened_count=6,
        categories=[
            {
                "key": key,
                "label": key,
                "count": counts[key],
                "percentage": round(counts[key] / 6 * 100, 1),
            }
            for key in DECISION_DIFFERENCE_ORDER
        ],
    )
    assert sum(item.count for item in response.categories) == 6

    payload = response.model_dump()
    payload["categories"][0]["percentage"] = 40.0
    with pytest.raises(ValidationError, match="差异比例"):
        AnalyticsDecisionDifferenceResponse.model_validate(payload)
