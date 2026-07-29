from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import Job, User, UserRole
from app.schemas.analytics import AnalyticsQuery
from app.services.analytics import collect_dashboard

BENCHMARK_USER_ID = uuid.UUID("ffffffff-ffff-4fff-8fff-000000000001")


@dataclass(frozen=True)
class BenchmarkConfig:
    job_count: int = 100
    application_count: int = 10_000
    process_events_per_application: int = 3
    warmup_runs: int = 3
    sample_runs: int = 20
    dashboard_p95_limit_ms: float = 2_000
    list_p95_limit_ms: float = 500

    def validate(self) -> None:
        if self.job_count < 1:
            raise ValueError("职位数量必须大于 0")
        if self.application_count < self.job_count:
            raise ValueError("应聘数量不能少于职位数量")
        if self.process_events_per_application != 3:
            raise ValueError("F23 固定基准要求每条应聘生成 3 条流程事件")
        if self.warmup_runs < 1 or self.sample_runs < 2:
            raise ValueError("基准至少需要 1 次预热和 2 次采样")

    @property
    def process_event_count(self) -> int:
        return self.application_count * self.process_events_per_application


def database_name_is_safe(database_url: str) -> bool:
    database = make_url(database_url).database or ""
    return database.endswith("_benchmark")


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        raise ValueError("无法计算空样本的百分位")
    if not 0 < ratio <= 1:
        raise ValueError("百分位比例必须在 0 到 1 之间")
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * ratio) - 1)
    return ordered[index]


def _execute(db: Session, statement: str, **parameters: object) -> None:
    db.execute(text(statement), parameters)


def _assert_empty(db: Session) -> None:
    counts = db.execute(
        text(
            "SELECT "
            "(SELECT count(*) FROM jobs), "
            "(SELECT count(*) FROM job_applications), "
            "(SELECT count(*) FROM candidate_process_events)"
        )
    ).one()
    if any(counts):
        raise RuntimeError("基准数据库必须是迁移完成后的空业务库")


def seed_benchmark_data(db: Session, config: BenchmarkConfig) -> None:
    config.validate()
    _assert_empty(db)
    common = {
        "job_count": config.job_count,
        "application_count": config.application_count,
        "user_id": BENCHMARK_USER_ID,
    }

    _execute(
        db,
        """
        INSERT INTO users (
            id, username, password_hash, display_name, is_active,
            must_change_password, session_version
        ) VALUES (
            :user_id, 'analytics-benchmark-admin', 'benchmark-only',
            '分析基准管理员', true, false, 1
        )
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO user_roles (user_id, role_id)
        SELECT :user_id, id FROM roles WHERE key = 'administrator'
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO jobs (id, owner_id, title, department, original_jd, status)
        SELECT
            CAST(md5('benchmark-job-' || value::text) AS uuid),
            :user_id,
            '基准职位 ' || value,
            '招聘平台',
            '用于 F23 招聘分析性能验收',
            CASE WHEN value % 10 = 0 THEN 'archived' ELSE 'active' END
        FROM generate_series(1, :job_count) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO job_criteria_versions (
            id, job_id, version_number, status, pass_threshold,
            confirmed_by_id, confirmed_at
        )
        SELECT
            CAST(md5('benchmark-criteria-' || value::text) AS uuid),
            CAST(md5('benchmark-job-' || value::text) AS uuid),
            1, 'confirmed', 60, :user_id, CURRENT_TIMESTAMP
        FROM generate_series(1, :job_count) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO screening_batches (
            id, job_id, criteria_version_id, name, status, ai_input_mode
        )
        SELECT
            CAST(md5('benchmark-batch-' || value::text) AS uuid),
            CAST(md5('benchmark-job-' || value::text) AS uuid),
            CAST(md5('benchmark-criteria-' || value::text) AS uuid),
            '分析基准批次', 'completed', 'raw'
        FROM generate_series(1, :job_count) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO interview_plan_versions (
            id, job_id, version_number, status, confirmed_by_id, confirmed_at
        )
        SELECT
            CAST(md5('benchmark-plan-' || value::text) AS uuid),
            CAST(md5('benchmark-job-' || value::text) AS uuid),
            1, 'confirmed', :user_id, CURRENT_TIMESTAMP
        FROM generate_series(1, :job_count) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO interview_rounds (
            id, plan_version_id, name, round_type, duration_minutes,
            pass_threshold, focus, sort_order
        )
        SELECT
            CAST(md5('benchmark-plan-round-' || value::text) AS uuid),
            CAST(md5('benchmark-plan-' || value::text) AS uuid),
            '综合面试', 'technical', 60, 60, '综合能力', 0
        FROM generate_series(1, :job_count) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO candidates (id, full_name, status)
        SELECT
            CAST(md5('benchmark-candidate-' || value::text) AS uuid),
            '基准候选人 ' || value,
            'active'
        FROM generate_series(1, :application_count) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO job_applications (
            id, candidate_id, job_id, status, created_at, updated_at
        )
        SELECT
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            CAST(md5('benchmark-candidate-' || value::text) AS uuid),
            CAST(md5(
                'benchmark-job-' || (((value - 1) % :job_count) + 1)::text
            ) AS uuid),
            'active',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '8 hours',
            CURRENT_TIMESTAMP
        FROM generate_series(1, :application_count) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO candidate_processes (
            id, application_id, current_stage, stage_entered_at
        )
        SELECT
            CAST(md5('benchmark-process-' || value::text) AS uuid),
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            CASE
                WHEN value % 32 = 0 THEN 'onboarding_completed'
                WHEN value % 16 = 0 THEN 'onboarding_pending_start'
                WHEN value % 8 = 0 THEN 'offer_pending_response'
                ELSE 'to_interview'
            END,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '5 hours'
        FROM generate_series(1, :application_count) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO candidate_process_events (
            id, process_id, sequence_number, from_stage, to_stage,
            reason, operator_id, created_at
        )
        SELECT
            CAST(md5(
                'benchmark-process-event-' || application_number::text || '-' || sequence::text
            ) AS uuid),
            CAST(md5('benchmark-process-' || application_number::text) AS uuid),
            sequence,
            CASE sequence
                WHEN 1 THEN 'unprocessed'
                WHEN 2 THEN 'pending'
                ELSE 'shortlisted'
            END,
            CASE sequence
                WHEN 1 THEN 'pending'
                WHEN 2 THEN 'shortlisted'
                ELSE 'to_interview'
            END,
            'F23 固定性能基准',
            :user_id,
            CURRENT_TIMESTAMP - ((application_number % 28)::text || ' days')::interval
                - interval '8 hours' + sequence * interval '1 hour'
        FROM generate_series(1, :application_count) AS application_number
        CROSS JOIN generate_series(1, 3) AS sequence
        """,
        **common,
    )

    _seed_screening_data(db, common)
    _seed_interview_data(db, common)
    _seed_offer_and_onboarding_data(db, common)
    db.commit()
    db.execute(text("ANALYZE"))
    db.commit()


def _seed_screening_data(db: Session, common: dict[str, object]) -> None:
    _execute(
        db,
        """
        INSERT INTO resume_documents (
            id, batch_id, candidate_id, application_id, original_filename,
            file_extension, content_type, detected_type, size_bytes, status,
            attempt_count, extraction_method, parsed_at, redacted_at, created_at
        )
        SELECT
            CAST(md5('benchmark-document-' || value::text) AS uuid),
            CAST(md5(
                'benchmark-batch-' || (((value - 1) % :job_count) + 1)::text
            ) AS uuid),
            CAST(md5('benchmark-candidate-' || value::text) AS uuid),
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            'benchmark-' || value || '.pdf', '.pdf', 'application/pdf',
            'pdf', 1024, 'completed', 1, 'text',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '7 hours',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '7 hours',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '8 hours'
        FROM generate_series(2, :application_count, 2) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO application_resume_documents (
            application_id, document_id, created_at
        )
        SELECT
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            CAST(md5('benchmark-document-' || value::text) AS uuid),
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '8 hours'
        FROM generate_series(2, :application_count, 2) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        UPDATE job_applications AS application
        SET primary_document_id = source.document_id
        FROM (
            SELECT
                CAST(md5('benchmark-application-' || value::text) AS uuid)
                    AS application_id,
                CAST(md5('benchmark-document-' || value::text) AS uuid)
                    AS document_id
            FROM generate_series(2, :application_count, 2) AS value
        ) AS source
        WHERE application.id = source.application_id
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO screening_results (
            id, application_id, document_id, criteria_version_id,
            analysis_version, status, ai_group, total_score, pass_threshold,
            hard_requirement_results, strengths, gaps, missing_items,
            interview_questions, model_name, prompt_version, started_at,
            completed_at, created_at
        )
        SELECT
            CAST(md5('benchmark-screening-' || value::text) AS uuid),
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            CAST(md5('benchmark-document-' || value::text) AS uuid),
            CAST(md5(
                'benchmark-criteria-' || (((value - 1) % :job_count) + 1)::text
            ) AS uuid),
            1, 'completed',
            CASE WHEN value % 6 = 0 THEN 'low_match' ELSE 'passed' END,
            CASE WHEN value % 6 = 0 THEN 55 ELSE 85 END,
            60, '[]'::json, '[]'::json, '[]'::json, '[]'::json, '[]'::json,
            'benchmark-model', 'v1',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '7 hours 5 minutes',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '7 hours',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '7 hours'
        FROM generate_series(2, :application_count, 2) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO recruiter_decisions (
            id, screening_result_id, operator_id, sequence_number,
            previous_decision, decision, reason, is_auto_rejection_override,
            created_at
        )
        SELECT
            CAST(md5('benchmark-decision-' || value::text) AS uuid),
            CAST(md5('benchmark-screening-' || value::text) AS uuid),
            :user_id, 1, 'unprocessed',
            CASE WHEN value % 10 = 0 THEN 'pending' ELSE 'shortlisted' END,
            'F23 固定性能基准', false,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '6 hours'
        FROM generate_series(2, :application_count, 2) AS value
        """,
        **common,
    )


def _seed_interview_data(db: Session, common: dict[str, object]) -> None:
    _execute(
        db,
        """
        INSERT INTO candidate_interview_schedules (
            id, application_id, plan_version_id, status, created_by_id, created_at
        )
        SELECT
            CAST(md5('benchmark-schedule-' || value::text) AS uuid),
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            CAST(md5(
                'benchmark-plan-' || (((value - 1) % :job_count) + 1)::text
            ) AS uuid),
            'scheduled', :user_id,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '5 hours'
        FROM generate_series(4, :application_count, 4) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO candidate_interview_rounds (
            id, schedule_id, plan_round_id, sort_order, scheduled_start_at,
            interview_method, status, reschedule_count, created_at
        )
        SELECT
            CAST(md5('benchmark-candidate-round-' || value::text) AS uuid),
            CAST(md5('benchmark-schedule-' || value::text) AS uuid),
            CAST(md5(
                'benchmark-plan-round-' || (((value - 1) % :job_count) + 1)::text
            ) AS uuid),
            0,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '4 hours',
            'online', 'scheduled', 0,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '5 hours'
        FROM generate_series(4, :application_count, 4) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO interview_evaluations (
            id, candidate_round_id, status, overall_recommendation,
            overall_comment, total_score, passed, submitted_by_id,
            submitted_at, created_at
        )
        SELECT
            CAST(md5('benchmark-evaluation-' || value::text) AS uuid),
            CAST(md5('benchmark-candidate-round-' || value::text) AS uuid),
            'submitted',
            CASE WHEN value % 12 = 0 THEN 'reserve' ELSE 'recommend' END,
            'F23 固定性能基准',
            CASE WHEN value % 12 = 0 THEN 58 ELSE 82 END,
            value % 12 <> 0, :user_id,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '3 hours',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '4 hours'
        FROM generate_series(4, :application_count, 4) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO interview_reports (
            id, application_id, status, current_version_number,
            created_by_id, confirmed_by_id, confirmed_at, created_at
        )
        SELECT
            CAST(md5('benchmark-report-' || value::text) AS uuid),
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            'confirmed', 1, :user_id, :user_id,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '2 hours',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '3 hours'
        FROM generate_series(4, :application_count, 4) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO interview_report_versions (
            id, report_id, version_number, idempotency_key, generation_mode,
            conclusion, executive_summary, strengths, concerns,
            follow_up_actions, evaluation_ids, evidence_snapshot,
            missing_rounds, created_by_id, created_by_username,
            created_by_display_name, created_at
        )
        SELECT
            CAST(md5('benchmark-report-version-' || value::text) AS uuid),
            CAST(md5('benchmark-report-' || value::text) AS uuid),
            1, CAST(md5('benchmark-report-key-' || value::text) AS uuid),
            'manual',
            CASE WHEN value % 12 = 0 THEN 'reserve' ELSE 'hire' END,
            'F23 固定性能基准', '[]'::json, '[]'::json, '[]'::json,
            '[]'::json, '{}'::json, '[]'::json,
            :user_id, 'analytics-benchmark-admin', '分析基准管理员',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '3 hours'
        FROM generate_series(4, :application_count, 4) AS value
        """,
        **common,
    )


def _seed_offer_and_onboarding_data(
    db: Session,
    common: dict[str, object],
) -> None:
    _execute(
        db,
        """
        INSERT INTO offers (
            id, application_id, status, current_version_number,
            created_by_id, created_at
        )
        SELECT
            CAST(md5('benchmark-offer-' || value::text) AS uuid),
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            CASE WHEN value % 16 = 0 THEN 'accepted' ELSE 'approved' END,
            1, :user_id,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '90 minutes'
        FROM generate_series(8, :application_count, 8) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO offer_versions (
            id, offer_id, version_number, idempotency_key,
            submission_idempotency_key, submitted_at, currency,
            monthly_salary, annual_salary_months, probation_months,
            bonus_description, expected_start_date, valid_until, notes,
            created_by_id, created_by_username, created_by_display_name,
            created_at
        )
        SELECT
            CAST(md5('benchmark-offer-version-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-' || value::text) AS uuid),
            1, CAST(md5('benchmark-offer-version-key-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-submit-key-' || value::text) AS uuid),
            CURRENT_TIMESTAMP - interval '2 hours',
            'CNY', 30000, 13, 0, '',
            CURRENT_DATE + 30, CURRENT_DATE + 10, '',
            :user_id, 'analytics-benchmark-admin', '分析基准管理员',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '90 minutes'
        FROM generate_series(8, :application_count, 8) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO offer_approvals (
            id, version_id, idempotency_key, approver_id,
            approver_username, approver_display_name, decision,
            comment, decided_at
        )
        SELECT
            CAST(md5('benchmark-offer-approval-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-version-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-approval-key-' || value::text) AS uuid),
            :user_id, 'analytics-benchmark-admin', '分析基准管理员',
            'approved', '',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '1 hour'
        FROM generate_series(8, :application_count, 8) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO offer_portal_links (
            id, offer_id, version_id, idempotency_key, token_hash,
            verification_phone_digest, expires_at, created_by_id,
            created_by_username, created_by_display_name, created_at
        )
        SELECT
            CAST(md5('benchmark-link-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-version-' || value::text) AS uuid),
            CAST(md5('benchmark-link-key-' || value::text) AS uuid),
            md5('benchmark-token-a-' || value::text)
                || md5('benchmark-token-b-' || value::text),
            md5('benchmark-phone-a-' || value::text)
                || md5('benchmark-phone-b-' || value::text),
            CURRENT_TIMESTAMP + interval '10 days',
            :user_id, 'analytics-benchmark-admin', '分析基准管理员',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '50 minutes'
        FROM generate_series(16, :application_count, 16) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO offer_responses (
            id, offer_id, version_id, portal_link_id, idempotency_key,
            decision, verification_completed_at, responded_at
        )
        SELECT
            CAST(md5('benchmark-response-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-version-' || value::text) AS uuid),
            CAST(md5('benchmark-link-' || value::text) AS uuid),
            CAST(md5('benchmark-response-key-' || value::text) AS uuid),
            'accepted',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '40 minutes',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '40 minutes'
        FROM generate_series(16, :application_count, 16) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO onboardings (
            id, application_id, offer_id, offer_response_id, status,
            confirmed_start_date, actual_start_date, version,
            created_at, updated_at
        )
        SELECT
            CAST(md5('benchmark-onboarding-' || value::text) AS uuid),
            CAST(md5('benchmark-application-' || value::text) AS uuid),
            CAST(md5('benchmark-offer-' || value::text) AS uuid),
            CAST(md5('benchmark-response-' || value::text) AS uuid),
            CASE WHEN value % 32 = 0 THEN 'onboarded' ELSE 'pending_start' END,
            CURRENT_DATE + 30,
            CASE WHEN value % 32 = 0 THEN CURRENT_DATE ELSE NULL END,
            1,
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '30 minutes',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '10 minutes'
        FROM generate_series(16, :application_count, 16) AS value
        """,
        **common,
    )
    _execute(
        db,
        """
        INSERT INTO onboarding_events (
            id, onboarding_id, sequence_number, idempotency_key, action,
            from_status, to_status, date_after, actor_type,
            actor_user_id, actor_username, actor_display_name, created_at
        )
        SELECT
            CAST(md5('benchmark-onboarding-event-' || value::text) AS uuid),
            CAST(md5('benchmark-onboarding-' || value::text) AS uuid),
            1,
            CAST(md5('benchmark-onboarding-event-key-' || value::text) AS uuid),
            'onboarded', 'pending_start', 'onboarded', CURRENT_DATE,
            'recruiter', :user_id, 'analytics-benchmark-admin',
            '分析基准管理员',
            CURRENT_TIMESTAMP - ((value % 28)::text || ' days')::interval
                - interval '10 minutes'
        FROM generate_series(32, :application_count, 32) AS value
        """,
        **common,
    )


def _timed_dashboard(
    db: Session,
    user: User,
    query: AnalyticsQuery,
    as_of: datetime,
) -> float:
    started = time.perf_counter()
    response = collect_dashboard(db, user, query, as_of=as_of, interval="day")
    if response.overview.application_count == 0:
        raise RuntimeError("基准查询没有命中应聘数据")
    return (time.perf_counter() - started) * 1_000


def _timed_job_list(db: Session) -> float:
    started = time.perf_counter()
    rows = db.execute(
        select(Job.id, Job.title, Job.status).order_by(Job.created_at.desc()).limit(100)
    ).all()
    if not rows:
        raise RuntimeError("基准职位列表为空")
    return (time.perf_counter() - started) * 1_000


def run_benchmark(engine: Engine, config: BenchmarkConfig) -> dict[str, object]:
    config.validate()
    with Session(engine) as db:
        user = db.scalar(
            select(User)
            .options(joinedload(User.role_assignments).joinedload(UserRole.role))
            .where(User.id == BENCHMARK_USER_ID)
        )
        if user is None:
            raise RuntimeError("基准管理员不存在，请先执行 --seed")

        today = date.today()
        query = AnalyticsQuery(start_date=today - timedelta(days=29), end_date=today)
        as_of = datetime.now(UTC)
        for _ in range(config.warmup_runs):
            _timed_dashboard(db, user, query, as_of)
            _timed_job_list(db)

        dashboard_samples = [
            _timed_dashboard(db, user, query, as_of)
            for _ in range(config.sample_runs)
        ]
        list_samples = [_timed_job_list(db) for _ in range(config.sample_runs)]
        counts = db.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM jobs) AS jobs, "
                "(SELECT count(*) FROM job_applications) AS applications, "
                "(SELECT count(*) FROM candidate_process_events) AS process_events, "
                "(SELECT count(*) FROM candidate_interview_schedules) AS interviews, "
                "(SELECT count(*) FROM offers) AS offers, "
                "(SELECT count(*) FROM onboardings) AS onboardings"
            )
        ).mappings().one()

    dashboard_p95 = percentile(dashboard_samples, 0.95)
    list_p95 = percentile(list_samples, 0.95)
    return {
        "config": asdict(config),
        "counts": dict(counts),
        "dashboard_ms": {
            "p50": round(percentile(dashboard_samples, 0.5), 2),
            "p95": round(dashboard_p95, 2),
            "max": round(max(dashboard_samples), 2),
        },
        "job_list_ms": {
            "p50": round(percentile(list_samples, 0.5), 2),
            "p95": round(list_p95, 2),
            "max": round(max(list_samples), 2),
        },
        "passed": (
            dashboard_p95 < config.dashboard_p95_limit_ms
            and list_p95 < config.list_p95_limit_ms
        ),
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="F23 招聘分析固定规模性能基准")
    parser.add_argument("--seed", action="store_true", help="向空基准库生成固定数据")
    parser.add_argument("--warmup-runs", type=int, default=3)
    parser.add_argument("--sample-runs", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if settings.is_production or not database_name_is_safe(settings.database_url):
        raise RuntimeError("性能基准只允许在名称以 _benchmark 结尾的非生产数据库运行")
    config = BenchmarkConfig(
        warmup_runs=args.warmup_runs,
        sample_runs=args.sample_runs,
    )
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    if args.seed:
        with Session(engine) as db:
            seed_benchmark_data(db, config)
    result = run_benchmark(engine, config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
