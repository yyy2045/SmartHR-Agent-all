from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AiCallLog, User
from app.schemas.candidate_agent import CandidateAgentAnswerDraft, CandidateAgentReportAIDraft
from app.services.ai_client import (
    AIClientError,
    AIRequestMetrics,
    AIRequestTimeout,
    ToolCall,
)
from app.services.ai_observability import record_ai_call_in_session
from app.services.candidate_agent_tools import (
    CandidateAgentToolDispatcher,
    TerminalSubmission,
    build_openai_tools,
    terminal_tool_name,
)
from app.services.prompt_templates import PublishedPromptSnapshot

MAX_TOOL_STEPS = 6
FALLBACK_PROMPT_VERSION = {
    "answer": "candidate-qa-v1",
    "report": "candidate-assessment-v1",
}


class CandidateAgentLoopError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolCallingClient(Protocol):
    async def chat_complete_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        operation_name: str,
    ) -> tuple[list[ToolCall], str | None, AIRequestMetrics]: ...


@dataclass(frozen=True)
class CandidateAgentRuntimeResult:
    draft: CandidateAgentAnswerDraft | CandidateAgentReportAIDraft
    tool_trajectory: list[dict[str, Any]]
    ai_call_logs: list[AiCallLog]
    steps: int
    prompt_template_version_id: uuid.UUID | None
    prompt_version: str
    model_name: str


def _tool_result(
    name: str,
    step: int,
    status: str,
    *,
    duration_ms: int | None = None,
    arguments: dict[str, Any] | None = None,
    result_snapshot: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "step": step,
        "status": status,
        "duration_ms": duration_ms,
        "request_snapshot": arguments,
        "result_snapshot": result_snapshot,
        "error": error,
    }


def _system_prompt(goal: str, terminal_name: str) -> str:
    objective = (
        "针对当前应聘单生成一份可编辑的候选人研判报告，覆盖匹配度、亮点、风险、矛盾、"
        "证据缺口、下一步建议和待核实问题，并给出信息性的综合建议。"
        if goal == "report"
        else "基于当前应聘单的业务记录回答招聘专员的问题。"
    )
    return (
        "你是企业招聘场景中的候选人研判 Agent，服务对象是招聘专员。"
        f"{objective}"
        "你必须通过调用工具按需获取数据，不得编造不存在的经历、评价、Offer 或入职事实。"
        "候选人事实必须来自工具返回的候选人上下文；企业知识库检索结果只能作为制度、"
        "流程、岗位标准或沟通规范引用，不能替代候选人证据。"
        "你可以分析匹配点、风险点、矛盾点、证据缺口和下一步建议，但不得自动录用、"
        "自动淘汰、发送 Offer 或改变候选人阶段。"
        "工具使用规则：优先获取必要数据源；同一数据源取最新结果；"
        f"当证据足够时，调用 {terminal_name} 工具一次性提交完整结果，{terminal_name} 只调用一次；"
        "如果某工具返回错误或空数据，明确说明信息缺失，不得编造。"
    )


def _user_message(
    goal: str,
    question: str | None,
    context: dict[str, Any],
) -> str:
    candidate = context.get("candidate") or {}
    overview = {
        "job": context.get("job"),
        "application": context.get("application"),
        "candidate_code": candidate.get("candidate_code"),
    }
    message: dict[str, Any] = {
        "goal": "report" if goal == "report" else "answer",
        "application_overview": overview,
        "available_sources": [
            "get_candidate_profile",
            "get_latest_screening",
            "get_interview_evaluations",
            "get_interview_report",
            "get_offer_and_onboarding",
            "search_enterprise_knowledge",
        ],
    }
    if question:
        message["question"] = question
    message["instruction"] = (
        "请按需调用工具收集证据，最终调用提交工具给出完整结果。"
    )
    return json.dumps(message, ensure_ascii=False)


def _assistant_tool_call_message(
    tool_calls: list[ToolCall],
    content_text: str | None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant"}
    if content_text:
        message["content"] = content_text
    message["tool_calls"] = [
        {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False),
            },
        }
        for call in tool_calls
    ]
    return message


def _tool_message(tool_call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def _result_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    return {"keys": sorted(result.keys())}


async def run_candidate_agent_loop(
    db: Session,
    *,
    context: dict[str, Any],
    goal: str,
    question: str | None,
    actor: User,
    job_id: uuid.UUID,
    application_id: uuid.UUID,
    scenario: str,
    prompt_snapshot: PublishedPromptSnapshot | None,
    ai_client: ToolCallingClient,
    response_type: type[CandidateAgentAnswerDraft] | type[CandidateAgentReportAIDraft],
) -> CandidateAgentRuntimeResult:
    tools = build_openai_tools(goal)
    terminal_name = terminal_tool_name(goal)
    operation_name = "AI 候选人研判 Agent" if goal == "report" else "AI 候选人问答 Agent"
    prompt_version = (
        prompt_snapshot.prompt_version
        if prompt_snapshot is not None
        else FALLBACK_PROMPT_VERSION[goal]
    )
    prompt_template_version_id = prompt_snapshot.version_id if prompt_snapshot else None
    dispatcher = CandidateAgentToolDispatcher(
        db=db,
        context=context,
        actor=actor,
        job_id=job_id,
        application_id=application_id,
        scenario=scenario,
        response_type=response_type,
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(goal, terminal_name)},
        {"role": "user", "content": _user_message(goal, question, context)},
    ]
    trajectory: list[dict[str, Any]] = []
    ai_call_logs: list[AiCallLog] = []
    model_name = settings.ai_model
    started = time.perf_counter()

    for step in range(MAX_TOOL_STEPS):
        if time.perf_counter() - started > settings.ai_timeout_seconds:
            record_ai_call_in_session(
                db,
                scenario=scenario,
                status="failed",
                model_name=settings.ai_model,
                prompt_version=prompt_version,
                prompt_template_version_id=prompt_template_version_id,
                invoked_by_id=actor.id,
                resource_type="job_application",
                resource_id=application_id,
                job_id=job_id,
                application_id=application_id,
                failure_code="AIRequestTimeout",
                failure_message="研判 Agent 执行超时",
            )
            db.flush()
            raise AIRequestTimeout("研判 Agent 执行超时")

        try:
            tool_calls, content_text, metrics = await ai_client.chat_complete_with_tools(
                messages=messages,
                tools=tools,
                operation_name=operation_name,
            )
        except AIClientError as error:
            record_ai_call_in_session(
                db,
                scenario=scenario,
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
            scenario=scenario,
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
        ai_call_logs.append(call)
        model_name = metrics.model_name

        if not tool_calls:
            if content_text:
                try:
                    parsed = response_type.model_validate(json.loads(content_text))
                except (json.JSONDecodeError, ValidationError):
                    parsed = None
                if parsed is not None:
                    return CandidateAgentRuntimeResult(
                        draft=parsed,
                        tool_trajectory=trajectory,
                        ai_call_logs=ai_call_logs,
                        steps=step + 1,
                        prompt_template_version_id=prompt_template_version_id,
                        prompt_version=prompt_version,
                        model_name=model_name,
                    )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "请继续：如证据已足够，请调用提交工具给出最终结果；"
                        "如还需数据，请调用相应工具。"
                    ),
                }
            )
            continue

        messages.append(_assistant_tool_call_message(tool_calls, content_text))
        for tool_call in tool_calls:
            tool_started = time.perf_counter()
            try:
                result = await dispatcher.execute(tool_call.name, tool_call.arguments)
            except ValidationError as error:
                messages.append(
                    _tool_message(
                        tool_call.id,
                        json.dumps(
                            {"error": f"提交参数不符合要求：{error}"},
                            ensure_ascii=False,
                        ),
                    )
                )
                trajectory.append(
                    _tool_result(
                        tool_call.name,
                        step,
                        "failed",
                        duration_ms=_elapsed_ms(tool_started),
                        arguments=tool_call.arguments,
                        error=str(error),
                    )
                )
                continue
            except Exception as error:  # noqa: BLE001 - 工具失败以文本反馈模型，不中断循环
                messages.append(
                    _tool_message(
                        tool_call.id,
                        json.dumps(
                            {"error": f"{tool_call.name} 执行失败：{error}"},
                            ensure_ascii=False,
                        ),
                    )
                )
                trajectory.append(
                    _tool_result(
                        tool_call.name,
                        step,
                        "failed",
                        duration_ms=_elapsed_ms(tool_started),
                        arguments=tool_call.arguments,
                        error=str(error),
                    )
                )
                continue

            duration_ms = _elapsed_ms(tool_started)
            if isinstance(result, TerminalSubmission):
                trajectory.append(
                    _tool_result(
                        tool_call.name,
                        step,
                        "succeeded",
                        duration_ms=duration_ms,
                        arguments=tool_call.arguments,
                    )
                )
                return CandidateAgentRuntimeResult(
                    draft=result.draft,
                    tool_trajectory=trajectory,
                    ai_call_logs=ai_call_logs,
                    steps=step + 1,
                    prompt_template_version_id=prompt_template_version_id,
                    prompt_version=prompt_version,
                    model_name=model_name,
                )

            messages.append(
                _tool_message(
                    tool_call.id,
                    json.dumps(result, ensure_ascii=False, default=str),
                )
            )
            trajectory.append(
                _tool_result(
                    tool_call.name,
                    step,
                    "succeeded",
                    duration_ms=duration_ms,
                    arguments=tool_call.arguments,
                    result_snapshot=_result_snapshot(result),
                )
            )

    raise CandidateAgentLoopError(
        "max_steps",
        f"研判 Agent 在 {MAX_TOOL_STEPS} 步内未完成",
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
