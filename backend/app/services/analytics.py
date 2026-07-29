from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session

from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    CandidateProcess,
    InterviewEvaluation,
    InterviewReport,
    InterviewReportVersion,
    Job,
    JobApplication,
    Offer,
    OfferApproval,
    OfferResponse,
    OfferVersion,
    Onboarding,
    OnboardingEvent,
    RecruiterDecision,
    RecruitmentRequest,
    RecruitmentRequestVersion,
    ResumeDocument,
    ScreeningResult,
    User,
)
from app.schemas.analytics import (
    ANALYTICS_TIMEZONE,
    CURRENT_STAGE_ORDER,
    DECISION_DIFFERENCE_ORDER,
    FUNNEL_STAGE_ORDER,
    OFFER_STATUS_ORDER,
    ONBOARDING_STATUS_ORDER,
    AnalyticsCurrentDistributionResponse,
    AnalyticsDashboardResponse,
    AnalyticsDecisionDifferenceResponse,
    AnalyticsFunnelResponse,
    AnalyticsInterviewResponse,
    AnalyticsJobOption,
    AnalyticsMeta,
    AnalyticsOfferResponse,
    AnalyticsOnboardingResponse,
    AnalyticsOverviewResponse,
    AnalyticsQuery,
    AnalyticsRatioMetric,
    AnalyticsStageDurationResponse,
    AnalyticsTrendResponse,
    CurrentStageMetric,
    DecisionDifferenceMetric,
    FunnelStageMetric,
    OfferStatusMetric,
    OnboardingAbandonmentMetric,
    OnboardingStatusMetric,
    StageDurationMetric,
)

SHANGHAI = ZoneInfo(ANALYTICS_TIMEZONE)

FUNNEL_STAGE_LABELS = {
    "application_created": "应聘创建",
    "ai_screening_completed": "AI 筛选完成",
    "recruiter_shortlisted": "人工初筛通过",
    "interview_started": "进入面试",
    "interview_passed": "面试通过",
    "offer_approved": "Offer 批准",
    "offer_accepted": "Offer 接受",
    "onboarding_completed": "已入职",
}
CURRENT_STAGE_LABELS = {
    "unprocessed": "待处理",
    "pending": "待定",
    "shortlisted": "初筛通过",
    "to_contact": "待联系",
    "contacted": "已联系",
    "to_interview": "面试中",
    "completed": "流程完成",
    "rejected": "已淘汰",
    "offer_pending_response": "Offer 待回应",
    "offer_rejected": "Offer 已拒绝",
    "onboarding_pending_confirmation": "待确认入职",
    "onboarding_pending_start": "待入职",
    "onboarding_completed": "已入职",
    "onboarding_abandoned": "放弃入职",
}


@dataclass(frozen=True)
class JobFact:
    id: uuid.UUID
    status: str
    recruitment_request_id: uuid.UUID | None


@dataclass(frozen=True)
class ApplicationFact:
    id: uuid.UUID
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    created_at: datetime


@dataclass(frozen=True)
class AnalyticsContext:
    query: AnalyticsQuery
    meta: AnalyticsMeta
    as_of: datetime
    start_utc: datetime
    end_utc: datetime
    jobs: tuple[JobFact, ...]
    applications: tuple[ApplicationFact, ...]

    @property
    def job_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(item.id for item in self.jobs)

    @property
    def application_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(item.id for item in self.applications)


def visible_job_clause(user: User):
    if user.has_role("administrator", "approver"):
        return Job.id.is_not(None)
    clauses = []
    if user.has_role("recruiter"):
        clauses.append(Job.owner_id == user.id)
    if user.has_role("hiring_manager"):
        clauses.append(Job.hiring_manager_id == user.id)
    return or_(*clauses) if clauses else false()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _query_bounds(query: AnalyticsQuery) -> tuple[datetime, datetime]:
    start = datetime.combine(query.start_date, time.min, tzinfo=SHANGHAI).astimezone(UTC)
    end = datetime.combine(
        query.end_date + timedelta(days=1), time.min, tzinfo=SHANGHAI
    ).astimezone(UTC)
    return start, end


def build_analytics_context(
    db: Session,
    user: User,
    query: AnalyticsQuery,
    *,
    as_of: datetime,
) -> AnalyticsContext:
    as_of = _aware(as_of).astimezone(UTC)
    start_utc, end_utc = _query_bounds(query)
    job_statement = select(
        Job.id,
        Job.status,
        Job.recruitment_request_id,
    ).where(visible_job_clause(user))
    if query.job_id is not None:
        job_statement = job_statement.where(Job.id == query.job_id)
    jobs = tuple(JobFact(*row) for row in db.execute(job_statement).all())
    if query.job_id is not None and not jobs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")

    job_ids = tuple(item.id for item in jobs)
    applications: tuple[ApplicationFact, ...] = ()
    if job_ids:
        application_rows = db.execute(
            select(
                JobApplication.id,
                JobApplication.candidate_id,
                JobApplication.job_id,
                JobApplication.created_at,
            ).where(
                JobApplication.status == "active",
                JobApplication.job_id.in_(job_ids),
                JobApplication.created_at >= start_utc,
                JobApplication.created_at < end_utc,
                JobApplication.created_at <= as_of,
            )
        ).all()
        applications = tuple(
            ApplicationFact(row.id, row.candidate_id, row.job_id, _aware(row.created_at))
            for row in application_rows
        )

    return AnalyticsContext(
        query=query,
        meta=AnalyticsMeta(
            as_of=as_of,
            query=query,
            visible_job_count=len(jobs),
        ),
        as_of=as_of,
        start_utc=start_utc,
        end_utc=end_utc,
        jobs=jobs,
        applications=applications,
    )


def _ratio(
    key: str,
    label: str,
    numerator: int,
    denominator: int,
) -> AnalyticsRatioMetric:
    return AnalyticsRatioMetric(
        key=key,
        label=label,
        numerator=numerator,
        denominator=denominator,
        percentage=(
            None if denominator == 0 else round(numerator / denominator * 100, 1)
        ),
        small_sample=0 < denominator < 5,
    )


def collect_overview(db: Session, context: AnalyticsContext) -> AnalyticsOverviewResponse:
    request_ids = tuple(
        item.recruitment_request_id
        for item in context.jobs
        if item.recruitment_request_id is not None
    )
    approved_headcount = 0
    if request_ids:
        headcounts = db.scalars(
            select(RecruitmentRequestVersion.headcount)
            .join(
                RecruitmentRequest,
                and_(
                    RecruitmentRequest.id == RecruitmentRequestVersion.request_id,
                    RecruitmentRequest.current_version_number
                    == RecruitmentRequestVersion.version_number,
                ),
            )
            .where(
                RecruitmentRequest.id.in_(request_ids),
                RecruitmentRequest.status.in_(("approved", "converted")),
            )
        ).all()
        approved_headcount = sum(headcounts)

    hired_application_ids: set[uuid.UUID] = set()
    if context.application_ids:
        hired_application_ids = set(
            db.scalars(
                select(Onboarding.application_id).where(
                    Onboarding.application_id.in_(context.application_ids),
                    Onboarding.status == "onboarded",
                )
            ).all()
        )
    linked_job_ids = {
        item.id for item in context.jobs if item.recruitment_request_id is not None
    }
    application_jobs = {item.id: item.job_id for item in context.applications}
    linked_hired_count = sum(
        application_jobs[application_id] in linked_job_ids
        for application_id in hired_application_ids
    )

    return AnalyticsOverviewResponse(
        meta=context.meta,
        active_job_count=sum(item.status == "active" for item in context.jobs),
        selected_job_count=len(context.jobs),
        application_count=len(context.applications),
        unique_candidate_count=len(
            {item.candidate_id for item in context.applications}
        ),
        approved_headcount=approved_headcount,
        hired_count=len(hired_application_ids),
        linked_hired_count=linked_hired_count,
        hiring_completion_rate=_ratio(
            "hiring_completion_rate",
            "招聘完成率",
            linked_hired_count,
            approved_headcount,
        ),
    )


def _application_id_set(db: Session, statement) -> set[uuid.UUID]:
    return set(db.scalars(statement.distinct()).all())


def collect_funnel(db: Session, context: AnalyticsContext) -> AnalyticsFunnelResponse:
    cohort = set(context.application_ids)
    raw: dict[str, set[uuid.UUID]] = {key: set() for key in FUNNEL_STAGE_ORDER}
    raw["application_created"] = cohort
    if cohort:
        raw["ai_screening_completed"] = _application_id_set(
            db,
            select(ResumeDocument.application_id)
            .join(ScreeningResult, ScreeningResult.document_id == ResumeDocument.id)
            .where(
                ResumeDocument.application_id.in_(cohort),
                ScreeningResult.status == "completed",
                ScreeningResult.completed_at <= context.as_of,
            ),
        )
        raw["recruiter_shortlisted"] = _application_id_set(
            db,
            select(ResumeDocument.application_id)
            .join(ScreeningResult, ScreeningResult.document_id == ResumeDocument.id)
            .join(
                RecruiterDecision,
                RecruiterDecision.screening_result_id == ScreeningResult.id,
            )
            .where(
                ResumeDocument.application_id.in_(cohort),
                RecruiterDecision.decision == "shortlisted",
                RecruiterDecision.created_at <= context.as_of,
            ),
        )
        raw["interview_started"] = _application_id_set(
            db,
            select(CandidateInterviewSchedule.application_id).where(
                CandidateInterviewSchedule.application_id.in_(cohort),
                CandidateInterviewSchedule.created_at <= context.as_of,
            ),
        )
        raw["interview_passed"] = _application_id_set(
            db,
            select(InterviewReport.application_id)
            .join(
                InterviewReportVersion,
                and_(
                    InterviewReportVersion.report_id == InterviewReport.id,
                    InterviewReportVersion.version_number
                    == InterviewReport.current_version_number,
                ),
            )
            .where(
                InterviewReport.application_id.in_(cohort),
                InterviewReport.status == "confirmed",
                InterviewReport.confirmed_at <= context.as_of,
                InterviewReportVersion.conclusion.in_(("hire", "next_round")),
            ),
        )
        raw["offer_approved"] = _application_id_set(
            db,
            select(Offer.application_id)
            .join(OfferVersion, OfferVersion.offer_id == Offer.id)
            .join(OfferApproval, OfferApproval.version_id == OfferVersion.id)
            .where(
                Offer.application_id.in_(cohort),
                OfferApproval.decision == "approved",
                OfferApproval.decided_at <= context.as_of,
            ),
        )
        raw["offer_accepted"] = _application_id_set(
            db,
            select(Offer.application_id)
            .join(OfferResponse, OfferResponse.offer_id == Offer.id)
            .where(
                Offer.application_id.in_(cohort),
                OfferResponse.decision == "accepted",
                OfferResponse.responded_at <= context.as_of,
            ),
        )
        raw["onboarding_completed"] = _application_id_set(
            db,
            select(Onboarding.application_id)
            .outerjoin(OnboardingEvent, OnboardingEvent.onboarding_id == Onboarding.id)
            .where(
                Onboarding.application_id.in_(cohort),
                or_(
                    Onboarding.status == "onboarded",
                    and_(
                        OnboardingEvent.action == "onboarded",
                        OnboardingEvent.created_at <= context.as_of,
                    ),
                ),
            ),
        )

    reached: dict[str, set[uuid.UUID]] = {}
    later_reached: set[uuid.UUID] = set()
    for key in reversed(FUNNEL_STAGE_ORDER):
        later_reached |= raw[key]
        reached[key] = later_reached & cohort
    counts = {key: len(reached[key]) for key in FUNNEL_STAGE_ORDER}
    cohort_size = len(cohort)
    return AnalyticsFunnelResponse(
        meta=context.meta,
        cohort_size=cohort_size,
        stages=[
            FunnelStageMetric(
                key=key,
                label=FUNNEL_STAGE_LABELS[key],
                count=counts[key],
                cohort_percentage=(
                    None
                    if cohort_size == 0
                    else round(counts[key] / cohort_size * 100, 1)
                ),
            )
            for key in FUNNEL_STAGE_ORDER
        ],
    )


def collect_current_distribution(
    db: Session,
    context: AnalyticsContext,
) -> AnalyticsCurrentDistributionResponse:
    stage_by_application: dict[uuid.UUID, str] = {}
    if context.application_ids:
        stage_by_application = dict(
            db.execute(
                select(CandidateProcess.application_id, CandidateProcess.current_stage).where(
                    CandidateProcess.application_id.in_(context.application_ids)
                )
            ).all()
        )
    counts = Counter(
        stage_by_application.get(application_id, "unprocessed")
        for application_id in context.application_ids
    )
    return AnalyticsCurrentDistributionResponse(
        meta=context.meta,
        total=len(context.application_ids),
        stages=[
            CurrentStageMetric(
                key=key,
                label=CURRENT_STAGE_LABELS[key],
                count=counts[key],
            )
            for key in CURRENT_STAGE_ORDER
        ],
    )


def _bucket_ranges(
    start_date: date,
    end_date: date,
    interval: str,
) -> list[tuple[date, date]]:
    ranges = []
    cursor = start_date
    step_days = 1 if interval == "day" else 7
    while cursor <= end_date:
        bucket_end = min(cursor + timedelta(days=step_days - 1), end_date)
        ranges.append((cursor, bucket_end))
        cursor = bucket_end + timedelta(days=1)
    return ranges


def _local_date(value: datetime) -> date:
    return _aware(value).astimezone(SHANGHAI).date()


def collect_trend(
    db: Session,
    context: AnalyticsContext,
    *,
    interval: str,
) -> AnalyticsTrendResponse:
    event_dates: dict[str, list[date]] = {
        "applications_created": [
            _local_date(item.created_at) for item in context.applications
        ],
        "offers_accepted": [],
        "onboardings_completed": [],
    }
    if context.job_ids:
        accepted_at = db.scalars(
            select(OfferResponse.responded_at)
            .join(Offer, Offer.id == OfferResponse.offer_id)
            .join(JobApplication, JobApplication.id == Offer.application_id)
            .where(
                JobApplication.status == "active",
                JobApplication.job_id.in_(context.job_ids),
                OfferResponse.decision == "accepted",
                OfferResponse.responded_at >= context.start_utc,
                OfferResponse.responded_at < context.end_utc,
                OfferResponse.responded_at <= context.as_of,
            )
        ).all()
        onboarded_at = db.scalars(
            select(OnboardingEvent.created_at)
            .join(Onboarding, Onboarding.id == OnboardingEvent.onboarding_id)
            .join(JobApplication, JobApplication.id == Onboarding.application_id)
            .where(
                JobApplication.status == "active",
                JobApplication.job_id.in_(context.job_ids),
                OnboardingEvent.action == "onboarded",
                OnboardingEvent.created_at >= context.start_utc,
                OnboardingEvent.created_at < context.end_utc,
                OnboardingEvent.created_at <= context.as_of,
            )
        ).all()
        event_dates["offers_accepted"] = [_local_date(item) for item in accepted_at]
        event_dates["onboardings_completed"] = [
            _local_date(item) for item in onboarded_at
        ]

    counters = {
        key: Counter(values)
        for key, values in event_dates.items()
    }
    points = []
    for bucket_start, bucket_end in _bucket_ranges(
        context.query.start_date,
        context.query.end_date,
        interval,
    ):
        bucket_dates = (
            bucket_start + timedelta(days=offset)
            for offset in range((bucket_end - bucket_start).days + 1)
        )
        dates = tuple(bucket_dates)
        points.append(
            {
                "bucket_start": bucket_start,
                "bucket_end": bucket_end,
                "applications_created": sum(
                    counters["applications_created"][item] for item in dates
                ),
                "offers_accepted": sum(
                    counters["offers_accepted"][item] for item in dates
                ),
                "onboardings_completed": sum(
                    counters["onboardings_completed"][item] for item in dates
                ),
            }
        )
    return AnalyticsTrendResponse(
        meta=context.meta,
        interval=interval,
        points=points,
    )


def _first_timestamp_by_application(rows) -> dict[uuid.UUID, datetime]:
    timestamps: dict[uuid.UUID, datetime] = {}
    for application_id, occurred_at in rows:
        if occurred_at is None:
            continue
        occurred_at = _aware(occurred_at)
        current = timestamps.get(application_id)
        if current is None or occurred_at < current:
            timestamps[application_id] = occurred_at
    return timestamps


def _stage_timestamps(
    db: Session,
    context: AnalyticsContext,
) -> dict[str, dict[uuid.UUID, datetime]]:
    application_ids = context.application_ids
    timestamps: dict[str, dict[uuid.UUID, datetime]] = {
        key: {} for key in FUNNEL_STAGE_ORDER
    }
    timestamps["application_created"] = {
        item.id: item.created_at for item in context.applications
    }
    if not application_ids:
        return timestamps

    timestamps["ai_screening_completed"] = _first_timestamp_by_application(
        db.execute(
            select(ResumeDocument.application_id, ScreeningResult.completed_at)
            .join(ScreeningResult, ScreeningResult.document_id == ResumeDocument.id)
            .where(
                ResumeDocument.application_id.in_(application_ids),
                ScreeningResult.status == "completed",
                ScreeningResult.completed_at.is_not(None),
                ScreeningResult.completed_at <= context.as_of,
            )
        ).all()
    )
    timestamps["recruiter_shortlisted"] = _first_timestamp_by_application(
        db.execute(
            select(ResumeDocument.application_id, RecruiterDecision.created_at)
            .join(ScreeningResult, ScreeningResult.document_id == ResumeDocument.id)
            .join(
                RecruiterDecision,
                RecruiterDecision.screening_result_id == ScreeningResult.id,
            )
            .where(
                ResumeDocument.application_id.in_(application_ids),
                RecruiterDecision.decision == "shortlisted",
                RecruiterDecision.created_at <= context.as_of,
            )
        ).all()
    )
    timestamps["interview_started"] = _first_timestamp_by_application(
        db.execute(
            select(
                CandidateInterviewSchedule.application_id,
                CandidateInterviewSchedule.created_at,
            ).where(
                CandidateInterviewSchedule.application_id.in_(application_ids),
                CandidateInterviewSchedule.created_at <= context.as_of,
            )
        ).all()
    )
    timestamps["interview_passed"] = _first_timestamp_by_application(
        db.execute(
            select(InterviewReport.application_id, InterviewReport.confirmed_at)
            .join(
                InterviewReportVersion,
                and_(
                    InterviewReportVersion.report_id == InterviewReport.id,
                    InterviewReportVersion.version_number
                    == InterviewReport.current_version_number,
                ),
            )
            .where(
                InterviewReport.application_id.in_(application_ids),
                InterviewReport.status == "confirmed",
                InterviewReport.confirmed_at.is_not(None),
                InterviewReport.confirmed_at <= context.as_of,
                InterviewReportVersion.conclusion.in_(("hire", "next_round")),
            )
        ).all()
    )
    timestamps["offer_approved"] = _first_timestamp_by_application(
        db.execute(
            select(Offer.application_id, OfferApproval.decided_at)
            .join(OfferVersion, OfferVersion.offer_id == Offer.id)
            .join(OfferApproval, OfferApproval.version_id == OfferVersion.id)
            .where(
                Offer.application_id.in_(application_ids),
                OfferApproval.decision == "approved",
                OfferApproval.decided_at <= context.as_of,
            )
        ).all()
    )
    timestamps["offer_accepted"] = _first_timestamp_by_application(
        db.execute(
            select(Offer.application_id, OfferResponse.responded_at)
            .join(OfferResponse, OfferResponse.offer_id == Offer.id)
            .where(
                Offer.application_id.in_(application_ids),
                OfferResponse.decision == "accepted",
                OfferResponse.responded_at <= context.as_of,
            )
        ).all()
    )
    timestamps["onboarding_completed"] = _first_timestamp_by_application(
        db.execute(
            select(Onboarding.application_id, OnboardingEvent.created_at)
            .join(OnboardingEvent, OnboardingEvent.onboarding_id == Onboarding.id)
            .where(
                Onboarding.application_id.in_(application_ids),
                OnboardingEvent.action == "onboarded",
                OnboardingEvent.created_at <= context.as_of,
            )
        ).all()
    )
    return timestamps


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def collect_stage_durations(
    db: Session,
    context: AnalyticsContext,
) -> AnalyticsStageDurationResponse:
    timestamps = _stage_timestamps(db, context)
    metrics = []
    total_excluded = 0
    for index, stage in enumerate(FUNNEL_STAGE_ORDER[:-1]):
        next_stage = FUNNEL_STAGE_ORDER[index + 1]
        durations: list[int] = []
        excluded_count = 0
        current_open_count = 0
        for application_id in context.application_ids:
            entered_at = timestamps[stage].get(application_id)
            next_at = timestamps[next_stage].get(application_id)
            if entered_at is not None and next_at is not None:
                seconds = round((next_at - entered_at).total_seconds())
                if seconds < 0:
                    excluded_count += 1
                else:
                    durations.append(seconds)
            elif entered_at is not None:
                current_open_count += 1
            elif next_at is not None:
                excluded_count += 1
        total_excluded += excluded_count
        metrics.append(
            StageDurationMetric(
                stage=stage,
                label=FUNNEL_STAGE_LABELS[stage],
                sample_size=len(durations),
                p50_seconds=_percentile(durations, 0.5),
                p90_seconds=_percentile(durations, 0.9),
                excluded_count=excluded_count,
                current_open_count=current_open_count,
            )
        )
    return AnalyticsStageDurationResponse(
        meta=context.meta,
        quality={
            "complete": total_excluded == 0,
            "excluded_count": total_excluded,
            "reasons": (
                [] if total_excluded == 0 else ["阶段事件缺失或时间顺序异常"]
            ),
        },
        stages=metrics,
    )


def collect_interviews(
    db: Session,
    context: AnalyticsContext,
) -> AnalyticsInterviewResponse:
    submitted_rounds: list[bool] = []
    report_conclusions: list[str | None] = []
    if context.application_ids:
        submitted_rounds = list(
            db.scalars(
                select(InterviewEvaluation.passed)
                .join(
                    CandidateInterviewRound,
                    CandidateInterviewRound.id == InterviewEvaluation.candidate_round_id,
                )
                .join(
                    CandidateInterviewSchedule,
                    CandidateInterviewSchedule.id == CandidateInterviewRound.schedule_id,
                )
                .where(
                    CandidateInterviewSchedule.application_id.in_(context.application_ids),
                    InterviewEvaluation.status == "submitted",
                    InterviewEvaluation.submitted_at.is_not(None),
                    InterviewEvaluation.submitted_at <= context.as_of,
                )
            ).all()
        )
        report_conclusions = list(
            db.scalars(
                select(InterviewReportVersion.conclusion)
                .join(InterviewReport, InterviewReport.id == InterviewReportVersion.report_id)
                .where(
                    InterviewReport.application_id.in_(context.application_ids),
                    InterviewReport.status == "confirmed",
                    InterviewReport.confirmed_at.is_not(None),
                    InterviewReport.confirmed_at <= context.as_of,
                    InterviewReportVersion.version_number
                    == InterviewReport.current_version_number,
                )
            ).all()
        )
    return AnalyticsInterviewResponse(
        meta=context.meta,
        round_pass_rate=_ratio(
            "interview_round_pass_rate",
            "面试轮次通过率",
            sum(item is True for item in submitted_rounds),
            len(submitted_rounds),
        ),
        candidate_pass_rate=_ratio(
            "interview_candidate_pass_rate",
            "候选人面试通过率",
            sum(item in ("hire", "next_round") for item in report_conclusions),
            len(report_conclusions),
        ),
    )


def _approved_offer_application_ids(
    db: Session,
    context: AnalyticsContext,
) -> set[uuid.UUID]:
    if not context.application_ids:
        return set()
    return _application_id_set(
        db,
        select(Offer.application_id)
        .join(OfferVersion, OfferVersion.offer_id == Offer.id)
        .join(OfferApproval, OfferApproval.version_id == OfferVersion.id)
        .where(
            Offer.application_id.in_(context.application_ids),
            OfferApproval.decision == "approved",
            OfferApproval.decided_at <= context.as_of,
        ),
    )


def _accepted_offer_application_ids(
    db: Session,
    context: AnalyticsContext,
) -> set[uuid.UUID]:
    if not context.application_ids:
        return set()
    return _application_id_set(
        db,
        select(Offer.application_id)
        .join(OfferResponse, OfferResponse.offer_id == Offer.id)
        .where(
            Offer.application_id.in_(context.application_ids),
            OfferResponse.decision == "accepted",
            OfferResponse.responded_at <= context.as_of,
        ),
    )


def collect_offers(db: Session, context: AnalyticsContext) -> AnalyticsOfferResponse:
    statuses: list[str] = []
    if context.application_ids:
        statuses = list(
            db.scalars(
                select(Offer.status).where(Offer.application_id.in_(context.application_ids))
            ).all()
        )
    counts = Counter(statuses)
    approved = _approved_offer_application_ids(db, context)
    accepted = _accepted_offer_application_ids(db, context) & approved
    labels = {
        "draft": "草稿",
        "pending_manager_confirmation": "待用人经理确认",
        "pending_approval": "待审批",
        "approved": "已批准",
        "rejected": "已驳回",
        "pending_response": "待候选人回应",
        "accepted": "已接受",
        "declined": "已拒绝",
    }
    return AnalyticsOfferResponse(
        meta=context.meta,
        total_offers=len(statuses),
        statuses=[
            OfferStatusMetric(key=key, label=labels[key], count=counts[key])
            for key in OFFER_STATUS_ORDER
        ],
        acceptance_rate=_ratio(
            "offer_acceptance_rate",
            "Offer 接受率",
            len(accepted),
            len(approved),
        ),
    )


def collect_onboardings(
    db: Session,
    context: AnalyticsContext,
) -> AnalyticsOnboardingResponse:
    rows: list[tuple[str, str | None]] = []
    if context.application_ids:
        rows = list(
            db.execute(
                select(Onboarding.status, Onboarding.abandonment_source).where(
                    Onboarding.application_id.in_(context.application_ids)
                )
            ).all()
        )
    status_counts = Counter(row[0] for row in rows)
    abandonment_counts = Counter(row[1] for row in rows if row[0] == "abandoned")
    accepted = _accepted_offer_application_ids(db, context)
    onboarded: set[uuid.UUID] = set()
    if context.application_ids:
        onboarded = set(
            db.scalars(
                select(Onboarding.application_id).where(
                    Onboarding.application_id.in_(context.application_ids),
                    Onboarding.status == "onboarded",
                )
            ).all()
        )
    status_labels = {
        "pending_confirmation": "待确认",
        "candidate_proposed_date": "候选人已提日期",
        "pending_start": "待入职",
        "onboarded": "已入职",
        "abandoned": "放弃入职",
    }
    abandonment_labels = {
        "candidate_withdrew": "候选人放弃",
        "company_cancelled": "公司取消",
        "other": "其他",
    }
    return AnalyticsOnboardingResponse(
        meta=context.meta,
        total_records=len(rows),
        statuses=[
            OnboardingStatusMetric(
                key=key,
                label=status_labels[key],
                count=status_counts[key],
            )
            for key in ONBOARDING_STATUS_ORDER
        ],
        completion_rate=_ratio(
            "onboarding_completion_rate",
            "入职完成率",
            len(onboarded & accepted),
            len(accepted),
        ),
        abandonment_sources=[
            OnboardingAbandonmentMetric(
                key=key,
                label=abandonment_labels[key],
                count=abandonment_counts[key],
            )
            for key in ("candidate_withdrew", "company_cancelled", "other")
            if abandonment_counts[key] > 0
        ],
    )


def collect_decision_differences(
    db: Session,
    context: AnalyticsContext,
) -> AnalyticsDecisionDifferenceResponse:
    latest_results: dict[
        uuid.UUID, tuple[uuid.UUID, str, datetime, int]
    ] = {}
    if context.application_ids:
        result_rows = db.execute(
            select(
                ResumeDocument.application_id,
                ScreeningResult.id,
                ScreeningResult.ai_group,
                ScreeningResult.completed_at,
                ScreeningResult.analysis_version,
            )
            .join(ScreeningResult, ScreeningResult.document_id == ResumeDocument.id)
            .where(
                ResumeDocument.application_id.in_(context.application_ids),
                ScreeningResult.status == "completed",
                ScreeningResult.ai_group.is_not(None),
                ScreeningResult.completed_at.is_not(None),
                ScreeningResult.completed_at <= context.as_of,
            )
        ).all()
        for application_id, result_id, ai_group, completed_at, version in result_rows:
            candidate = (result_id, ai_group, _aware(completed_at), version)
            current = latest_results.get(application_id)
            if current is None or (candidate[2], candidate[3], str(candidate[0])) > (
                current[2],
                current[3],
                str(current[0]),
            ):
                latest_results[application_id] = candidate

    result_to_application = {
        result[0]: application_id for application_id, result in latest_results.items()
    }
    decisions: dict[uuid.UUID, list[tuple[str, datetime]]] = {
        application_id: [] for application_id in latest_results
    }
    if result_to_application:
        for result_id, decision, created_at in db.execute(
            select(
                RecruiterDecision.screening_result_id,
                RecruiterDecision.decision,
                RecruiterDecision.created_at,
            ).where(
                RecruiterDecision.screening_result_id.in_(result_to_application),
                RecruiterDecision.created_at <= context.as_of,
            )
        ).all():
            decisions[result_to_application[result_id]].append(
                (decision, _aware(created_at))
            )

    cutoff_rows = []
    if latest_results:
        cutoff_rows.extend(
            db.execute(
                select(
                    CandidateInterviewSchedule.application_id,
                    CandidateInterviewSchedule.created_at,
                ).where(
                    CandidateInterviewSchedule.application_id.in_(latest_results),
                    CandidateInterviewSchedule.created_at <= context.as_of,
                )
            ).all()
        )
        cutoff_rows.extend(
            db.execute(
                select(Offer.application_id, Offer.created_at).where(
                    Offer.application_id.in_(latest_results),
                    Offer.created_at <= context.as_of,
                )
            ).all()
        )
    cutoffs = _first_timestamp_by_application(cutoff_rows)

    baseline = {"auto_rejected": 0, "low_match": 1, "passed": 2}
    human_rank = {"rejected": 0, "pending": 1, "shortlisted": 2}
    counts = Counter()
    for application_id, (_, ai_group, _, _) in latest_results.items():
        cutoff = cutoffs.get(application_id, context.as_of)
        eligible = [item for item in decisions[application_id] if item[1] <= cutoff]
        if not eligible:
            counts["missing_human_decision"] += 1
            continue
        human_decision = max(eligible, key=lambda item: item[1])[0]
        difference = human_rank[human_decision] - baseline[ai_group]
        if difference == 0:
            counts["consistent"] += 1
        elif difference > 0:
            counts["human_upgraded"] += 1
        else:
            counts["human_downgraded"] += 1

    total = len(latest_results)
    labels = {
        "consistent": "一致",
        "human_upgraded": "人工上调",
        "human_downgraded": "人工下调",
        "missing_human_decision": "缺少人工决定",
    }
    return AnalyticsDecisionDifferenceResponse(
        meta=context.meta,
        ai_screened_count=total,
        categories=[
            DecisionDifferenceMetric(
                key=key,
                label=labels[key],
                count=counts[key],
                percentage=(
                    None if total == 0 else round(counts[key] / total * 100, 1)
                ),
            )
            for key in DECISION_DIFFERENCE_ORDER
        ],
    )


def collect_job_options(db: Session, user: User) -> list[AnalyticsJobOption]:
    rows = db.execute(
        select(Job.id, Job.title, Job.status)
        .where(visible_job_clause(user))
        .order_by(Job.status, Job.title, Job.id)
    ).all()
    return [
        AnalyticsJobOption(id=row.id, title=row.title, status=row.status)
        for row in rows
    ]


def collect_dashboard(
    db: Session,
    user: User,
    query: AnalyticsQuery,
    *,
    as_of: datetime,
    interval: str,
) -> AnalyticsDashboardResponse:
    context = build_analytics_context(db, user, query, as_of=as_of)
    return AnalyticsDashboardResponse(
        meta=context.meta,
        jobs=collect_job_options(db, user),
        overview=collect_overview(db, context),
        funnel=collect_funnel(db, context),
        current_distribution=collect_current_distribution(db, context),
        trend=collect_trend(db, context, interval=interval),
        stage_duration=collect_stage_durations(db, context),
        interviews=collect_interviews(db, context),
        offers=collect_offers(db, context),
        onboardings=collect_onboardings(db, context),
        decision_difference=collect_decision_differences(db, context),
    )
