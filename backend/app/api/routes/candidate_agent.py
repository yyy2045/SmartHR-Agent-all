from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import (
    AiCallLog,
    CandidateAgentExchange,
    CandidateAgentReport,
    CandidateAgentSession,
    User,
)
from app.schemas.candidate_agent import (
    CandidateAgentAnswerDraft,
    CandidateAgentAskRequest,
    CandidateAgentExchangeResponse,
    CandidateAgentReportAIDraft,
    CandidateAgentReportGenerateRequest,
    CandidateAgentReportResponse,
    CandidateAgentSessionCreateRequest,
    CandidateAgentSessionDetailResponse,
    CandidateAgentSessionResponse,
)
from app.services.ai_client import AIClientError, get_ai_client
from app.services.candidate_agent_ai import (
    CANDIDATE_AGENT_ASSESSMENT_SCENARIO,
    CANDIDATE_AGENT_SCENARIO,
)
from app.services.candidate_agent_context import build_candidate_agent_context
from app.services.candidate_agent_runtime import (
    CandidateAgentLoopError,
    ToolCallingClient,
    run_candidate_agent_loop,
)
from app.services.prompt_templates import get_published_prompt_snapshot

router = APIRouter()


def _ensure_agent_role(user: User) -> None:
    if not (user.has_role("administrator") or user.has_role("recruiter")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员或招聘专员权限",
        )


def _get_session_or_404(
    db: Session,
    *,
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    session_id: uuid.UUID,
) -> CandidateAgentSession:
    session = db.scalar(
        select(CandidateAgentSession)
        .where(
            CandidateAgentSession.id == session_id,
            CandidateAgentSession.job_id == job_id,
            CandidateAgentSession.application_id == application_id,
        )
        .options(selectinload(CandidateAgentSession.exchanges))
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="候选人问答会话不存在",
        )
    return session


def _exchange_response(exchange: CandidateAgentExchange) -> CandidateAgentExchangeResponse:
    return CandidateAgentExchangeResponse.model_validate(exchange)


def _latest_failed_ai_call(
    db: Session,
    *,
    application_id: uuid.UUID,
    actor_id: uuid.UUID,
    scenario: str,
) -> AiCallLog | None:
    return db.scalar(
        select(AiCallLog)
        .where(
            AiCallLog.scenario == scenario,
            AiCallLog.status == "failed",
            AiCallLog.application_id == application_id,
            AiCallLog.invoked_by_id == actor_id,
        )
        .order_by(AiCallLog.created_at.desc(), AiCallLog.id.desc())
        .limit(1)
    )


@router.get(
    "/{job_id}/applications/{application_id}/candidate-agent/sessions",
    response_model=list[CandidateAgentSessionResponse],
)
def list_candidate_agent_sessions(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> list[CandidateAgentSession]:
    _ensure_agent_role(current_user)
    build_candidate_agent_context(
        db,
        job_id=job_id,
        application_id=application_id,
        actor=current_user,
    )
    return list(
        db.scalars(
            select(CandidateAgentSession)
            .where(
                CandidateAgentSession.job_id == job_id,
                CandidateAgentSession.application_id == application_id,
            )
            .order_by(
                CandidateAgentSession.updated_at.desc(),
                CandidateAgentSession.created_at.desc(),
            )
        )
    )


@router.post(
    "/{job_id}/applications/{application_id}/candidate-agent/sessions",
    response_model=CandidateAgentSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate_agent_session(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    payload: CandidateAgentSessionCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> CandidateAgentSession:
    _ensure_agent_role(current_user)
    build_candidate_agent_context(
        db,
        job_id=job_id,
        application_id=application_id,
        actor=current_user,
    )
    session = CandidateAgentSession(
        job_id=job_id,
        application_id=application_id,
        title=payload.title.strip() if payload.title else None,
        created_by_id=current_user.id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _get_session_or_404(
        db,
        job_id=job_id,
        application_id=application_id,
        session_id=session.id,
    )


@router.get(
    "/{job_id}/applications/{application_id}/candidate-agent/sessions/{session_id}",
    response_model=CandidateAgentSessionDetailResponse,
)
def get_candidate_agent_session(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    session_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> CandidateAgentSession:
    _ensure_agent_role(current_user)
    build_candidate_agent_context(
        db,
        job_id=job_id,
        application_id=application_id,
        actor=current_user,
    )
    return _get_session_or_404(
        db,
        job_id=job_id,
        application_id=application_id,
        session_id=session_id,
    )


@router.post(
    "/{job_id}/applications/{application_id}/candidate-agent/sessions/{session_id}/ask",
    response_model=CandidateAgentExchangeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ask_candidate_agent(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    session_id: uuid.UUID,
    payload: CandidateAgentAskRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    ai_client: Annotated[ToolCallingClient, Depends(get_ai_client)],
) -> CandidateAgentExchangeResponse:
    _ensure_agent_role(current_user)
    session = _get_session_or_404(
        db,
        job_id=job_id,
        application_id=application_id,
        session_id=session_id,
    )
    context = build_candidate_agent_context(
        db,
        job_id=job_id,
        application_id=application_id,
        actor=current_user,
    )
    existing = db.scalar(
        select(CandidateAgentExchange).where(
            CandidateAgentExchange.session_id == session.id,
            CandidateAgentExchange.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return _exchange_response(existing)

    next_sequence = (
        db.scalar(
            select(func.max(CandidateAgentExchange.sequence_number)).where(
                CandidateAgentExchange.session_id == session.id
            )
        )
        or 0
    ) + 1
    exchange = CandidateAgentExchange(
        session_id=session.id,
        sequence_number=next_sequence,
        idempotency_key=payload.idempotency_key,
        status="pending",
        question=payload.question.strip(),
        evidence_snapshot=context,
        created_by_id=current_user.id,
    )
    db.add(exchange)
    db.flush()
    prompt_snapshot = get_published_prompt_snapshot(db, CANDIDATE_AGENT_SCENARIO)
    try:
        result = await run_candidate_agent_loop(
            db,
            context=context,
            goal="answer",
            question=exchange.question,
            actor=current_user,
            job_id=job_id,
            application_id=application_id,
            scenario=CANDIDATE_AGENT_SCENARIO,
            prompt_snapshot=prompt_snapshot,
            ai_client=ai_client,
            response_type=CandidateAgentAnswerDraft,
        )
    except (AIClientError, CandidateAgentLoopError) as error:
        failed_call = _latest_failed_ai_call(
            db,
            application_id=application_id,
            actor_id=current_user.id,
            scenario=CANDIDATE_AGENT_SCENARIO,
        )
        exchange.status = "manual_fallback"
        exchange.answer = (
            "AI 问答暂时不可用，本轮问题和上下文已保存。"
            "请招聘专员基于页面证据人工判断，不会阻断候选人流程。"
        )
        exchange.failure_code = error.__class__.__name__
        exchange.failure_message = str(error)
        if failed_call is not None:
            exchange.ai_call_log_id = failed_call.id
            exchange.ai_call_log_ids = [str(failed_call.id)]
            exchange.model_name = failed_call.model_name
            exchange.prompt_version = failed_call.prompt_version
            exchange.prompt_template_version_id = failed_call.prompt_template_version_id
    else:
        exchange.status = "succeeded"
        exchange.answer = result.draft.answer
        exchange.evidence_references = [
            item.model_dump(mode="json") for item in result.draft.evidence_references
        ]
        exchange.knowledge_citations = [
            item.model_dump(mode="json") for item in result.draft.knowledge_citations
        ]
        exchange.tool_trajectory = result.tool_trajectory
        exchange.ai_call_log_ids = [str(call.id) for call in result.ai_call_logs]
        exchange.ai_call_log_id = (
            result.ai_call_logs[-1].id if result.ai_call_logs else None
        )
        exchange.prompt_template_version_id = result.prompt_template_version_id
        exchange.prompt_version = result.prompt_version
        exchange.model_name = result.model_name
    db.commit()
    db.refresh(exchange)
    return _exchange_response(exchange)


@router.post(
    "/{job_id}/applications/{application_id}/candidate-agent/report",
    response_model=CandidateAgentReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_candidate_agent_report(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    payload: CandidateAgentReportGenerateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
    ai_client: Annotated[ToolCallingClient, Depends(get_ai_client)],
) -> CandidateAgentReport:
    _ensure_agent_role(current_user)
    context = build_candidate_agent_context(
        db,
        job_id=job_id,
        application_id=application_id,
        actor=current_user,
    )
    existing = db.scalar(
        select(CandidateAgentReport).where(
            CandidateAgentReport.application_id == application_id,
            CandidateAgentReport.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return existing

    report = CandidateAgentReport(
        application_id=application_id,
        job_id=job_id,
        idempotency_key=payload.idempotency_key,
        status="pending",
        evidence_snapshot=context,
        created_by_id=current_user.id,
    )
    db.add(report)
    db.flush()
    prompt_snapshot = get_published_prompt_snapshot(db, CANDIDATE_AGENT_ASSESSMENT_SCENARIO)
    try:
        result = await run_candidate_agent_loop(
            db,
            context=context,
            goal="report",
            question=None,
            actor=current_user,
            job_id=job_id,
            application_id=application_id,
            scenario=CANDIDATE_AGENT_ASSESSMENT_SCENARIO,
            prompt_snapshot=prompt_snapshot,
            ai_client=ai_client,
            response_type=CandidateAgentReportAIDraft,
        )
    except (AIClientError, CandidateAgentLoopError) as error:
        failed_call = _latest_failed_ai_call(
            db,
            application_id=application_id,
            actor_id=current_user.id,
            scenario=CANDIDATE_AGENT_ASSESSMENT_SCENARIO,
        )
        report.status = "manual_fallback"
        report.match_assessment = (
            "AI 研判报告暂时不可用，本轮上下文已保存。"
            "请招聘专员基于页面证据人工研判，不会阻断候选人流程。"
        )
        report.failure_code = error.__class__.__name__
        report.failure_message = str(error)
        if failed_call is not None:
            report.ai_call_log_ids = [str(failed_call.id)]
            report.model_name = failed_call.model_name
            report.prompt_version = failed_call.prompt_version
            report.prompt_template_version_id = failed_call.prompt_template_version_id
    else:
        draft = result.draft
        report.status = "succeeded"
        report.match_assessment = draft.match_assessment
        report.strengths = draft.strengths
        report.risks = draft.risks
        report.contradictions = draft.contradictions
        report.evidence_gaps = draft.evidence_gaps
        report.next_step_suggestions = draft.next_step_suggestions
        report.open_questions = draft.open_questions
        report.overall_recommendation = draft.overall_recommendation
        report.evidence_references = [
            item.model_dump(mode="json") for item in draft.evidence_references
        ]
        report.knowledge_citations = [
            item.model_dump(mode="json") for item in draft.knowledge_citations
        ]
        report.tool_trajectory = result.tool_trajectory
        report.ai_call_log_ids = [str(call.id) for call in result.ai_call_logs]
        report.prompt_template_version_id = result.prompt_template_version_id
        report.prompt_version = result.prompt_version
        report.model_name = result.model_name
    db.commit()
    db.refresh(report)
    return report


@router.get(
    "/{job_id}/applications/{application_id}/candidate-agent/report",
    response_model=CandidateAgentReportResponse | None,
)
def get_candidate_agent_report(
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> CandidateAgentReport | None:
    _ensure_agent_role(current_user)
    build_candidate_agent_context(
        db,
        job_id=job_id,
        application_id=application_id,
        actor=current_user,
    )
    return db.scalar(
        select(CandidateAgentReport)
        .where(CandidateAgentReport.application_id == application_id)
        .order_by(
            CandidateAgentReport.created_at.desc(),
            CandidateAgentReport.id.desc(),
        )
        .limit(1)
    )
