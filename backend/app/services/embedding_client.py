from __future__ import annotations

import asyncio
import logging
import math
from functools import lru_cache
from typing import Any, Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
MAX_EMBEDDING_RETRIES = 2


class EmbeddingClientError(RuntimeError):
    pass


class EmbeddingConfigurationError(EmbeddingClientError):
    pass


class EmbeddingRequestTimeout(EmbeddingClientError):
    pass


class EmbeddingUpstreamError(EmbeddingClientError):
    pass


class EmbeddingResponseValidationError(EmbeddingClientError):
    pass


class EmbeddingClient(Protocol):
    model: str
    dimension: int
    version: str
    batch_size: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimension: int,
        version: str,
        timeout_seconds: int,
        batch_size: int,
        max_concurrency: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.dimension = dimension
        self.version = version.strip()
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size
        self.transport = transport
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def _validate_configuration(self) -> None:
        if not self.base_url or self.base_url == "https://api.example.com/v1":
            raise EmbeddingConfigurationError("尚未配置可用的 EMBEDDING_BASE_URL")
        if not self.api_key or self.api_key.startswith("replace-with-"):
            raise EmbeddingConfigurationError("尚未配置可用的 EMBEDDING_API_KEY")
        if not self.model or self.model.startswith("replace-with-"):
            raise EmbeddingConfigurationError("尚未配置可用的 EMBEDDING_MODEL")
        if not self.version:
            raise EmbeddingConfigurationError("尚未配置 EMBEDDING_VERSION")

    def _extract_embeddings(
        self,
        body: dict[str, Any],
        expected_count: int,
    ) -> list[list[float]]:
        data = body.get("data")
        if not isinstance(data, list) or len(data) != expected_count:
            raise EmbeddingResponseValidationError("Embedding 响应数量不正确")
        try:
            ordered = sorted(data, key=lambda item: int(item["index"]))
        except (KeyError, TypeError, ValueError) as error:
            raise EmbeddingResponseValidationError("Embedding 响应缺少合法索引") from error

        embeddings: list[list[float]] = []
        for expected_index, item in enumerate(ordered):
            if int(item["index"]) != expected_index:
                raise EmbeddingResponseValidationError("Embedding 响应索引不连续")
            raw_embedding = item.get("embedding")
            if not isinstance(raw_embedding, list) or len(raw_embedding) != self.dimension:
                raise EmbeddingResponseValidationError("Embedding 向量维度不正确")
            try:
                embedding = [float(value) for value in raw_embedding]
            except (TypeError, ValueError) as error:
                raise EmbeddingResponseValidationError("Embedding 向量包含非法值") from error
            if not all(math.isfinite(value) for value in embedding):
                raise EmbeddingResponseValidationError("Embedding 向量包含非有限值")
            embeddings.append(embedding)
        return embeddings

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self._validate_configuration()
        if not texts:
            return []
        if len(texts) > self.batch_size:
            raise ValueError(f"单次 Embedding 文本数量不能超过 {self.batch_size}")

        last_error: EmbeddingClientError | None = None
        async with self._semaphore:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                for attempt in range(MAX_EMBEDDING_RETRIES + 1):
                    try:
                        response = await client.post(
                            f"{self.base_url}/embeddings",
                            headers={
                                "Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json",
                            },
                            json={"model": self.model, "input": texts},
                        )
                        response.raise_for_status()
                        body = response.json()
                        if not isinstance(body, dict):
                            raise EmbeddingResponseValidationError(
                                "Embedding 响应不是 JSON 对象"
                            )
                        return self._extract_embeddings(body, len(texts))
                    except httpx.TimeoutException:
                        last_error = EmbeddingRequestTimeout("Embedding 服务响应超时")
                    except httpx.HTTPStatusError as error:
                        status_code = error.response.status_code
                        if status_code not in {408, 429} and status_code < 500:
                            raise EmbeddingUpstreamError(
                                f"Embedding 服务请求失败（HTTP {status_code}）"
                            ) from error
                        last_error = EmbeddingUpstreamError("Embedding 服务暂时不可用")
                    except httpx.RequestError:
                        last_error = EmbeddingUpstreamError("无法连接 Embedding 服务")
                    except (ValueError, EmbeddingResponseValidationError) as error:
                        last_error = (
                            error
                            if isinstance(error, EmbeddingResponseValidationError)
                            else EmbeddingResponseValidationError(
                                "Embedding 服务响应不是有效 JSON"
                            )
                        )

                    if attempt < MAX_EMBEDDING_RETRIES:
                        logger.warning(
                            "Embedding 第 %s 次调用失败，准备重试",
                            attempt + 1,
                        )

        if last_error is not None:
            raise last_error
        raise EmbeddingUpstreamError("Embedding 服务调用失败")


@lru_cache
def get_embedding_client() -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
        version=settings.embedding_version,
        timeout_seconds=settings.embedding_timeout_seconds,
        batch_size=settings.embedding_batch_size,
        max_concurrency=settings.embedding_max_concurrency,
    )
