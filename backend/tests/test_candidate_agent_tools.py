import uuid

import pytest
from pydantic import ValidationError

from app.config import settings
from app.models import User
from app.schemas.candidate_agent import CandidateAgentAnswerDraft, CandidateAgentReportAIDraft
from app.schemas.recruitment_knowledge import (
    RecruitmentKnowledgeRetrievalCitation,
    RecruitmentKnowledgeRetrievalResponse,
)
from app.services.candidate_agent_tools import (
    CandidateAgentToolDispatcher,
    TerminalSubmission,
    build_openai_tools,
    build_tool_definitions,
)


def _context() -> dict[str, object]:
    return {
        "candidate": {"full_name": "候选人A"},
        "candidate_profile": {"skills": ["Python"]},
        "primary_document": {"original_filename": "resume.pdf"},
        "latest_screening": {"ai_group": "passed"},
        "interview_evaluations": [
            {"round_name": "技术一面"},
            {"round_name": "业务二面"},
        ],
        "interview_report": {"conclusion": "next_round"},
        "offer": {"status": "approved"},
        "onboarding": {"status": "pending_start"},
    }


def _dispatcher(
    context: dict[str, object] | None = None,
    *,
    response_type: type[CandidateAgentAnswerDraft] | type[CandidateAgentReportAIDraft] = (
        CandidateAgentAnswerDraft
    ),
) -> CandidateAgentToolDispatcher:
    return CandidateAgentToolDispatcher(
        db=None,  # type: ignore[arg-type]
        context=context or _context(),
        actor=User(),  # type: ignore[call-arg]
        job_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        scenario="candidate_qa",
        response_type=response_type,
    )


def _valid_answer() -> dict[str, object]:
    return {
        "answer": "候选人系统重构经验较强。",
        "evidence_references": [
            {"source_type": "latest_screening", "source_label": "AI 初筛"}
        ],
    }


def test_build_tool_definitions_select_terminal_by_goal() -> None:
    answer_names = [item.name for item in build_tool_definitions("answer")]
    report_names = [item.name for item in build_tool_definitions("report")]

    assert "submit_answer" in answer_names
    assert "submit_report" not in answer_names
    assert "submit_report" in report_names
    assert "submit_answer" not in report_names
    assert len(answer_names) == 7
    assert len(report_names) == 7


def test_build_openai_tools_wraps_function_schema() -> None:
    tools = build_openai_tools("answer")

    assert len(tools) == 7
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "get_candidate_profile"
    assert "parameters" in tools[0]["function"]
    terminal = tools[-1]["function"]
    assert terminal["name"] == "submit_answer"
    assert terminal["parameters"]["type"] == "object"


@pytest.mark.asyncio
async def test_dispatcher_returns_context_slices() -> None:
    dispatcher = _dispatcher()

    profile = await dispatcher.execute("get_candidate_profile", {})
    assert set(profile.keys()) == {"candidate", "candidate_profile", "primary_document"}

    screening = await dispatcher.execute("get_latest_screening", {})
    assert screening["latest_screening"] == {"ai_group": "passed"}

    evaluations = await dispatcher.execute("get_interview_evaluations", {"limit": 1})
    assert len(evaluations["interview_evaluations"]) == 1

    report = await dispatcher.execute("get_interview_report", {})
    assert report["interview_report"] == {"conclusion": "next_round"}

    offer = await dispatcher.execute("get_offer_and_onboarding", {})
    assert offer["offer"] == {"status": "approved"}
    assert offer["onboarding"] == {"status": "pending_start"}


@pytest.mark.asyncio
async def test_dispatcher_unknown_tool_returns_error() -> None:
    dispatcher = _dispatcher()
    result = await dispatcher.execute("unknown_tool", {})

    assert result == {"error": "未知工具：unknown_tool"}


@pytest.mark.asyncio
async def test_dispatcher_submit_answer_validates_draft() -> None:
    dispatcher = _dispatcher()
    result = await dispatcher.execute("submit_answer", _valid_answer())

    assert isinstance(result, TerminalSubmission)
    assert isinstance(result.draft, CandidateAgentAnswerDraft)
    assert result.draft.answer == "候选人系统重构经验较强。"


@pytest.mark.asyncio
async def test_dispatcher_submit_answer_rejects_invalid_arguments() -> None:
    dispatcher = _dispatcher()

    with pytest.raises(ValidationError):
        await dispatcher.execute("submit_answer", {"answer": ""})


@pytest.mark.asyncio
async def test_search_knowledge_embedding_disabled_returns_unavailable() -> None:
    dispatcher = _dispatcher()
    result = await dispatcher.execute(
        "search_enterprise_knowledge",
        {"query": "入职流程", "purpose": "policy"},
    )

    assert result == {
        "available": False,
        "citations": [],
        "note": "企业知识库检索未启用",
    }


@pytest.mark.asyncio
async def test_search_knowledge_maps_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    async def fake_retrieve(db, request, actor):
        return RecruitmentKnowledgeRetrievalResponse(
            query_hash="hash",
            returned_count=1,
            filtered_count=1,
            citations=[
                RecruitmentKnowledgeRetrievalCitation(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    document_title="入职管理制度",
                    version_number=3,
                    category="policy",
                    heading_path=["入职", "流程"],
                    source_locator="3.2 入职流程",
                    snippet="候选人入职前需完成背景调查。",
                    score=0.91,
                )
            ],
        )

    monkeypatch.setattr(settings, "embedding_enabled", True)
    monkeypatch.setattr(
        "app.services.candidate_agent_tools.retrieve_recruitment_knowledge",
        fake_retrieve,
    )

    dispatcher = _dispatcher()
    result = await dispatcher.execute(
        "search_enterprise_knowledge",
        {"query": "入职背景调查", "purpose": "policy"},
    )

    assert result["available"] is True
    citation = result["citations"][0]
    assert citation["document_title"] == "入职管理制度"
    assert citation["snippet"] == "候选人入职前需完成背景调查。"
    assert citation["metadata"]["version_number"] == 3
    assert citation["metadata"]["category"] == "policy"
    assert citation["metadata"]["heading_path"] == ["入职", "流程"]
    assert citation["metadata"]["source_locator"] == "3.2 入职流程"
