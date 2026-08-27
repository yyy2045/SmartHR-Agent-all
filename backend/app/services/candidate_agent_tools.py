from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.schemas.candidate_agent import (
    CandidateAgentAnswerDraft,
    CandidateAgentKnowledgeCitation,
    CandidateAgentReportAIDraft,
)
from app.schemas.recruitment_knowledge import RecruitmentKnowledgeRetrievalRequest
from app.services.embedding_client import EmbeddingClientError
from app.services.recruitment_knowledge import retrieve_recruitment_knowledge

SUBMIT_ANSWER_TOOL = "submit_answer"
SUBMIT_REPORT_TOOL = "submit_report"

_KNOWLEDGE_CATEGORIES = {
    "policy",
    "job_standard",
    "interview",
    "offer",
    "compensation",
    "communication",
    "general",
}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    terminal: bool = False


@dataclass(frozen=True)
class TerminalSubmission:
    draft: CandidateAgentAnswerDraft | CandidateAgentReportAIDraft


def terminal_tool_name(goal: str) -> str:
    return SUBMIT_REPORT_TOOL if goal == "report" else SUBMIT_ANSWER_TOOL


def _object_schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _function_tool(definition: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.parameters,
        },
    }


def build_tool_definitions(goal: str) -> list[ToolDefinition]:
    data_tools = [
        ToolDefinition(
            name="get_candidate_profile",
            description=(
                "获取候选人结构化资料（教育/工作/项目/技能/证书/语言）与主简历文档信息。"
            ),
            parameters=_object_schema({}),
        ),
        ToolDefinition(
            name="get_latest_screening",
            description=(
                "获取最新一次 AI 初筛结果（分组、总分、阈值、亮点、缺口、证据引用与"
                "招聘专员当前判定）。"
            ),
            parameters=_object_schema({}),
        ),
        ToolDefinition(
            name="get_interview_evaluations",
            description="获取已提交的面试评价（轮次、总体建议、评分、是否通过）。",
            parameters=_object_schema(
                {"limit": {"type": "integer", "minimum": 1, "maximum": 10}},
            ),
        ),
        ToolDefinition(
            name="get_interview_report",
            description="获取已生成的面试报告（结论、摘要、亮点、顾虑、后续行动）。",
            parameters=_object_schema({}),
        ),
        ToolDefinition(
            name="get_offer_and_onboarding",
            description="获取 Offer 与入职状态（当前版本、状态、入职日期）。",
            parameters=_object_schema({}),
        ),
        ToolDefinition(
            name="search_enterprise_knowledge",
            description=(
                "检索企业招聘知识库（制度、岗位标准、面试、Offer、沟通话术等），"
                "仅作制度/标准引用，不能替代候选人证据。"
            ),
            parameters=_object_schema(
                {
                    "query": {"type": "string", "maxLength": 4000},
                    "purpose": {
                        "type": "string",
                        "enum": sorted(_KNOWLEDGE_CATEGORIES),
                    },
                },
                required=["query", "purpose"],
            ),
        ),
    ]
    if goal == "report":
        terminal = ToolDefinition(
            name=SUBMIT_REPORT_TOOL,
            description="收齐证据后，调用此工具一次性提交完整研判报告。",
            parameters=CandidateAgentReportAIDraft.model_json_schema(),
            terminal=True,
        )
    else:
        terminal = ToolDefinition(
            name=SUBMIT_ANSWER_TOOL,
            description="收齐证据后，调用此工具一次性提交最终回答。",
            parameters=CandidateAgentAnswerDraft.model_json_schema(),
            terminal=True,
        )
    return [*data_tools, terminal]


def build_openai_tools(goal: str) -> list[dict[str, Any]]:
    return [_function_tool(item) for item in build_tool_definitions(goal)]


class CandidateAgentToolDispatcher:
    def __init__(
        self,
        *,
        db: Session,
        context: dict[str, Any],
        actor: User,
        job_id: uuid.UUID,
        application_id: uuid.UUID,
        scenario: str,
        response_type: type[CandidateAgentAnswerDraft] | type[CandidateAgentReportAIDraft],
    ) -> None:
        self.db = db
        self.context = context
        self.actor = actor
        self.job_id = job_id
        self.application_id = application_id
        self.scenario = scenario
        self.response_type = response_type

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> TerminalSubmission | dict[str, Any]:
        if name in {SUBMIT_ANSWER_TOOL, SUBMIT_REPORT_TOOL}:
            return TerminalSubmission(draft=self.response_type.model_validate(arguments))
        if name == "get_candidate_profile":
            return {
                "candidate": self.context.get("candidate"),
                "candidate_profile": self.context.get("candidate_profile"),
                "primary_document": self.context.get("primary_document"),
            }
        if name == "get_latest_screening":
            return {"latest_screening": self.context.get("latest_screening")}
        if name == "get_interview_evaluations":
            evaluations = self.context.get("interview_evaluations") or []
            limit = arguments.get("limit")
            if isinstance(limit, int) and limit > 0:
                evaluations = evaluations[:limit]
            return {"interview_evaluations": evaluations}
        if name == "get_interview_report":
            return {"interview_report": self.context.get("interview_report")}
        if name == "get_offer_and_onboarding":
            return {
                "offer": self.context.get("offer"),
                "onboarding": self.context.get("onboarding"),
            }
        if name == "search_enterprise_knowledge":
            return await self._search_knowledge(arguments)
        return {"error": f"未知工具：{name}"}

    async def _search_knowledge(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not settings.embedding_enabled:
            return {"available": False, "citations": [], "note": "企业知识库检索未启用"}
        query = str(arguments.get("query") or "").strip()
        if not query:
            return {"available": False, "citations": [], "note": "检索查询不能为空"}
        purpose = arguments.get("purpose")
        category = purpose if purpose in _KNOWLEDGE_CATEGORIES else None
        try:
            response = await retrieve_recruitment_knowledge(
                self.db,
                RecruitmentKnowledgeRetrievalRequest(
                    scenario=self.scenario,
                    query=query[:4000],
                    category=category,
                    limit=5,
                    resource_type="job_application",
                    resource_id=self.application_id,
                    job_id=self.job_id,
                    application_id=self.application_id,
                ),
                actor=self.actor,
            )
        except EmbeddingClientError as error:
            return {"available": False, "citations": [], "note": f"知识库检索失败：{error}"}
        citations = [
            CandidateAgentKnowledgeCitation(
                chunk_id=citation.chunk_id,
                document_id=citation.document_id,
                document_title=citation.document_title,
                snippet=citation.snippet,
                score=citation.score,
                metadata={
                    "version_number": citation.version_number,
                    "category": citation.category,
                    "heading_path": citation.heading_path,
                    "source_locator": citation.source_locator,
                },
            )
            for citation in response.citations
        ]
        return {
            "available": True,
            "citations": [item.model_dump(mode="json") for item in citations],
        }
