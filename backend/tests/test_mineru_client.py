import io
import json
import zipfile

import httpx
import pytest

from app.services.mineru_client import (
    MineruConfigurationError,
    MineruParseClient,
    MineruParseFailedError,
    MineruUpstreamError,
)

BASE_URL = "https://mineru.net/api/v4"
API_KEY = "test-token"
BATCH_ID = "2bb2f0ec-a336-4a0a-b61a-241afaf9cc87"
FILE_URL = "https://oss.example.com/api-upload/demo.pdf"
FULL_ZIP_URL = "https://cdn-mineru.openxlab.org.cn/pdf/018e53ad.zip"


def _zip_bytes(markdown: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("full.md", markdown)
    return buffer.getvalue()


def _create_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "data": {"batch_id": BATCH_ID, "file_urls": [FILE_URL]},
            "msg": "ok",
        },
    )


def _poll_response(state: str, **extra: object) -> httpx.Response:
    data: dict[str, object] = {"file_name": "demo.pdf", "state": state, **extra}
    return httpx.Response(
        200,
        json={"code": 0, "data": {"batch_id": BATCH_ID, "extract_result": [data]}, "msg": "ok"},
    )


def _make_client(handler, **overrides) -> MineruParseClient:
    return MineruParseClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout_seconds=30,
        poll_interval_seconds=0.0,
        max_poll_seconds=30,
        transport=httpx.MockTransport(handler),
        **overrides,
    )


@pytest.mark.asyncio
async def test_parse_file_downloads_markdown_after_polling() -> None:
    polls = {"count": 0}
    markdown = "# 岗位说明\n候选人需要说明资源边界。"
    api_prefix = "/api/v4"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == f"{api_prefix}/file-urls/batch":
            assert request.headers["Authorization"] == f"Bearer {API_KEY}"
            return _create_response()
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "GET" and path == f"{api_prefix}/extract-results/batch/{BATCH_ID}":
            polls["count"] += 1
            return _poll_response("running") if polls["count"] < 2 else _poll_response(
                "done", full_zip_url=FULL_ZIP_URL
            )
        if request.method == "GET" and path == "/pdf/018e53ad.zip":
            return httpx.Response(200, content=_zip_bytes(markdown))
        return httpx.Response(404)

    text = await _make_client(handler).parse_file("demo.pdf", b"%PDF-1.4")
    assert "资源边界" in text
    assert polls["count"] == 2


@pytest.mark.asyncio
async def test_parse_file_forwards_model_version_ocr_and_page_range() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/file-urls/batch"):
            captured["payload"] = json.loads(request.content)
            return _create_response()
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "GET" and request.url.path.endswith(BATCH_ID):
            return _poll_response("done", full_zip_url=FULL_ZIP_URL)
        if request.method == "GET" and request.url.path.endswith(".zip"):
            return httpx.Response(200, content=_zip_bytes("# 标题"))
        return httpx.Response(404)

    await _make_client(handler).parse_file(
        "demo.pdf", b"x", model_version="vlm", is_ocr=True, page_range="1-5"
    )
    assert captured["payload"]["model_version"] == "vlm"
    assert captured["payload"]["files"][0]["is_ocr"] is True
    assert captured["payload"]["files"][0]["page_ranges"] == "1-5"


@pytest.mark.asyncio
async def test_parse_file_raises_when_task_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _create_response()
        if request.method == "PUT":
            return httpx.Response(200)
        return _poll_response(
            "failed",
            err_code=-30003,
            err_msg="file page count exceeds limit",
        )

    with pytest.raises(MineruParseFailedError) as exc_info:
        await _make_client(handler).parse_file("demo.pdf", b"x")
    assert exc_info.value.code == -30003
    assert "page count" in str(exc_info.value)


@pytest.mark.asyncio
async def test_parse_file_raises_when_download_returns_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return _create_response()
        if request.method == "PUT":
            return httpx.Response(200)
        if request.method == "GET" and request.url.path.endswith(BATCH_ID):
            return _poll_response("done", full_zip_url=FULL_ZIP_URL)
        return httpx.Response(403)

    with pytest.raises(MineruUpstreamError) as exc_info:
        await _make_client(handler).parse_file("demo.pdf", b"x")
    assert "HTTP 403" in str(exc_info.value)
    assert "cdn-mineru.openxlab.org.cn" in str(exc_info.value)


@pytest.mark.asyncio
async def test_parse_file_raises_configuration_error_without_api_key() -> None:
    client = MineruParseClient(
        base_url=BASE_URL,
        api_key="",
        timeout_seconds=30,
        poll_interval_seconds=0.0,
        max_poll_seconds=30,
    )
    with pytest.raises(MineruConfigurationError):
        await client.parse_file("demo.pdf", b"x")
