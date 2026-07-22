import json
import logging

import httpx
import pytest

from app.services.ai_client import (
    AIConfigurationError,
    AIRequestTimeout,
    AIResponseValidationError,
    AIUpstreamError,
    OpenAICompatibleClient,
)


def valid_draft() -> dict[str, object]:
    return {
        "suggested_title": "高级后端工程师",
        "summary": "负责核心服务设计、开发与稳定性建设。",
        "pass_threshold": 65,
        "hard_requirements": [
            {
                "requirement_type": "min_experience_years",
                "title": "相关经验",
                "description": "后端服务开发经验",
                "expected_value": "3 年",
                "auto_reject": True,
                "sort_order": 0,
            }
        ],
        "scoring_dimensions": [
            {
                "name": "系统设计",
                "description": "关注可扩展架构设计",
                "weight_percent": 60,
                "sort_order": 0,
            },
            {
                "name": "工程质量",
                "description": "关注测试和稳定性",
                "weight_percent": 40,
                "sort_order": 1,
            },
        ],
    }


def make_client(transport: httpx.AsyncBaseTransport) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url="https://model.example/v1",
        api_key="test-api-key",
        model="test-model",
        timeout_seconds=10,
        max_concurrency=2,
        transport=transport,
    )


@pytest.mark.asyncio
async def test_openai_client_sends_json_schema_and_returns_validated_draft() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(valid_draft(), ensure_ascii=False)}}
                ]
            },
        )

    draft = await make_client(httpx.MockTransport(handler)).structure_jd(
        title="后端工程师",
        department="研发中心",
        jd="负责 Python 与 FastAPI 服务开发。",
    )

    assert draft.suggested_title == "高级后端工程师"
    assert sum(item.weight_percent for item in draft.scoring_dimensions) == 100
    assert len(requests) == 1
    request_body = json.loads(requests[0].content)
    assert request_body["model"] == "test-model"
    assert request_body["response_format"]["type"] == "json_schema"
    assert request_body["response_format"]["json_schema"]["strict"] is True
    assert "负责 Python 与 FastAPI 服务开发" in request_body["messages"][1]["content"]
    assert requests[0].headers["authorization"] == "Bearer test-api-key"


@pytest.mark.asyncio
async def test_invalid_model_output_retries_twice_without_logging_jd(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempts = 0
    sensitive_jd = "内部保密项目代号 NEBULA-77"

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        draft = valid_draft()
        if attempts < 3:
            draft["scoring_dimensions"] = [
                {
                    "name": "系统设计",
                    "description": "",
                    "weight_percent": 80,
                    "sort_order": 0,
                }
            ]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(draft)}}]},
        )

    with caplog.at_level(logging.WARNING):
        result = await make_client(httpx.MockTransport(handler)).structure_jd(
            title="工程师",
            department="研发",
            jd=sensitive_jd,
        )

    assert attempts == 3
    assert result.suggested_title == "高级后端工程师"
    assert sensitive_jd not in caplog.text


@pytest.mark.asyncio
async def test_timeout_and_invalid_output_fail_after_three_attempts() -> None:
    timeout_attempts = 0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal timeout_attempts
        timeout_attempts += 1
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(AIRequestTimeout):
        await make_client(httpx.MockTransport(timeout_handler)).structure_jd(
            title="工程师",
            department="研发",
            jd="JD",
        )
    assert timeout_attempts == 3

    invalid_attempts = 0

    def invalid_handler(_: httpx.Request) -> httpx.Response:
        nonlocal invalid_attempts
        invalid_attempts += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    with pytest.raises(AIResponseValidationError):
        await make_client(httpx.MockTransport(invalid_handler)).structure_jd(
            title="工程师",
            department="研发",
            jd="JD",
        )
    assert invalid_attempts == 3


@pytest.mark.asyncio
async def test_configuration_and_non_retryable_http_errors_are_readable() -> None:
    unconfigured = OpenAICompatibleClient(
        base_url="https://api.example.com/v1",
        api_key="",
        model="",
        timeout_seconds=10,
        max_concurrency=1,
    )
    with pytest.raises(AIConfigurationError, match="AI_BASE_URL"):
        await unconfigured.structure_jd(title="工程师", department="", jd="JD")

    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    with pytest.raises(AIUpstreamError, match="HTTP 401"):
        await make_client(httpx.MockTransport(handler)).structure_jd(
            title="工程师",
            department="研发",
            jd="JD",
        )
    assert attempts == 1
