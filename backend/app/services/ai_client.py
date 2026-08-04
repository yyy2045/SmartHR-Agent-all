from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from app.config import settings
from app.schemas.candidate_agent import CandidateAgentAnswerDraft
from app.schemas.interview_report import InterviewReportAIDraft
from app.schemas.job import JDAIDraft
from app.schemas.screening import ResumeAnalysisDraft
from app.services.prompt_templates import PublishedPromptSnapshot

logger = logging.getLogger(__name__)
MAX_MODEL_RETRIES = 2
RESUME_MATCH_PROMPT_VERSION = "resume-match-v2"
INTERVIEW_REPORT_PROMPT_VERSION = "interview-report-v1"
StructuredResponse = TypeVar(
    "StructuredResponse",
    JDAIDraft,
    ResumeAnalysisDraft,
    InterviewReportAIDraft,
    CandidateAgentAnswerDraft,
)


@dataclass(frozen=True)
class AIRequestMetrics:
    model_name: str
    retry_count: int
    duration_ms: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_prompt_template(template: str, variables: dict[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in variables:
            raise AIConfigurationError(f"Prompt 模板变量未提供：{key}")
        value = variables[key]
        if isinstance(value, str):
            return value
        return _json_dumps(value)

    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", replace, template)


def _model_temperature(
    prompt_template: PublishedPromptSnapshot | None,
    default: float,
) -> float:
    if prompt_template is None:
        return default
    value = prompt_template.model_parameters.get("temperature")
    if isinstance(value, int | float):
        return float(value)
    return default


def _render_prompt_pair(
    prompt_template: PublishedPromptSnapshot,
    variables: dict[str, object],
) -> tuple[str, str]:
    system_prompt = _render_prompt_template(prompt_template.system_prompt, variables)
    user_prompt = _render_prompt_template(prompt_template.user_prompt_template, variables)
    if (
        "{{schema_instruction}}" not in prompt_template.system_prompt
        and "{{schema_instruction}}" not in prompt_template.user_prompt_template
    ):
        system_prompt = f"{system_prompt}\n{variables['schema_instruction']}"
    return system_prompt, user_prompt


def _schema_instruction(
    response_type: type[JDAIDraft]
    | type[ResumeAnalysisDraft]
    | type[InterviewReportAIDraft]
    | type[CandidateAgentAnswerDraft],
) -> str:
    schema = json.dumps(
        response_type.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"必须只返回一个符合以下 JSON Schema 的 JSON 对象：{schema}"


class AIClientError(RuntimeError):
    pass


class AIConfigurationError(AIClientError):
    pass


class AIRequestTimeout(AIClientError):
    pass


class AIUpstreamError(AIClientError):
    pass


class AIResponseValidationError(AIClientError):
    pass


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int,
        max_concurrency: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def _validate_configuration(self) -> None:
        if not self.base_url or self.base_url == "https://api.example.com/v1":
            raise AIConfigurationError("尚未配置可用的 AI_BASE_URL")
        if not self.api_key or self.api_key.startswith("replace-with-"):
            raise AIConfigurationError("尚未配置可用的 AI_API_KEY")
        if not self.model or self.model.startswith("replace-with-"):
            raise AIConfigurationError("尚未配置可用的 AI_MODEL")

    @staticmethod
    def _request_payload(
        *,
        title: str,
        department: str,
        jd: str,
        model: str,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "你是企业招聘标准结构化助手。只根据用户提供的 JD 生成筛选草稿，不虚构信息。"
            "客观硬性要求类型仅允许 min_experience_years、min_education、"
            "required_certification、language_level、other。只有前四类可设置 auto_reject=true。"
            "评分维度权重必须为整数且总和严格等于 100。输出必须符合给定 JSON Schema。"
            f"{_schema_instruction(JDAIDraft)}"
        )
        user_prompt = (
            f"当前职位名称：{title}\n"
            f"所属部门：{department or '未提供'}\n"
            "请提取建议职位名称、职位摘要、硬性要求和语义评分维度。\n"
            f"JD：\n{jd}"
        )
        if prompt_template is not None:
            system_prompt, user_prompt = _render_prompt_pair(
                prompt_template,
                {
                    "title": title,
                    "department": department or "未提供",
                    "jd": jd,
                    "schema_instruction": _schema_instruction(JDAIDraft),
                },
            )
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": _model_temperature(prompt_template, 0.1),
            "response_format": {"type": "json_object"},
        }

    @staticmethod
    def _extract_content(body: dict[str, Any]) -> Any:
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise AIResponseValidationError("模型响应缺少结构化内容") from error
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError as error:
                raise AIResponseValidationError("模型响应不是有效 JSON") from error
        if isinstance(content, dict):
            return content
        raise AIResponseValidationError("模型响应内容类型无效")

    @staticmethod
    def _usage_metrics(body: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return None, None, None
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")
        return (
            input_tokens if isinstance(input_tokens, int) else None,
            output_tokens if isinstance(output_tokens, int) else None,
            total_tokens if isinstance(total_tokens, int) else None,
        )

    @staticmethod
    def _resume_request_payload(
        *,
        payload: dict[str, Any],
        model: str,
        validation_feedback: str | None = None,
        previous_analysis: dict[str, Any] | None = None,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "你是企业招聘的人岗匹配助手。候选人文本可能是原文，也可能已经本地脱敏。"
            "你只能依据给定文本片段和已确认职位标准进行判断，不得猜测缺失信息。"
            "如果输入包含 candidate_profile_override，它是招聘专员修正后的权威结构化资料，"
            "必须以它为候选人资料来源，并在 candidate_profile 字段原样返回该结构。"
            "最低经验、最低学历、必需证书和明确语言等级必须返回 passed、failed 或 unknown；"
            "简历未提及时必须返回 unknown。技能、行业和项目质量不能作为客观自动淘汰条件。"
            "每个评分维度只返回 0 到 100 的分数、说明、缺失项和证据；不要返回总分或最终分组。"
            "所有明确判断必须引用真实存在的片段编号。每个 evidence.quote 必须从对应片段中"
            "逐字复制一段连续原文，禁止概括、改写、纠正错别字、修改数字、修改标点或拼接"
            "不连续文本；没有可逐字引用的内容时不得编造证据。"
            "输出必须符合给定 JSON Schema。"
            f"{_schema_instruction(ResumeAnalysisDraft)}"
        )
        if validation_feedback:
            system_prompt += (
                "上一次输出未通过后端合同校验。保持上一次分析的事实、状态、分数和 ID 不变，"
                "逐项检查 previous_analysis 中的全部 evidence.quote，只将不合法引用替换为对应"
                "输入片段中的连续逐字原文，然后返回完整 JSON 对象。"
                f"校验反馈：{validation_feedback}"
            )
        user_content: dict[str, Any] | list[Any] | str = payload
        if previous_analysis is not None:
            user_content = {
                "resume_input": payload,
                "previous_analysis": previous_analysis,
                "repair_task": "只纠正证据引用并返回完整分析，禁止改写引用原文。",
            }
        user_prompt = json.dumps(user_content, ensure_ascii=False)
        if prompt_template is not None:
            system_prompt, user_prompt = _render_prompt_pair(
                prompt_template,
                {
                    "payload": user_prompt,
                    "resume_input": payload,
                    "validation_feedback": validation_feedback or "",
                    "previous_analysis": previous_analysis or {},
                    "schema_instruction": _schema_instruction(ResumeAnalysisDraft),
                },
            )
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": _model_temperature(prompt_template, 0),
            "response_format": {"type": "json_object"},
        }

    @staticmethod
    def _interview_report_request_payload(
        *,
        payload: dict[str, Any],
        model: str,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "你是企业招聘面试报告助手。只能依据输入中的最新筛选结果、证据引用和已提交"
            "面试评价生成可编辑草稿，不得补全或猜测缺失信息。必须明确区分‘未提供信息’"
            "与‘不符合要求’，缺失面试轮次只能作为风险提示，不能假定面试未通过。"
            "结论只允许 hire、next_round、reserve、reject。AI 不拥有最终录用权，输出只是"
            "招聘专员确认前的草稿，也不得建议系统自动改变候选人阶段。"
            f"{_schema_instruction(InterviewReportAIDraft)}"
        )
        user_prompt = json.dumps(payload, ensure_ascii=False)
        if prompt_template is not None:
            system_prompt, user_prompt = _render_prompt_pair(
                prompt_template,
                {
                    "payload": user_prompt,
                    "context": payload,
                    "schema_instruction": _schema_instruction(InterviewReportAIDraft),
                },
            )
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": _model_temperature(prompt_template, 0.1),
            "response_format": {"type": "json_object"},
        }

    @staticmethod
    def _candidate_agent_request_payload(
        *,
        payload: dict[str, Any],
        model: str,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> dict[str, Any]:
        system_prompt = (
            "你是企业招聘场景中的候选人问答 Agent，服务对象是招聘专员。"
            "你只能基于输入中的候选人上下文、业务记录和企业知识库引用回答，"
            "不得编造不存在的经历、评价、Offer 或入职事实。"
            "候选人事实必须来自候选人上下文；企业知识库只能作为制度、流程、"
            "岗位标准或沟通规范引用，不能替代候选人证据。"
            "你可以分析匹配点、风险点、矛盾点和下一步建议，但不得自动录用、"
            "自动淘汰、发送 Offer 或改变候选人阶段。"
            "回答必须给出证据引用；证据不足时要明确说明限制。"
            f"{_schema_instruction(CandidateAgentAnswerDraft)}"
        )
        user_prompt = json.dumps(payload, ensure_ascii=False)
        if prompt_template is not None:
            system_prompt, user_prompt = _render_prompt_pair(
                prompt_template,
                {
                    "payload": user_prompt,
                    "question": payload.get("question", ""),
                    "context": payload.get("context", {}),
                    "enterprise_knowledge": payload.get("enterprise_knowledge", {}),
                    "schema_instruction": _schema_instruction(CandidateAgentAnswerDraft),
                },
            )
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": _model_temperature(prompt_template, 0.1),
            "response_format": {"type": "json_object"},
        }

    async def _request_structured_with_metrics(
        self,
        *,
        payload: dict[str, Any],
        response_type: type[StructuredResponse],
        operation_name: str,
    ) -> tuple[StructuredResponse, AIRequestMetrics]:
        last_error: AIClientError | None = None
        started = time.perf_counter()

        async with self._semaphore:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                for attempt in range(MAX_MODEL_RETRIES + 1):
                    try:
                        response = await client.post(
                            f"{self.base_url}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                        )
                        response.raise_for_status()
                        body = response.json()
                        content = self._extract_content(body)
                        parsed = response_type.model_validate(content)
                        input_tokens, output_tokens, total_tokens = self._usage_metrics(body)
                        return parsed, AIRequestMetrics(
                            model_name=self.model,
                            retry_count=attempt,
                            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                        )
                    except httpx.TimeoutException:
                        last_error = AIRequestTimeout("AI 服务响应超时")
                    except httpx.HTTPStatusError as error:
                        status_code = error.response.status_code
                        if status_code not in {408, 429} and status_code < 500:
                            raise AIUpstreamError(
                                f"AI 服务请求失败（HTTP {status_code}）"
                            ) from error
                        last_error = AIUpstreamError("AI 服务暂时不可用")
                    except (httpx.RequestError, json.JSONDecodeError):
                        last_error = AIUpstreamError("无法连接 AI 服务")
                    except (AIResponseValidationError, ValidationError):
                        last_error = AIResponseValidationError("AI 返回的结构化结果格式不合法")

                    if attempt < MAX_MODEL_RETRIES:
                        logger.warning(
                            "%s 第 %s 次调用失败，准备重试",
                            operation_name,
                            attempt + 1,
                        )

        if last_error is not None:
            raise last_error
        raise AIUpstreamError("AI 服务调用失败")

    async def _request_structured(
        self,
        *,
        payload: dict[str, Any],
        response_type: type[StructuredResponse],
        operation_name: str,
    ) -> StructuredResponse:
        response, _metrics = await self._request_structured_with_metrics(
            payload=payload,
            response_type=response_type,
            operation_name=operation_name,
        )
        return response

    async def structure_jd(
        self,
        *,
        title: str,
        department: str,
        jd: str,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> JDAIDraft:
        response, _metrics = await self.structure_jd_with_metrics(
            title=title,
            department=department,
            jd=jd,
            prompt_template=prompt_template,
        )
        return response

    async def structure_jd_with_metrics(
        self,
        *,
        title: str,
        department: str,
        jd: str,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> tuple[JDAIDraft, AIRequestMetrics]:
        self._validate_configuration()
        payload = self._request_payload(
            title=title,
            department=department,
            jd=jd,
            model=self.model,
            prompt_template=prompt_template,
        )
        return await self._request_structured_with_metrics(
            payload=payload,
            response_type=JDAIDraft,
            operation_name="AI 结构化 JD",
        )

    async def analyze_resume(
        self,
        payload: dict[str, Any],
        *,
        validation_feedback: str | None = None,
        previous_analysis: dict[str, Any] | None = None,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> ResumeAnalysisDraft:
        response, _metrics = await self.analyze_resume_with_metrics(
            payload,
            validation_feedback=validation_feedback,
            previous_analysis=previous_analysis,
            prompt_template=prompt_template,
        )
        return response

    async def analyze_resume_with_metrics(
        self,
        payload: dict[str, Any],
        *,
        validation_feedback: str | None = None,
        previous_analysis: dict[str, Any] | None = None,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> tuple[ResumeAnalysisDraft, AIRequestMetrics]:
        self._validate_configuration()
        return await self._request_structured_with_metrics(
            payload=self._resume_request_payload(
                payload=payload,
                model=self.model,
                validation_feedback=validation_feedback,
                previous_analysis=previous_analysis,
                prompt_template=prompt_template,
            ),
            response_type=ResumeAnalysisDraft,
            operation_name="AI 简历匹配",
        )

    async def generate_interview_report(
        self,
        payload: dict[str, Any],
        *,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> InterviewReportAIDraft:
        response, _metrics = await self.generate_interview_report_with_metrics(
            payload,
            prompt_template=prompt_template,
        )
        return response

    async def generate_interview_report_with_metrics(
        self,
        payload: dict[str, Any],
        *,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> tuple[InterviewReportAIDraft, AIRequestMetrics]:
        self._validate_configuration()
        return await self._request_structured_with_metrics(
            payload=self._interview_report_request_payload(
                payload=payload,
                model=self.model,
                prompt_template=prompt_template,
            ),
            response_type=InterviewReportAIDraft,
            operation_name="AI 面试报告",
        )


    async def answer_candidate_question(
        self,
        payload: dict[str, Any],
        *,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> CandidateAgentAnswerDraft:
        response, _metrics = await self.answer_candidate_question_with_metrics(
            payload,
            prompt_template=prompt_template,
        )
        return response

    async def answer_candidate_question_with_metrics(
        self,
        payload: dict[str, Any],
        *,
        prompt_template: PublishedPromptSnapshot | None = None,
    ) -> tuple[CandidateAgentAnswerDraft, AIRequestMetrics]:
        self._validate_configuration()
        return await self._request_structured_with_metrics(
            payload=self._candidate_agent_request_payload(
                payload=payload,
                model=self.model,
                prompt_template=prompt_template,
            ),
            response_type=CandidateAgentAnswerDraft,
            operation_name="AI 候选人问答 Agent",
        )


@lru_cache
def get_ai_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
        max_concurrency=settings.ai_max_concurrency,
    )
