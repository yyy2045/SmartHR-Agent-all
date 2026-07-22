from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import settings
from app.schemas.job import JDAIDraft

logger = logging.getLogger(__name__)
MAX_MODEL_RETRIES = 2


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
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "job_criteria_draft",
                    "strict": True,
                    "schema": JDAIDraft.model_json_schema(),
                },
            },
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

    async def structure_jd(self, *, title: str, department: str, jd: str) -> JDAIDraft:
        self._validate_configuration()
        payload = self._request_payload(
            title=title,
            department=department,
            jd=jd,
            model=self.model,
        )
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
                        return JDAIDraft.model_validate(content)
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
                        last_error = AIResponseValidationError("AI 返回的筛选草稿格式不合法")

                    if attempt < MAX_MODEL_RETRIES:
                        logger.warning("AI 结构化 JD 第 %s 次调用失败，准备重试", attempt + 1)

        if last_error is not None:
            raise last_error
        raise AIUpstreamError("AI 服务调用失败")


@lru_cache
def get_ai_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=settings.ai_base_url,
        api_key=settings.ai_api_key,
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
        max_concurrency=settings.ai_max_concurrency,
    )
