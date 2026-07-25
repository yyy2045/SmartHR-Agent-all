import httpx
import pytest

from app.services.embedding_client import (
    EmbeddingConfigurationError,
    EmbeddingResponseValidationError,
    OpenAICompatibleEmbeddingClient,
)


def make_client(
    transport: httpx.AsyncBaseTransport,
) -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        base_url="https://embedding.example/v1",
        api_key="test-embedding-key",
        model="test-embedding-model",
        dimension=3,
        version="v1",
        timeout_seconds=10,
        batch_size=2,
        max_concurrency=2,
        transport=transport,
    )


@pytest.mark.asyncio
async def test_embedding_client_orders_and_validates_vectors() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                ]
            },
        )

    result = await make_client(httpx.MockTransport(handler)).embed(["教育", "项目"])

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert requests[0].headers["authorization"] == "Bearer test-embedding-key"
    assert b'"model":"test-embedding-model"' in requests[0].content


@pytest.mark.asyncio
async def test_embedding_client_retries_invalid_vectors_and_rejects_non_finite_values() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            content=b'{"data":[{"index":0,"embedding":[0.1,1e999,0.3]}]}',
            headers={"Content-Type": "application/json"},
        )

    with pytest.raises(EmbeddingResponseValidationError, match="非有限值"):
        await make_client(httpx.MockTransport(handler)).embed(["工作经历"])

    assert attempts == 3


@pytest.mark.asyncio
async def test_embedding_client_requires_real_configuration() -> None:
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://api.example.com/v1",
        api_key="",
        model="",
        dimension=3,
        version="v1",
        timeout_seconds=10,
        batch_size=2,
        max_concurrency=1,
    )

    with pytest.raises(EmbeddingConfigurationError, match="EMBEDDING_BASE_URL"):
        await client.embed(["测试"])
