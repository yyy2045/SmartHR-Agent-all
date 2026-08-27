from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AiCallLog, User
from app.schemas.candidate_agent import CandidateAgentAnswerDraft
from app.services.ai_client import AIClientError, AIRequestMetrics, get_ai_client
from app.services.ai_observability import record_ai_call_in_session
from app.services.prompt_templates import get_published_prompt_snapshot

CANDIDATE_AGENT_SCENARIO = "candidate_qa"
CANDIDATE_AGENT_ASSESSMENT_SCENARIO = "candidate_assessment"
CANDIDATE_AGENT_FALLBACK_PROMPT_VERSION = "candidate-qa-v1"


class CandidateQuestionClient(Protocol):
    async def answer_candidate_question_with_metrics(
        self,
        payload: dict[str, Any],
        *,
        prompt_template: Any | None = None,
    ) -> tuple[CandidateAgentAnswerDraft, AIRequestMetrics]: ...


@dataclass(frozen=True)
class CandidateAgentAIResult:
    answer: CandidateAgentAnswerDraft
    ai_call_log: AiCallLog
    prompt_template_version_id: uuid.UUID | None
    prompt_version: str
    model_name: str


def build_candidate_agent_ai_payload(
    *,
    question: str,
    context: dict[str, Any],
    enterprise_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "question": question,
        "context": context,
        "enterprise_knowledge": enterprise_knowledge
        or {"available": False, "citations": [], "note": "未检索企业知识库"},
        "decision_boundary": {
            "ai_may": [
                "解释候选人与职位的匹配证据",
                "提示风险、矛盾和信息缺口",
                "建议招聘专员下一步核实问题",
            ],
            "ai_must_not": [
                "自动录用或淘汰候选人",
                "发送 Offer",
                "改变候选人流程阶段",
                "把企业知识库内容当作候选人事实",
            ],
        },
    }


async def generate_candidate_agent_answer(
    db: Session,
    *,
    question: str,
    context: dict[str, Any],
    actor: User,
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    enterprise_knowledge: dict[str, Any] | None = None,
    ai_client: CandidateQuestionClient | None = None,
) -> CandidateAgentAIResult:
    prompt_template = get_published_prompt_snapshot(db, CANDIDATE_AGENT_SCENARIO)
    prompt_version = (
        prompt_template.prompt_version
        if prompt_template is not None
        else CANDIDATE_AGENT_FALLBACK_PROMPT_VERSION
    )
    prompt_template_version_id = prompt_template.version_id if prompt_template else None
    client = ai_client or get_ai_client()
    payload = build_candidate_agent_ai_payload(
        question=question,
        context=context,
        enterprise_knowledge=enterprise_knowledge,
    )
    try:
        answer, metrics = await client.answer_candidate_question_with_metrics(
            payload,
            prompt_template=prompt_template,
        )
    except AIClientError as error:
        call = record_ai_call_in_session(
            db,
            scenario=CANDIDATE_AGENT_SCENARIO,
            status="failed",
            model_name=settings.ai_model,
            prompt_version=prompt_version,
            prompt_template_version_id=prompt_template_version_id,
            invoked_by_id=actor.id,
            resource_type="job_application",
            resource_id=application_id,
            job_id=job_id,
            application_id=application_id,
            failure_code=error.__class__.__name__,
            failure_message=str(error),
        )
        db.flush()
        raise
    call = record_ai_call_in_session(
        db,
        scenario=CANDIDATE_AGENT_SCENARIO,
        status="succeeded",
        model_name=metrics.model_name,
        prompt_version=prompt_version,
        prompt_template_version_id=prompt_template_version_id,
        retry_count=metrics.retry_count,
        duration_ms=metrics.duration_ms,
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        total_tokens=metrics.total_tokens,
        invoked_by_id=actor.id,
        resource_type="job_application",
        resource_id=application_id,
        job_id=job_id,
        application_id=application_id,
    )
    db.flush()
    return CandidateAgentAIResult(
        answer=answer,
        ai_call_log=call,
        prompt_template_version_id=prompt_template_version_id,
        prompt_version=prompt_version,
        model_name=metrics.model_name,
    )
