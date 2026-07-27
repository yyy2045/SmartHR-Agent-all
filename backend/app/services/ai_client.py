from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from app.config import settings
from app.schemas.interview_report import InterviewReportAIDraft
from app.schemas.job import JDAIDraft
from app.schemas.screening import ResumeAnalysisDraft

logger = logging.getLogger(__name__)
MAX_MODEL_RETRIES = 2
RESUME_MATCH_PROMPT_VERSION = "resume-match-v2"
INTERVIEW_REPORT_PROMPT_VERSION = "interview-report-v1"
StructuredResponse = TypeVar(
    "StructuredResponse", JDAIDraft, ResumeAnalysisDraft, InterviewReportAIDraft
)


def _schema_instruction(
    response_type: type[JDAIDraft]
    | type[ResumeAnalysisDraft]
    | type[InterviewReportAIDraft],
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
    def _request_payload(*, title: str, department: str, jd: str, model: str) -> dict[str, Any]:
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
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
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
    def _resume_request_payload(
        *,
        payload: dict[str, Any],
        model: str,
        validation_feedback: str | None = None,
        previous_analysis: dict[str, Any] | None = None,
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
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_content, ensure_ascii=False),
                },
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }

    @staticmethod
    def _interview_report_request_payload(
        *, payload: dict[str, Any], model: str
    ) -> dict[str, Any]:
        system_prompt = (
            "你是企业招聘面试报告助手。只能依据输入中的最新筛选结果、证据引用和已提交"
            "面试评价生成可编辑草稿，不得补全或猜测缺失信息。必须明确区分‘未提供信息’"
            "与‘不符合要求’，缺失面试轮次只能作为风险提示，不能假定面试未通过。"
            "结论只允许 hire、next_round、reserve、reject。AI 不拥有最终录用权，输出只是"
            "招聘专员确认前的草稿，也不得建议系统自动改变候选人阶段。"
            f"{_schema_instruction(InterviewReportAIDraft)}"
        )
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }

    async def _request_structured(
        self,
        *,
        payload: dict[str, Any],
        response_type: type[StructuredResponse],
        operation_name: str,
    ) -> StructuredResponse:
        last_error: AIClientError | None = None

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
                        content = self._extract_content(response.json())
                        return response_type.model_validate(content)
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

    async def structure_jd(self, *, title: str, department: str, jd: str) -> JDAIDraft:
        self._validate_configuration()
        payload = self._request_payload(
            title=title,
            department=department,
            jd=jd,
            model=self.model,
        )
        return await self._request_structured(
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
    ) -> ResumeAnalysisDraft:
        self._validate_configuration()
        return await self._request_structured(
            payload=self._resume_request_payload(
                payload=payload,
                model=self.model,
                validation_feedback=validation_feedback,
                previous_analysis=previous_analysis,
            ),
            response_type=ResumeAnalysisDraft,
            operation_name="AI 简历匹配",
        )

    async def generate_interview_report(
        self, payload: dict[str, Any]
    ) -> InterviewReportAIDraft:
        self._validate_configuration()
        return await self._request_structured(
            payload=self._interview_report_request_payload(
                payload=payload,
                model=self.model,
            ),
            response_type=InterviewReportAIDraft,
            operation_name="AI 面试报告",
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
