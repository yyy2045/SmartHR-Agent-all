import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.config import settings
from app.database import get_db
from app.models import (
    CandidateInterviewRound,
    CandidateInterviewSchedule,
    InterviewDimensionRating,
    InterviewEvaluation,
    InterviewQuestionResponse,
    InterviewReport,
    InterviewReportVersion,
    Job,
    JobApplication,
    ScreeningResult,
    User,
)
from app.schemas.interview_report import (
    InterviewReportConfirmRequest,
    InterviewReportContent,
    InterviewReportContextResponse,
    InterviewReportCreateRequest,
    InterviewReportGenerateRequest,
    InterviewReportResponse,
    InterviewReportSummaryResponse,
    InterviewReportUpdateRequest,
    InterviewReportVersionResponse,
    ReportDimensionEvidenceResponse,
    ReportMissingRoundResponse,
    ReportQuestionEvidenceResponse,
    ReportScreeningCitationResponse,
    ReportScreeningEvidenceResponse,
    ReportSubmittedEvaluationResponse,
)
from app.schemas.recruitment_knowledge import (
    RecruitmentKnowledgeRetrievalCitation,
    RecruitmentKnowledgeRetrievalRequest,
)
from app.services.ai_client import (
    INTERVIEW_REPORT_PROMPT_VERSION,
    MAX_MODEL_RETRIES,
    AIClientError,
    AIConfigurationError,
    AIRequestTimeout,
    AIResponseValidationError,
    AIUpstreamError,
    OpenAICompatibleClient,
    get_ai_client,
)
from app.services.ai_observability import record_ai_call_in_session
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job
from app.services.embedding_client import EmbeddingClientError
from app.services.prompt_templates import get_published_prompt_snapshot
from app.services.recruitment_knowledge import retrieve_recruitment_knowledge

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
AIClient = Annotated[OpenAICompatibleClient, Depends(get_ai_client)]

_REPORT_LOAD_OPTIONS = (
    selectinload(InterviewReport.application).selectinload(JobApplication.candidate),
    selectinload(InterviewReport.application).selectinload(JobApplication.job),
    selectinload(InterviewReport.versions),
)
_CONTENT_FIELDS = (
    "conclusion",
    "executive_summary",
    "strengths",
    "concerns",
    "follow_up_actions",
)


def _get_application(
    db: Session,
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    user: User,
    *,
    for_update: bool = False,
) -> tuple[Job, JobApplication]:
    job = get_visible_job(db, job_id, user)
    query = (
        select(JobApplication)
        .where(
            JobApplication.id == application_id,
            JobApplication.job_id == job_id,
        )
        .options(
            selectinload(JobApplication.candidate),
            selectinload(JobApplication.job),
        )
    )
    if for_update:
        query = query.with_for_update()
    application = db.scalar(query)
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="职位应聘记录不存在",
        )
    return job, application


def _latest_screening_result(
    db: Session, application_id: uuid.UUID
) -> ScreeningResult | None:
    return db.scalar(
        select(ScreeningResult)
        .where(
            ScreeningResult.application_id == application_id,
            ScreeningResult.status == "completed",
        )
        .options(
            selectinload(ScreeningResult.evidence_citations),
            selectinload(ScreeningResult.recruiter_decisions),
        )
        .order_by(
            ScreeningResult.completed_at.desc().nulls_last(),
            ScreeningResult.created_at.desc(),
            ScreeningResult.analysis_version.desc(),
            ScreeningResult.id,
        )
        .limit(1)
    )


def _screening_response(
    result: ScreeningResult | None,
) -> ReportScreeningEvidenceResponse | None:
    if result is None:
        return None
    current_decision = (
        result.recruiter_decisions[-1].decision
        if result.recruiter_decisions
        else "unprocessed"
    )
    return ReportScreeningEvidenceResponse(
        id=result.id,
        document_id=result.document_id,
        criteria_version_id=result.criteria_version_id,
        analysis_version=result.analysis_version,
        ai_group=result.ai_group,
        total_score=result.total_score,
        pass_threshold=result.pass_threshold,
        current_decision=current_decision,
        strengths=result.strengths,
        gaps=result.gaps,
        missing_items=result.missing_items,
        completed_at=result.completed_at,
        citations=[
            ReportScreeningCitationResponse(
                id=item.id,
                subject_type=item.subject_type,
                subject_key=item.subject_key,
                quote=item.quote,
                source_type=item.source_type,
                page_number=item.page_number,
                paragraph_index=item.paragraph_index,
            )
            for item in result.evidence_citations
        ],
    )


def _load_interview_rounds(
    db: Session, application_id: uuid.UUID
) -> list[CandidateInterviewRound]:
    return list(
        db.scalars(
            select(CandidateInterviewRound)
            .join(
                CandidateInterviewSchedule,
                CandidateInterviewRound.schedule_id == CandidateInterviewSchedule.id,
            )
            .where(CandidateInterviewSchedule.application_id == application_id)
            .options(
                selectinload(CandidateInterviewRound.plan_round),
                selectinload(CandidateInterviewRound.evaluation)
                .selectinload(InterviewEvaluation.question_responses)
                .selectinload(InterviewQuestionResponse.question),
                selectinload(CandidateInterviewRound.evaluation)
                .selectinload(InterviewEvaluation.dimension_ratings)
                .selectinload(InterviewDimensionRating.dimension),
            )
            .order_by(CandidateInterviewRound.sort_order, CandidateInterviewRound.id)
        ).all()
    )


def _evaluation_response(
    round_item: CandidateInterviewRound,
) -> ReportSubmittedEvaluationResponse:
    evaluation = round_item.evaluation
    if (
        evaluation is None
        or evaluation.status != "submitted"
        or evaluation.overall_recommendation is None
        or evaluation.submitted_at is None
    ):
        raise RuntimeError("面试轮次没有完整的已提交评价")
    return ReportSubmittedEvaluationResponse(
        evaluation_id=evaluation.id,
        round_id=round_item.id,
        round_name=round_item.plan_round.name,
        round_type=round_item.plan_round.round_type,
        sort_order=round_item.sort_order,
        total_score=evaluation.total_score,
        passed=evaluation.passed,
        overall_recommendation=evaluation.overall_recommendation,
        overall_comment=evaluation.overall_comment,
        submitted_at=evaluation.submitted_at,
        question_responses=[
            ReportQuestionEvidenceResponse(
                question_id=item.question_id,
                question_text=item.question.question_text,
                answer_summary=item.answer_summary,
                evidence=item.evidence,
            )
            for item in sorted(
                evaluation.question_responses,
                key=lambda response: (response.question.sort_order, response.id),
            )
        ],
        dimension_ratings=[
            ReportDimensionEvidenceResponse(
                dimension_id=item.dimension_id,
                dimension_name=item.dimension.name,
                score=item.score,
                evidence=item.evidence,
            )
            for item in sorted(
                evaluation.dimension_ratings,
                key=lambda rating: (rating.dimension.sort_order, rating.id),
            )
        ],
    )


def _context_response(
    db: Session,
    job: Job,
    application: JobApplication,
) -> InterviewReportContextResponse:
    submitted_evaluations: list[ReportSubmittedEvaluationResponse] = []
    missing_rounds: list[ReportMissingRoundResponse] = []
    for round_item in _load_interview_rounds(db, application.id):
        if round_item.evaluation is not None and round_item.evaluation.status == "submitted":
            submitted_evaluations.append(_evaluation_response(round_item))
            continue
        missing_rounds.append(
            ReportMissingRoundResponse(
                round_id=round_item.id,
                round_name=round_item.plan_round.name,
                round_type=round_item.plan_round.round_type,
                sort_order=round_item.sort_order,
                round_status=round_item.status,
                reason=("cancelled" if round_item.status == "cancelled" else "not_submitted"),
            )
        )

    return InterviewReportContextResponse(
        application_id=application.id,
        application_status=application.status,
        job_id=job.id,
        job_title=job.title,
        candidate_id=application.candidate_id,
        candidate_code=application.candidate.candidate_code,
        candidate_name=application.candidate.full_name,
        latest_screening=_screening_response(
            _latest_screening_result(db, application.id)
        ),
        submitted_evaluations=submitted_evaluations,
        missing_rounds=missing_rounds,
    )


def _load_report(
    db: Session,
    application_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> InterviewReport | None:
    query = (
        select(InterviewReport)
        .where(InterviewReport.application_id == application_id)
        .options(*_REPORT_LOAD_OPTIONS)
        .execution_options(populate_existing=True)
    )
    if for_update:
        query = query.with_for_update()
    return db.scalar(query)


def _reload_report(db: Session, report_id: uuid.UUID) -> InterviewReport:
    report = db.scalar(
        select(InterviewReport)
        .where(InterviewReport.id == report_id)
        .options(*_REPORT_LOAD_OPTIONS)
        .execution_options(populate_existing=True)
    )
    if report is None:
        raise RuntimeError("面试报告提交后无法重新加载")
    return report


def _version_response(
    version: InterviewReportVersion,
) -> InterviewReportVersionResponse:
    return InterviewReportVersionResponse(
        id=version.id,
        version_number=version.version_number,
        source_version_id=version.source_version_id,
        generation_mode=version.generation_mode,
        conclusion=version.conclusion,
        executive_summary=version.executive_summary,
        strengths=version.strengths,
        concerns=version.concerns,
        follow_up_actions=version.follow_up_actions,
        screening_result_id=version.screening_result_id,
        evaluation_ids=version.evaluation_ids,
        evidence_snapshot=InterviewReportContextResponse.model_validate(
            version.evidence_snapshot
        ),
        missing_rounds=version.missing_rounds,
        model_name=version.model_name,
        prompt_version=version.prompt_version,
        ai_failure_code=version.ai_failure_code,
        ai_failure_message=version.ai_failure_message,
        created_by_id=version.created_by_id,
        created_by_username=version.created_by_username,
        created_by_display_name=version.created_by_display_name,
        created_at=version.created_at,
    )


def _report_response(report: InterviewReport) -> InterviewReportResponse:
    application = report.application
    return InterviewReportResponse(
        id=report.id,
        application_id=application.id,
        application_status=application.status,
        job_id=application.job_id,
        job_title=application.job.title,
        candidate_id=application.candidate_id,
        candidate_code=application.candidate.candidate_code,
        candidate_name=application.candidate.full_name,
        status=report.status,
        current_version_number=report.current_version_number,
        confirmed_by_id=report.confirmed_by_id,
        confirmed_at=report.confirmed_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
        versions=[_version_response(version) for version in report.versions],
    )


def _report_summary_response(
    report: InterviewReport,
) -> InterviewReportSummaryResponse:
    application = report.application
    return InterviewReportSummaryResponse(
        id=report.id,
        application_id=application.id,
        application_status=application.status,
        candidate_id=application.candidate_id,
        candidate_code=application.candidate.candidate_code,
        candidate_name=application.candidate.full_name,
        status=report.status,
        current_version_number=report.current_version_number,
        current_conclusion=report.current_version.conclusion,
        confirmed_at=report.confirmed_at,
        updated_at=report.updated_at,
    )


def _ensure_write_allowed(job: Job, application: JobApplication, user: User) -> None:
    ensure_job_writable(job, user)
    if job.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="归档职位不能修改面试报告",
        )
    if application.status == "merged":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已合并应聘记录不能修改面试报告",
        )


def _find_idempotent_version(
    report: InterviewReport,
    idempotency_key: uuid.UUID,
) -> InterviewReportVersion | None:
    return next(
        (
            version
            for version in report.versions
            if version.idempotency_key == idempotency_key
        ),
        None,
    )


def _content_values(content: InterviewReportContent) -> dict[str, object]:
    return {field: getattr(content, field) for field in _CONTENT_FIELDS}


def _version_content_values(version: InterviewReportVersion) -> dict[str, object]:
    return {field: getattr(version, field) for field in _CONTENT_FIELDS}


def _raise_idempotency_conflict() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="幂等键已用于不同的面试报告操作或内容",
    )


def _ensure_manual_create_replay(
    version: InterviewReportVersion,
    payload: InterviewReportCreateRequest,
) -> None:
    if (
        version.source_version_id is not None
        or version.generation_mode != "manual"
        or version.prompt_version is not None
        or version.ai_failure_code is not None
        or _version_content_values(version) != _content_values(payload)
    ):
        _raise_idempotency_conflict()


def _ensure_ai_create_replay(version: InterviewReportVersion) -> None:
    if (
        version.source_version_id is not None
        or version.prompt_version != INTERVIEW_REPORT_PROMPT_VERSION
    ):
        _raise_idempotency_conflict()


def _ensure_update_replay(
    version: InterviewReportVersion,
    payload: InterviewReportUpdateRequest,
) -> None:
    if (
        version.source_version_id != payload.source_version_id
        or version.generation_mode != "manual"
        or version.prompt_version is not None
        or version.ai_failure_code is not None
        or _version_content_values(version) != _content_values(payload)
    ):
        _raise_idempotency_conflict()


def _new_version_from_context(
    *,
    content: InterviewReportContent,
    context: InterviewReportContextResponse,
    user: User,
    idempotency_key: uuid.UUID,
    generation_mode: str,
    model_name: str | None = None,
    prompt_version: str | None = None,
    ai_failure_code: str | None = None,
    ai_failure_message: str | None = None,
) -> InterviewReportVersion:
    return InterviewReportVersion(
        version_number=1,
        idempotency_key=idempotency_key,
        source_version_id=None,
        generation_mode=generation_mode,
        screening_result_id=(
            context.latest_screening.id if context.latest_screening is not None else None
        ),
        evaluation_ids=[
            str(evaluation.evaluation_id)
            for evaluation in context.submitted_evaluations
        ],
        evidence_snapshot=context.model_dump(mode="json"),
        missing_rounds=[
            item.model_dump(mode="json") for item in context.missing_rounds
        ],
        model_name=model_name,
        prompt_version=prompt_version,
        ai_failure_code=ai_failure_code,
        ai_failure_message=ai_failure_message,
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
        **_content_values(content),
    )


def _new_version_from_source(
    *,
    report: InterviewReport,
    source: InterviewReportVersion,
    payload: InterviewReportUpdateRequest,
    user: User,
) -> InterviewReportVersion:
    return InterviewReportVersion(
        version_number=report.current_version_number + 1,
        idempotency_key=payload.idempotency_key,
        source_version_id=source.id,
        generation_mode="manual",
        screening_result_id=source.screening_result_id,
        evaluation_ids=deepcopy(source.evaluation_ids),
        evidence_snapshot=deepcopy(source.evidence_snapshot),
        missing_rounds=deepcopy(source.missing_rounds),
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
        **_content_values(payload),
    )


def _create_report(
    application: JobApplication,
    user: User,
) -> InterviewReport:
    return InterviewReport(
        application=application,
        status="draft",
        current_version_number=1,
        created_by_id=user.id,
    )


def _interview_report_rag_query(
    context: InterviewReportContextResponse,
) -> str:
    lines = [
        f"Job title: {context.job_title}",
        "Scenario: generate interview report based on screening result "
        "and submitted interview evaluations.",
    ]
    if context.latest_screening is not None:
        lines.extend(
            [
                f"Screening group: {context.latest_screening.ai_group or 'unknown'}",
                f"Screening score: {context.latest_screening.total_score}",
                "Screening strengths: "
                + "；".join(context.latest_screening.strengths[:5]),
                "Screening gaps: " + "；".join(context.latest_screening.gaps[:5]),
            ]
        )
    for evaluation in context.submitted_evaluations[:5]:
        lines.append(
            "Interview evaluation: "
            f"{evaluation.round_name} {evaluation.overall_recommendation} "
            f"{evaluation.overall_comment or ''}"
        )
        for rating in evaluation.dimension_ratings[:5]:
            lines.append(
                f"Dimension {rating.dimension_name}: "
                f"score={rating.score}, evidence={rating.evidence}"
            )
    if context.missing_rounds:
        lines.append(
            "Missing rounds: "
            + "；".join(f"{item.round_name}:{item.reason}" for item in context.missing_rounds)
        )
    return "\n".join(line for line in lines if line).strip()[:4_000]


def _ai_request_payload(
    context: InterviewReportContextResponse,
    *,
    knowledge_citations: list[RecruitmentKnowledgeRetrievalCitation] | None = None,
    knowledge_error: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "job": {"title": context.job_title},
        "latest_screening": (
            context.latest_screening.model_dump(mode="json")
            if context.latest_screening is not None
            else None
        ),
        "submitted_evaluations": [
            item.model_dump(mode="json") for item in context.submitted_evaluations
        ],
        "missing_rounds": [
            item.model_dump(mode="json") for item in context.missing_rounds
        ],
    }
    if knowledge_citations is not None or knowledge_error is not None:
        payload["enterprise_knowledge"] = {
            "status": "available" if knowledge_error is None else "unavailable",
            "citations": [
                item.model_dump(mode="json") for item in (knowledge_citations or [])
            ],
            "error": knowledge_error,
            "usage_instruction": (
                "Use enterprise knowledge only as policy, standard or process context. "
                "Do not treat it as candidate evidence, do not invent citations, and do not "
                "override screening evidence or submitted interview evaluations."
            ),
        }
    return payload


async def _retrieve_interview_report_knowledge(
    db: Session,
    context: InterviewReportContextResponse,
    *,
    actor: User,
) -> tuple[list[RecruitmentKnowledgeRetrievalCitation] | None, str | None]:
    if not settings.embedding_enabled:
        return None, None
    try:
        response = await retrieve_recruitment_knowledge(
            db,
            RecruitmentKnowledgeRetrievalRequest(
                scenario="interview_report",
                query=_interview_report_rag_query(context),
                limit=5,
                resource_type="job_application",
                resource_id=context.application_id,
                job_id=context.job_id,
                application_id=context.application_id,
            ),
            actor=actor,
        )
    except (EmbeddingClientError, RuntimeError) as error:
        db.rollback()
        return [], f"{error.__class__.__name__}: {str(error)[:500]}"
    return response.citations, None


def _ai_failure(error: AIClientError) -> tuple[str, str]:
    if isinstance(error, AIConfigurationError):
        code = "configuration_error"
    elif isinstance(error, AIRequestTimeout):
        code = "timeout"
    elif isinstance(error, AIResponseValidationError):
        code = "invalid_response"
    elif isinstance(error, AIUpstreamError):
        code = "upstream_error"
    else:
        code = "unknown_error"
    return code, str(error)[:2_000]


def _existing_initial_report(
    report: InterviewReport | None,
    idempotency_key: uuid.UUID,
) -> tuple[InterviewReport, InterviewReportVersion] | None:
    if report is None:
        return None
    version = _find_idempotent_version(report, idempotency_key)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该应聘记录已经存在面试报告，请修改当前版本",
        )
    return report, version


@router.get(
    "/{job_id}/applications/{application_id}/interview-report/context",
    response_model=InterviewReportContextResponse,
)
def get_interview_report_context(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewReportContextResponse:
    job, application = _get_application(
        db, job_id, application_id, current_user
    )
    return _context_response(db, job, application)


@router.get(
    "/{job_id}/interview-reports",
    response_model=list[InterviewReportSummaryResponse],
)
def list_interview_reports(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[InterviewReportSummaryResponse]:
    get_visible_job(db, job_id, current_user)
    reports = list(
        db.scalars(
            select(InterviewReport)
            .join(JobApplication)
            .where(JobApplication.job_id == job_id)
            .options(*_REPORT_LOAD_OPTIONS)
            .order_by(InterviewReport.updated_at.desc(), InterviewReport.id)
        ).all()
    )
    return [_report_summary_response(report) for report in reports]


@router.get(
    "/{job_id}/applications/{application_id}/interview-report",
    response_model=InterviewReportResponse,
)
def get_interview_report(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewReportResponse:
    _job, application = _get_application(
        db, job_id, application_id, current_user
    )
    report = _load_report(db, application.id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试报告不存在",
        )
    return _report_response(report)


@router.post(
    "/{job_id}/applications/{application_id}/interview-report/manual-draft",
    response_model=InterviewReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_interview_report(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    payload: InterviewReportCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewReportResponse:
    job, application = _get_application(
        db, job_id, application_id, current_user, for_update=True
    )
    _ensure_write_allowed(job, application, current_user)
    existing = _existing_initial_report(
        _load_report(db, application.id, for_update=True),
        payload.idempotency_key,
    )
    if existing is not None:
        report, version = existing
        _ensure_manual_create_replay(version, payload)
        return _report_response(report)

    context = _context_response(db, job, application)
    report = _create_report(application, current_user)
    report.versions.append(
        _new_version_from_context(
            content=payload,
            context=context,
            user=current_user,
            idempotency_key=payload.idempotency_key,
            generation_mode="manual",
        )
    )
    db.add(report)
    try:
        db.flush()
        record_audit(
            db,
            action="interview_report.manual_draft_created",
            target_type="interview_report",
            target_id=report.id,
            job_id=job.id,
            result="success",
            actor=current_user,
            details={
                "application_id": str(application.id),
                "version_number": 1,
            },
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        concurrent = _load_report(db, application.id)
        if concurrent is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="面试报告创建冲突，请刷新后重试",
            ) from error
        replay = _find_idempotent_version(concurrent, payload.idempotency_key)
        if replay is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="面试报告已由其他请求创建，请刷新后修改",
            ) from error
        _ensure_manual_create_replay(replay, payload)
        return _report_response(concurrent)
    return _report_response(_reload_report(db, report.id))


@router.post(
    "/{job_id}/applications/{application_id}/interview-report/ai-draft",
    response_model=InterviewReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_ai_interview_report(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    payload: InterviewReportGenerateRequest,
    current_user: CurrentUser,
    db: DbSession,
    ai_client: AIClient,
) -> InterviewReportResponse:
    job, application = _get_application(db, job_id, application_id, current_user)
    _ensure_write_allowed(job, application, current_user)
    existing = _existing_initial_report(
        _load_report(db, application.id), payload.idempotency_key
    )
    if existing is not None:
        report, version = existing
        _ensure_ai_create_replay(version)
        return _report_response(report)

    context = _context_response(db, job, application)
    knowledge_citations, knowledge_error = await _retrieve_interview_report_knowledge(
        db,
        context,
        actor=current_user,
    )
    ai_payload = _ai_request_payload(
        context,
        knowledge_citations=knowledge_citations,
        knowledge_error=knowledge_error,
    )
    generation_mode = "ai"
    failure_code: str | None = None
    failure_message: str | None = None
    prompt_template = get_published_prompt_snapshot(db, "interview_report")
    prompt_version = (
        prompt_template.prompt_version
        if prompt_template is not None
        else INTERVIEW_REPORT_PROMPT_VERSION
    )
    prompt_template_version_id = prompt_template.version_id if prompt_template else None
    try:
        if hasattr(ai_client, "generate_interview_report_with_metrics"):
            content, metrics = await ai_client.generate_interview_report_with_metrics(
                ai_payload,
                prompt_template=prompt_template,
            )
        else:
            content = await ai_client.generate_interview_report(ai_payload)
            metrics = None
        record_ai_call_in_session(
            db,
            scenario="interview_report",
            status="succeeded",
            model_name=metrics.model_name if metrics else getattr(ai_client, "model", None),
            prompt_version=prompt_version,
            prompt_template_version_id=prompt_template_version_id,
            retry_count=metrics.retry_count if metrics else 0,
            duration_ms=metrics.duration_ms if metrics else None,
            input_tokens=metrics.input_tokens if metrics else None,
            output_tokens=metrics.output_tokens if metrics else None,
            total_tokens=metrics.total_tokens if metrics else None,
            invoked_by_id=current_user.id,
            resource_type="job_application",
            resource_id=application.id,
            job_id=job.id,
            application_id=application.id,
        )
    except AIClientError as error:
        generation_mode = "manual"
        failure_code, failure_message = _ai_failure(error)
        record_ai_call_in_session(
            db,
            scenario="interview_report",
            status="failed",
            model_name=getattr(ai_client, "model", None),
            prompt_version=prompt_version,
            prompt_template_version_id=prompt_template_version_id,
            retry_count=0 if isinstance(error, AIConfigurationError) else MAX_MODEL_RETRIES,
            invoked_by_id=current_user.id,
            resource_type="job_application",
            resource_id=application.id,
            job_id=job.id,
            application_id=application.id,
            failure_code=error.__class__.__name__,
            failure_message=str(error),
        )
        content = InterviewReportContent()

    report = _create_report(application, current_user)
    report.versions.append(
        _new_version_from_context(
            content=content,
            context=context,
            user=current_user,
            idempotency_key=payload.idempotency_key,
            generation_mode=generation_mode,
            model_name=ai_client.model or None,
            prompt_version=prompt_version,
            ai_failure_code=failure_code,
            ai_failure_message=failure_message,
        )
    )
    db.add(report)
    try:
        db.flush()
        action = (
            "interview_report.ai_draft_created"
            if failure_code is None
            else "interview_report.ai_fallback_created"
        )
        record_audit(
            db,
            action=action,
            target_type="interview_report",
            target_id=report.id,
            job_id=job.id,
            result="success",
            actor=current_user,
            details={
                "application_id": str(application.id),
                "version_number": 1,
                "generation_mode": generation_mode,
                "ai_failure_code": failure_code,
            },
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        concurrent = _load_report(db, application.id)
        if concurrent is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="面试报告创建冲突，请刷新后重试",
            ) from error
        replay = _find_idempotent_version(concurrent, payload.idempotency_key)
        if replay is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="面试报告已由其他请求创建，请刷新后修改",
            ) from error
        _ensure_ai_create_replay(replay)
        return _report_response(concurrent)
    return _report_response(_reload_report(db, report.id))


@router.post(
    "/{job_id}/applications/{application_id}/interview-report/versions",
    response_model=InterviewReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_interview_report_version(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    payload: InterviewReportUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewReportResponse:
    job, application = _get_application(
        db, job_id, application_id, current_user, for_update=True
    )
    _ensure_write_allowed(job, application, current_user)
    report = _load_report(db, application.id, for_update=True)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试报告不存在",
        )
    replay = _find_idempotent_version(report, payload.idempotency_key)
    if replay is not None:
        _ensure_update_replay(replay, payload)
        return _report_response(report)
    if report.status == "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已确认面试报告不能继续修改",
        )
    source = report.current_version
    if payload.source_version_id != source.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="面试报告已产生新版本，请刷新后重试",
        )
    if _version_content_values(source) == _content_values(payload):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="面试报告内容未发生变化",
        )

    version = _new_version_from_source(
        report=report,
        source=source,
        payload=payload,
        user=current_user,
    )
    report.versions.append(version)
    report.current_version_number = version.version_number
    record_audit(
        db,
        action="interview_report.version_created",
        target_type="interview_report",
        target_id=report.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={
            "application_id": str(application.id),
            "source_version_id": str(source.id),
            "version_number": version.version_number,
        },
    )
    db.commit()
    return _report_response(_reload_report(db, report.id))


@router.post(
    "/{job_id}/applications/{application_id}/interview-report/confirm",
    response_model=InterviewReportResponse,
)
def confirm_interview_report(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    payload: InterviewReportConfirmRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewReportResponse:
    job, application = _get_application(
        db, job_id, application_id, current_user, for_update=True
    )
    _ensure_write_allowed(job, application, current_user)
    report = _load_report(db, application.id, for_update=True)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试报告不存在",
        )
    current_version = report.current_version
    if report.status == "confirmed":
        if payload.version_id == current_version.id:
            return _report_response(report)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="面试报告已经确认其他版本",
        )
    if payload.version_id != current_version.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只能确认面试报告当前版本",
        )
    if current_version.conclusion is None or not current_version.executive_summary.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="确认前必须填写报告结论和摘要",
        )

    report.status = "confirmed"
    report.confirmed_by_id = current_user.id
    report.confirmed_at = datetime.now(UTC)
    record_audit(
        db,
        action="interview_report.confirmed",
        target_type="interview_report",
        target_id=report.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={
            "application_id": str(application.id),
            "version_id": str(current_version.id),
            "version_number": current_version.version_number,
            "conclusion": current_version.conclusion,
        },
    )
    db.commit()
    return _report_response(_reload_report(db, report.id))
