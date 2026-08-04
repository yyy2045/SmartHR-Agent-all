import json
import logging
import uuid

import httpx
import pytest

from app.services.ai_client import (
    AIConfigurationError,
    AIRequestTimeout,
    AIResponseValidationError,
    AIUpstreamError,
    OpenAICompatibleClient,
)
from app.services.prompt_templates import PublishedPromptSnapshot


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


def prompt_snapshot(
    *,
    scenario: str = "jd_generation",
    version_number: int = 2,
    system_prompt: str = "自定义系统 Prompt：{{title}}",
    user_prompt_template: str = "自定义用户 Prompt：{{jd}}",
    temperature: float = 0.7,
) -> PublishedPromptSnapshot:
    return PublishedPromptSnapshot(
        version_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        scenario=scenario,
        version_number=version_number,
        system_prompt=system_prompt,
        user_prompt_template=user_prompt_template,
        model_parameters={"temperature": temperature},
    )


def resume_payload() -> dict[str, object]:
    return {
        "candidate_code": "CAND-TEST",
        "segments": [{"segment_key": "SEG-0001", "text": "5 年 Python 经验"}],
        "criteria": {
            "criteria_version_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "pass_threshold": 60,
            "hard_requirements": [],
            "scoring_dimensions": [
                {
                    "dimension_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "name": "工程能力",
                    "description": "Python 工程能力",
                }
            ],
        },
    }


def valid_resume_analysis() -> dict[str, object]:
    return {
        "candidate_profile": {
            "education": [],
            "work_experiences": [],
            "projects": [],
            "skills": [
                {
                    "name": "Python",
                    "level": "熟练",
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": "Python"}
                    ],
                }
            ],
            "certifications": [],
            "languages": [],
        },
        "hard_requirements": [],
        "dimension_scores": [
            {
                "dimension_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "score": 80,
                "rationale": "具有明确经验。",
                "missing_items": [],
                "evidence": [
                    {"segment_key": "SEG-0001", "quote": "5 年 Python 经验"}
                ],
            }
        ],
        "strengths": ["Python 经验"],
        "gaps": [],
        "missing_items": [],
        "interview_questions": [],
    }


def interview_report_payload() -> dict[str, object]:
    return {
        "job": {"title": "高级后端工程师"},
        "latest_screening": {
            "total_score": 86,
            "strengths": ["系统设计证据充分"],
            "citations": [{"quote": "负责核心交易系统重构"}],
        },
        "submitted_evaluations": [
            {
                "round_name": "技术一面",
                "overall_recommendation": "recommend",
                "overall_comment": "系统设计能力达到岗位要求。",
            }
        ],
        "missing_rounds": [
            {"round_name": "业务二面", "reason": "not_submitted"}
        ],
    }


def valid_interview_report() -> dict[str, object]:
    return {
        "conclusion": "next_round",
        "executive_summary": "技术能力达到要求，建议完成业务面后再决策。",
        "strengths": ["系统设计证据充分"],
        "concerns": ["业务面评价尚未提交"],
        "follow_up_actions": ["完成业务面"],
    }


def candidate_agent_payload() -> dict[str, object]:
    return {
        "question": "这个候选人的主要风险是什么？",
        "context": {
            "job": {"title": "后端工程师"},
            "candidate": {"full_name": "候选人A", "contacts_visible": True},
            "latest_screening": {
                "ai_group": "passed",
                "evidence_citations": [
                    {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "quote": "负责核心系统重构"}
                ],
            },
        },
        "enterprise_knowledge": {"available": False, "citations": []},
        "decision_boundary": {"ai_must_not": ["自动录用或淘汰候选人"]},
    }


def valid_candidate_agent_answer() -> dict[str, object]:
    return {
        "answer": "候选人具备系统重构经验，但团队规模信息不足，建议在下一轮核实。",
        "evidence_references": [
            {
                "source_type": "latest_screening",
                "source_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "source_label": "AI 初筛证据",
                "quote": "负责核心系统重构",
                "metadata": {"subject_key": "system_design"},
            }
        ],
        "knowledge_citations": [],
        "limitations": ["团队规模未明确"],
        "suggested_follow_up_questions": ["请说明最近一次系统重构中的团队规模和个人职责。"],
    }


@pytest.mark.asyncio
async def test_openai_client_returns_observability_metrics_from_usage() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps(valid_draft(), ensure_ascii=False)}}
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 40,
                    "total_tokens": 160,
                },
            },
        )

    draft, metrics = await make_client(httpx.MockTransport(handler)).structure_jd_with_metrics(
        title="后端工程师",
        department="研发中心",
        jd="负责 Python 与 FastAPI 服务开发。",
    )

    assert draft.suggested_title == "高级后端工程师"
    assert metrics.model_name == "test-model"
    assert metrics.retry_count == 0
    assert metrics.input_tokens == 120
    assert metrics.output_tokens == 40
    assert metrics.total_tokens == 160
    assert metrics.duration_ms >= 0


@pytest.mark.asyncio
async def test_openai_client_sends_json_object_with_schema_and_validates_draft() -> None:
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
    assert request_body["response_format"] == {"type": "json_object"}
    system_prompt = request_body["messages"][0]["content"]
    assert '"suggested_title"' in system_prompt
    assert '"scoring_dimensions"' in system_prompt
    assert "负责 Python 与 FastAPI 服务开发" in request_body["messages"][1]["content"]
    assert requests[0].headers["authorization"] == "Bearer test-api-key"


@pytest.mark.asyncio
async def test_openai_client_renders_published_prompt_snapshot_and_keeps_schema_guard() -> None:
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

    await make_client(httpx.MockTransport(handler)).structure_jd(
        title="后端工程师",
        department="研发",
        jd="负责 FastAPI 服务",
        prompt_template=prompt_snapshot(),
    )

    request_body = json.loads(requests[0].content)
    assert request_body["temperature"] == 0.7
    assert request_body["messages"][0]["content"].startswith("自定义系统 Prompt：后端工程师")
    assert '"suggested_title"' in request_body["messages"][0]["content"]
    assert request_body["messages"][1]["content"] == "自定义用户 Prompt：负责 FastAPI 服务"


@pytest.mark.asyncio
async def test_openai_client_requests_resume_scores_without_model_total() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                valid_resume_analysis(), ensure_ascii=False
                            )
                        }
                    }
                ]
            },
        )

    result = await make_client(httpx.MockTransport(handler)).analyze_resume(
        resume_payload()
    )

    assert result.dimension_scores[0].score == 80
    request_body = json.loads(requests[0].content)
    assert request_body["response_format"] == {"type": "json_object"}
    system_prompt = request_body["messages"][0]["content"]
    assert '"candidate_profile"' in system_prompt
    assert '"dimension_scores"' in system_prompt
    assert '"total_score"' not in system_prompt
    assert '"ai_group"' not in system_prompt
    assert "逐字复制一段连续原文" in system_prompt
    user_payload = json.loads(request_body["messages"][1]["content"])
    assert user_payload == resume_payload()
    assert "private.pdf" not in request_body["messages"][1]["content"]


@pytest.mark.asyncio
async def test_openai_client_generates_strict_interview_report_from_supplied_evidence() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                valid_interview_report(), ensure_ascii=False
                            )
                        }
                    }
                ]
            },
        )

    result = await make_client(
        httpx.MockTransport(handler)
    ).generate_interview_report(interview_report_payload())

    assert result.conclusion == "next_round"
    assert len(requests) == 1
    request_body = json.loads(requests[0].content)
    assert request_body["model"] == "test-model"
    assert request_body["response_format"] == {"type": "json_object"}
    system_prompt = request_body["messages"][0]["content"]
    assert '"conclusion"' in system_prompt
    assert '"executive_summary"' in system_prompt
    assert "缺失面试轮次只能作为风险提示" in system_prompt
    assert json.loads(request_body["messages"][1]["content"]) == (
        interview_report_payload()
    )


@pytest.mark.asyncio
async def test_invalid_interview_report_retries_twice() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )

    with pytest.raises(AIResponseValidationError):
        await make_client(
            httpx.MockTransport(handler)
        ).generate_interview_report(interview_report_payload())

    assert attempts == 3


@pytest.mark.asyncio
async def test_openai_client_answers_candidate_agent_question_with_evidence_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                valid_candidate_agent_answer(), ensure_ascii=False
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 180,
                    "completion_tokens": 90,
                    "total_tokens": 270,
                },
            },
        )

    result, metrics = await make_client(
        httpx.MockTransport(handler)
    ).answer_candidate_question_with_metrics(candidate_agent_payload())

    assert "系统重构经验" in result.answer
    assert result.evidence_references[0].source_type == "latest_screening"
    assert metrics.total_tokens == 270
    request_body = json.loads(requests[0].content)
    assert request_body["response_format"] == {"type": "json_object"}
    assert '"evidence_references"' in request_body["messages"][0]["content"]
    assert '"suggested_follow_up_questions"' in request_body["messages"][0]["content"]
    assert json.loads(request_body["messages"][1]["content"]) == candidate_agent_payload()


@pytest.mark.asyncio
async def test_resume_contract_feedback_requests_one_corrected_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                valid_resume_analysis(), ensure_ascii=False
                            )
                        }
                    }
                ]
            },
        )

    await make_client(httpx.MockTransport(handler)).analyze_resume(
        resume_payload(),
        validation_feedback="证据引用不属于对应简历片段：SEG-0001",
        previous_analysis=valid_resume_analysis(),
    )

    request_body = json.loads(requests[0].content)
    system_prompt = request_body["messages"][0]["content"]
    assert "上一次输出未通过后端合同校验" in system_prompt
    assert "SEG-0001" in system_prompt
    user_payload = json.loads(request_body["messages"][1]["content"])
    assert user_payload["resume_input"] == resume_payload()
    assert user_payload["previous_analysis"] == valid_resume_analysis()
    assert user_payload["repair_task"].startswith("只纠正证据引用")


@pytest.mark.asyncio
async def test_invalid_resume_analysis_retries_twice() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )

    with pytest.raises(AIResponseValidationError):
        await make_client(httpx.MockTransport(handler)).analyze_resume(resume_payload())

    assert attempts == 3


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
