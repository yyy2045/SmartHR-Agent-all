from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from functools import lru_cache
from typing import Any, final

import httpx

from app.config import settings

logger = logging.getLogger(__name__)
MAX_MINERU_CREATE_RETRIES = 1
MAX_MINERU_DOWNLOAD_RETRIES = 1
PRECISE_MODEL_VERSIONS = {"pipeline", "vlm", "MinerU-HTML"}


class MineruClientError(RuntimeError):
    """基类：MinerU 在线解析失败。"""


class MineruConfigurationError(MineruClientError):
    pass


class MineruUpstreamError(MineruClientError):
    pass


class MineruParseFailedError(MineruClientError):
    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@final
class MineruParseClient:
    """MinerU 精准解析 API 客户端（需要 API Key，支持 pipeline/vlm/MinerU-HTML）。

    流程：POST /file-urls/batch 申请签名上传地址 -> PUT 上传文件 -> 轮询
    GET /extract-results/batch/{batch_id} 直至 done -> 下载 full_zip_url 解压
    其中的 full.md 返回 Markdown 文本。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        model_version: str = "pipeline",
        timeout_seconds: int,
        poll_interval_seconds: float,
        max_poll_seconds: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.model_version = model_version.strip() or "pipeline"
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_seconds = max_poll_seconds
        self.transport = transport

    def _validate_configuration(self) -> None:
        if not self.base_url or "example.com" in self.base_url:
            raise MineruConfigurationError("尚未配置可用的 MINERU_PARSE_BASE_URL")
        if not self.api_key:
            raise MineruConfigurationError("尚未配置 MINERU_PARSE_API_KEY（精准解析 API 必填）")
        if self.model_version not in PRECISE_MODEL_VERSIONS:
            raise MineruConfigurationError(
                f"不支持的 MINERU_PARSE_MODEL_VERSION：{self.model_version}"
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def parse_file(
        self,
        filename: str,
        content: bytes,
        *,
        model_version: str | None = None,
        language: str = "ch",
        page_range: str | None = None,
        enable_table: bool = True,
        is_ocr: bool = False,
        enable_formula: bool = True,
    ) -> str:
        self._validate_configuration()
        version = (model_version or self.model_version).strip() or "pipeline"
        if version not in PRECISE_MODEL_VERSIONS:
            raise MineruConfigurationError(f"不支持的解析引擎：{version}")
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=True,
        ) as client:
            batch_id, file_url = await self._create_task(
                client,
                filename=filename,
                version=version,
                language=language,
                page_range=page_range,
                enable_table=enable_table,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
            )
            await self._upload_file(client, file_url, content)
            full_zip_url = await self._await_result(client, batch_id)
            zip_bytes = await self._download_zip(client, full_zip_url)
            return self._extract_markdown(zip_bytes, full_zip_url)

    async def _create_task(
        self,
        client: httpx.AsyncClient,
        *,
        filename: str,
        version: str,
        language: str,
        page_range: str | None,
        enable_table: bool,
        is_ocr: bool,
        enable_formula: bool,
    ) -> tuple[str, str]:
        file_payload: dict[str, Any] = {"name": filename, "is_ocr": is_ocr}
        if page_range:
            file_payload["page_ranges"] = page_range
        payload: dict[str, Any] = {
            "files": [file_payload],
            "model_version": version,
            "language": language,
            "enable_table": enable_table,
            "enable_formula": enable_formula,
        }

        last_error: MineruClientError | None = None
        for attempt in range(MAX_MINERU_CREATE_RETRIES + 1):
            try:
                response = await client.post(
                    f"{self.base_url}/file-urls/batch",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise MineruUpstreamError("MinerU 响应不是 JSON 对象")
                data = self._require_success(body)
                batch_id = data.get("batch_id")
                file_urls = data.get("file_urls")
                if (
                    not isinstance(batch_id, str)
                    or not isinstance(file_urls, list)
                    or not file_urls
                ):
                    raise MineruUpstreamError("MinerU 响应缺少 batch_id 或 file_urls")
                return batch_id, str(file_urls[0])
            except httpx.TimeoutException:
                last_error = MineruUpstreamError("MinerU 请求超时")
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                if status_code in {408, 429}:
                    last_error = MineruUpstreamError("MinerU 限频，请稍后重试")
                elif status_code >= 500:
                    last_error = MineruUpstreamError("MinerU 服务暂时不可用")
                else:
                    raise MineruUpstreamError(
                        f"MinerU 请求失败（HTTP {status_code}）"
                    ) from error
            except httpx.RequestError:
                last_error = MineruUpstreamError("无法连接 MinerU 服务")
            except (ValueError, MineruClientError) as error:
                last_error = (
                    error
                    if isinstance(error, MineruClientError)
                    else MineruUpstreamError("MinerU 响应不是有效 JSON")
                )

            if attempt < MAX_MINERU_CREATE_RETRIES:
                logger.warning("MinerU 创建任务失败，准备重试：%s", last_error)

        if last_error is not None:
            raise last_error
        raise MineruUpstreamError("MinerU 创建解析任务失败")

    def _require_success(self, body: dict[str, Any]) -> dict[str, Any]:
        code = body.get("code")
        if code != 0:
            raise MineruUpstreamError(str(body.get("msg") or f"MinerU 返回错误码 {code}"))
        data = body.get("data")
        if not isinstance(data, dict):
            raise MineruUpstreamError("MinerU 响应缺少 data")
        return data

    async def _upload_file(
        self,
        client: httpx.AsyncClient,
        file_url: str,
        content: bytes,
    ) -> None:
        try:
            response = await client.put(file_url, content=content)
        except httpx.RequestError as error:
            raise MineruUpstreamError("无法上传文件到 MinerU") from error
        if response.status_code not in {200, 201, 204}:
            raise MineruUpstreamError(
                f"MinerU 文件上传失败（HTTP {response.status_code}）"
            )

    async def _await_result(self, client: httpx.AsyncClient, batch_id: str) -> str:
        deadline = asyncio.get_event_loop().time() + self.max_poll_seconds
        while True:
            result = await self._poll(client, batch_id)
            if result is not None:
                return result
            if asyncio.get_event_loop().time() >= deadline:
                raise MineruUpstreamError("MinerU 解析超时，请稍后重试")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _poll(self, client: httpx.AsyncClient, batch_id: str) -> str | None:
        try:
            response = await client.get(
                f"{self.base_url}/extract-results/batch/{batch_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.TimeoutException, httpx.RequestError) as error:
            raise MineruUpstreamError("查询 MinerU 任务状态失败") from error
        except (httpx.HTTPStatusError, ValueError) as error:
            raise MineruUpstreamError("MinerU 任务查询返回异常") from error

        if not isinstance(body, dict):
            raise MineruUpstreamError("MinerU 响应不是 JSON 对象")
        data = self._require_success(body)
        results = data.get("extract_result")
        if not isinstance(results, list) or not results:
            return None
        item = results[0]
        if not isinstance(item, dict):
            return None
        state = item.get("state")
        if state == "done":
            full_zip_url = item.get("full_zip_url")
            if not isinstance(full_zip_url, str):
                raise MineruUpstreamError("MinerU 解析完成但缺少结果压缩包链接")
            return full_zip_url
        if state == "failed":
            raise MineruParseFailedError(
                str(item.get("err_msg") or "MinerU 解析失败"),
                code=item.get("err_code"),
            )
        return None

    async def _download_zip(self, client: httpx.AsyncClient, full_zip_url: str) -> bytes:
        host = httpx.URL(full_zip_url).host
        last_error: MineruClientError | None = None
        for attempt in range(MAX_MINERU_DOWNLOAD_RETRIES + 1):
            try:
                response = await client.get(full_zip_url)
                response.raise_for_status()
                return response.content
            except httpx.TimeoutException:
                last_error = MineruUpstreamError(f"下载 MinerU 解析结果超时（{host}）")
            except httpx.RequestError as error:
                last_error = MineruUpstreamError(f"无法连接 MinerU 结果 CDN（{host}）")
                logger.warning("MinerU 结果下载连接失败：%s", error)
            except httpx.HTTPStatusError as error:
                last_error = MineruUpstreamError(
                    f"下载 MinerU 解析结果失败（HTTP {error.response.status_code}，{host}）"
                )
                logger.warning(
                    "MinerU 结果下载返回 HTTP %s：%s",
                    error.response.status_code,
                    full_zip_url,
                )
                break

            if attempt < MAX_MINERU_DOWNLOAD_RETRIES:
                logger.warning("MinerU 结果下载失败，准备重试：%s", last_error)
                await asyncio.sleep(self.poll_interval_seconds)

        if last_error is not None:
            raise last_error
        raise MineruUpstreamError("下载 MinerU 解析结果失败")

    def _extract_markdown(self, zip_bytes: bytes, full_zip_url: str) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
                name = next(
                    (
                        entry
                        for entry in archive.namelist()
                        if entry.replace("\\", "/").endswith("full.md")
                    ),
                    None,
                )
                if name is None:
                    raise MineruUpstreamError("MinerU 结果压缩包缺少 full.md")
                text = archive.read(name).decode("utf-8", errors="replace")
        except (zipfile.BadZipFile, OSError) as error:
            raise MineruUpstreamError("MinerU 结果压缩包损坏或无法读取") from error
        except MineruUpstreamError:
            raise
        if not text or not text.strip():
            raise MineruUpstreamError("MinerU 解析结果为空")
        return text


@lru_cache
def get_mineru_client() -> MineruParseClient:
    return MineruParseClient(
        base_url=settings.mineru_parse_base_url,
        api_key=settings.mineru_parse_api_key,
        model_version=settings.mineru_parse_model_version,
        timeout_seconds=settings.mineru_parse_timeout_seconds,
        poll_interval_seconds=settings.mineru_parse_poll_interval_seconds,
        max_poll_seconds=settings.mineru_parse_max_poll_seconds,
    )
