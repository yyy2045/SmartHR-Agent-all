import math
import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ANALYTICS_TIMEZONE = "Asia/Shanghai"
ANALYTICS_MAX_RANGE_DAYS = 366
ANALYTICS_SMALL_SAMPLE_SIZE = 5

AnalyticsInterval = Literal["day", "week"]
FunnelStageKey = Literal[
    "application_created",
    "ai_screening_completed",
    "recruiter_shortlisted",
    "interview_started",
    "interview_passed",
    "offer_approved",
    "offer_accepted",
    "onboarding_completed",
]
CurrentStageKey = Literal[
    "unprocessed",
    "pending",
    "shortlisted",
    "to_contact",
    "contacted",
    "to_interview",
    "completed",
    "rejected",
    "offer_pending_response",
    "offer_rejected",
    "onboarding_pending_confirmation",
    "onboarding_pending_start",
    "onboarding_completed",
    "onboarding_abandoned",
]
OfferStatusKey = Literal[
    "draft",
    "pending_manager_confirmation",
    "pending_approval",
    "approved",
    "rejected",
    "pending_response",
    "accepted",
    "declined",
]
OnboardingStatusKey = Literal[
    "pending_confirmation",
    "candidate_proposed_date",
    "pending_start",
    "onboarded",
    "abandoned",
]
OnboardingAbandonmentSource = Literal[
    "candidate_withdrew",
    "company_cancelled",
    "other",
]
DecisionDifferenceKey = Literal[
    "consistent",
    "human_upgraded",
    "human_downgraded",
    "missing_human_decision",
]

FUNNEL_STAGE_ORDER: tuple[FunnelStageKey, ...] = (
    "application_created",
    "ai_screening_completed",
    "recruiter_shortlisted",
    "interview_started",
    "interview_passed",
    "offer_approved",
    "offer_accepted",
    "onboarding_completed",
)
CURRENT_STAGE_ORDER: tuple[CurrentStageKey, ...] = (
    "unprocessed",
    "pending",
    "shortlisted",
    "to_contact",
    "contacted",
    "to_interview",
    "completed",
    "rejected",
    "offer_pending_response",
    "offer_rejected",
    "onboarding_pending_confirmation",
    "onboarding_pending_start",
    "onboarding_completed",
    "onboarding_abandoned",
)
OFFER_STATUS_ORDER: tuple[OfferStatusKey, ...] = (
    "draft",
    "pending_manager_confirmation",
    "pending_approval",
    "approved",
    "rejected",
    "pending_response",
    "accepted",
    "declined",
)
ONBOARDING_STATUS_ORDER: tuple[OnboardingStatusKey, ...] = (
    "pending_confirmation",
    "candidate_proposed_date",
    "pending_start",
    "onboarded",
    "abandoned",
)
DECISION_DIFFERENCE_ORDER: tuple[DecisionDifferenceKey, ...] = (
    "consistent",
    "human_upgraded",
    "human_downgraded",
    "missing_human_decision",
)


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalyticsQuery(AnalyticsModel):
    start_date: date
    end_date: date
    job_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("分析结束日期不能早于开始日期")
        inclusive_days = (self.end_date - self.start_date).days + 1
        if inclusive_days > ANALYTICS_MAX_RANGE_DAYS:
            raise ValueError(f"分析时间范围不能超过 {ANALYTICS_MAX_RANGE_DAYS} 天")
        return self


class AnalyticsMeta(AnalyticsModel):
    as_of: datetime
    timezone: Literal["Asia/Shanghai"] = ANALYTICS_TIMEZONE
    query: AnalyticsQuery
    visible_job_count: int = Field(ge=0)

    @field_validator("as_of")
    @classmethod
    def validate_aware_as_of(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("分析统计时间必须包含时区")
        return value


class AnalyticsQuality(AnalyticsModel):
    complete: bool = True
    excluded_count: int = Field(default=0, ge=0)
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("数据完整性原因不能重复")
        expected_complete = self.excluded_count == 0 and not self.reasons
        if self.complete != expected_complete:
            raise ValueError("数据完整性标记与排除信息不一致")
        return self


class AnalyticsCountMetric(AnalyticsModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)


class AnalyticsRatioMetric(AnalyticsModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=100)
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    percentage: float | None = Field(default=None, ge=0, le=100)
    small_sample: bool = False

    @model_validator(mode="after")
    def validate_ratio(self) -> Self:
        if self.numerator > self.denominator:
            raise ValueError("比例指标分子不能大于分母")
        if self.denominator == 0:
            if self.percentage is not None:
                raise ValueError("零分母比例必须返回 null")
        else:
            expected = round(self.numerator / self.denominator * 100, 1)
            if self.percentage is None or not math.isclose(
                self.percentage, expected, abs_tol=0.05
            ):
                raise ValueError("比例指标与分子分母不一致")
        expected_small_sample = 0 < self.denominator < ANALYTICS_SMALL_SAMPLE_SIZE
        if self.small_sample != expected_small_sample:
            raise ValueError("小样本标记与分母不一致")
        return self


class AnalyticsOverviewResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    active_job_count: int = Field(ge=0)
    selected_job_count: int = Field(ge=0)
    application_count: int = Field(ge=0)
    unique_candidate_count: int = Field(ge=0)
    approved_headcount: int = Field(ge=0)
    hired_count: int = Field(ge=0)
    hiring_completion_rate: AnalyticsRatioMetric

    @model_validator(mode="after")
    def validate_completion_rate(self) -> Self:
        metric = self.hiring_completion_rate
        if metric.key != "hiring_completion_rate":
            raise ValueError("招聘完成率口径键错误")
        if metric.numerator != self.hired_count:
            raise ValueError("招聘完成率分子必须等于已入职人数")
        if metric.denominator != self.approved_headcount:
            raise ValueError("招聘完成率分母必须等于批准需求人数")
        if self.unique_candidate_count > self.application_count:
            raise ValueError("去重候选人数不能大于应聘数")
        if self.active_job_count > self.selected_job_count:
            raise ValueError("开放职位数不能大于所选职位数")
        return self


class FunnelStageMetric(AnalyticsModel):
    key: FunnelStageKey
    label: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)
    cohort_percentage: float | None = Field(default=None, ge=0, le=100)


class AnalyticsFunnelResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    cohort_size: int = Field(ge=0)
    stages: list[FunnelStageMetric]

    @model_validator(mode="after")
    def validate_funnel(self) -> Self:
        if tuple(item.key for item in self.stages) != FUNNEL_STAGE_ORDER:
            raise ValueError("历史漏斗必须按固定八个主阶段返回")
        previous_count = self.cohort_size
        for item in self.stages:
            if item.count > previous_count:
                raise ValueError("历史漏斗后续阶段人数不能增加")
            expected = (
                None
                if self.cohort_size == 0
                else round(item.count / self.cohort_size * 100, 1)
            )
            if expected is None:
                if item.cohort_percentage is not None:
                    raise ValueError("空漏斗百分比必须返回 null")
            elif item.cohort_percentage is None or not math.isclose(
                item.cohort_percentage, expected, abs_tol=0.05
            ):
                raise ValueError("漏斗比例与同批应聘总数不一致")
            previous_count = item.count
        return self


class CurrentStageMetric(AnalyticsModel):
    key: CurrentStageKey
    label: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)


class AnalyticsCurrentDistributionResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    total: int = Field(ge=0)
    stages: list[CurrentStageMetric]

    @model_validator(mode="after")
    def validate_distribution(self) -> Self:
        if tuple(item.key for item in self.stages) != CURRENT_STAGE_ORDER:
            raise ValueError("当前分布必须按全部互斥流程阶段返回")
        if sum(item.count for item in self.stages) != self.total:
            raise ValueError("当前阶段分布合计与有效应聘数不一致")
        return self


class AnalyticsTrendPoint(AnalyticsModel):
    bucket_start: date
    bucket_end: date
    applications_created: int = Field(ge=0)
    offers_accepted: int = Field(ge=0)
    onboardings_completed: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_bucket(self) -> Self:
        if self.bucket_end < self.bucket_start:
            raise ValueError("趋势时间桶结束日期不能早于开始日期")
        return self


class AnalyticsTrendResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    interval: AnalyticsInterval
    points: list[AnalyticsTrendPoint]

    @model_validator(mode="after")
    def validate_points(self) -> Self:
        previous_end: date | None = None
        for point in self.points:
            bucket_days = (point.bucket_end - point.bucket_start).days + 1
            if self.interval == "day" and bucket_days != 1:
                raise ValueError("按日趋势必须使用单日时间桶")
            if self.interval == "week" and not 1 <= bucket_days <= 7:
                raise ValueError("按周趋势时间桶不能超过七天")
            if previous_end is not None and point.bucket_start <= previous_end:
                raise ValueError("趋势时间桶必须按时间升序且不能重叠")
            if (
                point.bucket_start < self.meta.query.start_date
                or point.bucket_end > self.meta.query.end_date
            ):
                raise ValueError("趋势时间桶不能超出查询范围")
            previous_end = point.bucket_end
        return self


class StageDurationMetric(AnalyticsModel):
    stage: FunnelStageKey
    label: str = Field(min_length=1, max_length=100)
    sample_size: int = Field(ge=0)
    p50_seconds: int | None = Field(default=None, ge=0)
    p90_seconds: int | None = Field(default=None, ge=0)
    excluded_count: int = Field(default=0, ge=0)
    current_open_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_percentiles(self) -> Self:
        if self.sample_size == 0:
            if self.p50_seconds is not None or self.p90_seconds is not None:
                raise ValueError("无完成样本时耗时分位数必须返回 null")
        elif self.p50_seconds is None or self.p90_seconds is None:
            raise ValueError("有完成样本时必须返回 P50 和 P90")
        elif self.p90_seconds < self.p50_seconds:
            raise ValueError("P90 耗时不能小于 P50")
        return self


class AnalyticsStageDurationResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    stages: list[StageDurationMetric]

    @model_validator(mode="after")
    def validate_unique_stages(self) -> Self:
        keys = [item.stage for item in self.stages]
        if len(keys) != len(set(keys)):
            raise ValueError("阶段耗时不能重复")
        if keys != sorted(keys, key=FUNNEL_STAGE_ORDER.index):
            raise ValueError("阶段耗时必须按主阶段顺序返回")
        return self


class AnalyticsInterviewResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    round_pass_rate: AnalyticsRatioMetric
    candidate_pass_rate: AnalyticsRatioMetric

    @model_validator(mode="after")
    def validate_metric_keys(self) -> Self:
        if self.round_pass_rate.key != "interview_round_pass_rate":
            raise ValueError("面试轮次通过率口径键错误")
        if self.candidate_pass_rate.key != "interview_candidate_pass_rate":
            raise ValueError("候选人面试通过率口径键错误")
        return self


class OfferStatusMetric(AnalyticsModel):
    key: OfferStatusKey
    label: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)


class AnalyticsOfferResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    total_offers: int = Field(ge=0)
    statuses: list[OfferStatusMetric]
    acceptance_rate: AnalyticsRatioMetric

    @model_validator(mode="after")
    def validate_offer_metrics(self) -> Self:
        if tuple(item.key for item in self.statuses) != OFFER_STATUS_ORDER:
            raise ValueError("Offer 状态必须按固定顺序返回")
        if sum(item.count for item in self.statuses) != self.total_offers:
            raise ValueError("Offer 状态合计与 Offer 总数不一致")
        if self.acceptance_rate.key != "offer_acceptance_rate":
            raise ValueError("Offer 接受率口径键错误")
        return self


class OnboardingStatusMetric(AnalyticsModel):
    key: OnboardingStatusKey
    label: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)


class OnboardingAbandonmentMetric(AnalyticsModel):
    key: OnboardingAbandonmentSource
    label: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)


class AnalyticsOnboardingResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    total_records: int = Field(ge=0)
    statuses: list[OnboardingStatusMetric]
    completion_rate: AnalyticsRatioMetric
    abandonment_sources: list[OnboardingAbandonmentMetric]

    @model_validator(mode="after")
    def validate_onboarding_metrics(self) -> Self:
        if tuple(item.key for item in self.statuses) != ONBOARDING_STATUS_ORDER:
            raise ValueError("入职状态必须按固定顺序返回")
        if sum(item.count for item in self.statuses) != self.total_records:
            raise ValueError("入职状态合计与入职记录总数不一致")
        if self.completion_rate.key != "onboarding_completion_rate":
            raise ValueError("入职完成率口径键错误")
        abandoned_count = next(
            item.count for item in self.statuses if item.key == "abandoned"
        )
        if sum(item.count for item in self.abandonment_sources) != abandoned_count:
            raise ValueError("放弃来源合计与放弃入职人数不一致")
        source_keys = [item.key for item in self.abandonment_sources]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("放弃来源不能重复")
        return self


class DecisionDifferenceMetric(AnalyticsModel):
    key: DecisionDifferenceKey
    label: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)
    percentage: float | None = Field(default=None, ge=0, le=100)


class AnalyticsDecisionDifferenceResponse(AnalyticsModel):
    meta: AnalyticsMeta
    quality: AnalyticsQuality = Field(default_factory=AnalyticsQuality)
    ai_screened_count: int = Field(ge=0)
    categories: list[DecisionDifferenceMetric]

    @model_validator(mode="after")
    def validate_categories(self) -> Self:
        if tuple(item.key for item in self.categories) != DECISION_DIFFERENCE_ORDER:
            raise ValueError("AI 与人工差异必须按固定四类返回")
        if sum(item.count for item in self.categories) != self.ai_screened_count:
            raise ValueError("AI 与人工差异合计与有效 AI 结果数不一致")
        for item in self.categories:
            expected = (
                None
                if self.ai_screened_count == 0
                else round(item.count / self.ai_screened_count * 100, 1)
            )
            if expected is None:
                if item.percentage is not None:
                    raise ValueError("空差异统计百分比必须返回 null")
            elif item.percentage is None or not math.isclose(
                item.percentage, expected, abs_tol=0.05
            ):
                raise ValueError("AI 与人工差异比例不一致")
        return self
