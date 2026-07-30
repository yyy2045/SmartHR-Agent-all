from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    Candidate,
    CandidateProfile,
    HardRequirement,
    Job,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeTextSegment,
    Role,
    ScoringDimension,
    TalentRecommendationResult,
    TalentRecommendationRun,
    User,
    UserRole,
)
from app.schemas.screening import ResumeAnalysisDraft
from app.services.ai_client import RESUME_MATCH_PROMPT_VERSION, AIUpstreamError
from app.services.talent_recommendation_rescoring import (
    rescore_talent_recommendations,
)


@dataclass(frozen=True)
class RescoringDependencies:
    session_factory: sessionmaker[Session]
    run_id: uuid.UUID
    result_ids: tuple[uuid.UUID, ...]
    requirement_id: uuid.UUID
    dimension_id: uuid.UUID


class StubAIClient:
    def __init__(
        self,
        responses: list[ResumeAnalysisDraft | Exception],
        *,
        model: str = "test-ai",
    ) -> None:
        self.model = model
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def analyze_resume(
        self,
        payload: dict[str, object],
        *,
        validation_feedback: str | None = None,
        previous_analysis: dict[str, object] | None = None,
    ) -> ResumeAnalysisDraft:
        self.calls.append(
            {
                "payload": payload,
                "validation_feedback": validation_feedback,
                "previous_analysis": previous_analysis,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CancellingAIClient(StubAIClient):
    def __init__(
        self,
        dependency: RescoringDependencies,
        response: ResumeAnalysisDraft,
    ) -> None:
        super().__init__([response])
        self.dependency = dependency

    async def analyze_resume(
        self,
        payload: dict[str, object],
        *,
        validation_feedback: str | None = None,
        previous_analysis: dict[str, object] | None = None,
    ) -> ResumeAnalysisDraft:
        with self.dependency.session_factory() as db:
            run = db.get(TalentRecommendationRun, self.dependency.run_id)
            assert run is not None
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            db.commit()
        return await super().analyze_resume(
            payload,
            validation_feedback=validation_feedback,
            previous_analysis=previous_analysis,
        )


def _analysis(
    dependency: RescoringDependencies,
    *,
    score: int = 88,
    quote: str = "Python",
) -> ResumeAnalysisDraft:
    return ResumeAnalysisDraft.model_validate(
        {
            "candidate_profile": {
                "education": [],
                "work_experiences": [],
                "projects": [],
                "skills": [
                    {
                        "name": "Python",
                        "level": "熟练",
                        "evidence": [
                            {"segment_key": "SEG-0001", "quote": quote}
                        ],
                    }
                ],
                "certifications": [],
                "languages": [],
            },
            "hard_requirements": [
                {
                    "requirement_id": str(dependency.requirement_id),
                    "status": "passed",
                    "rationale": "简历明确包含 Python",
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": quote}
                    ],
                }
            ],
            "dimension_scores": [
                {
                    "dimension_id": str(dependency.dimension_id),
                    "score": score,
                    "rationale": "Python 经验符合岗位需要",
                    "missing_items": [],
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": quote}
                    ],
                }
            ],
            "strengths": ["Python"],
            "gaps": [],
            "missing_items": [],
            "interview_questions": ["请介绍 Python 项目"],
        }
    )


@pytest.fixture
def rescoring_dependencies(tmp_path: Path) -> Iterator[RescoringDependencies]:
    database_path = tmp_path / "talent-rescoring.sqlite3"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    requirement_id = uuid.uuid4()
    dimension_id = uuid.uuid4()
    with testing_session() as db:
        recruiter_role = Role(key="recruiter", display_name="招聘专员")
        recruiter = User(
            username="rescoring-recruiter",
            password_hash="hashed",
            display_name="重评招聘专员",
            is_active=True,
            must_change_password=False,
            role_assignments=[UserRole(role=recruiter_role)],
        )
        job = Job(
            owner=recruiter,
            title="Python 后端工程师",
            department="招聘平台",
            original_jd="负责 Python 后端开发",
            status="active",
        )
        criteria = JobCriteriaVersion(
            job=job,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_at=datetime.now(UTC),
            hard_requirements=[
                HardRequirement(
                    id=requirement_id,
                    requirement_type="other",
                    title="Python",
                    description="具备 Python 开发能力",
                    expected_value="熟练",
                    auto_reject=False,
                    sort_order=0,
                )
            ],
            scoring_dimensions=[
                ScoringDimension(
                    id=dimension_id,
                    name="Python 工程能力",
                    description="能够建设稳定后端服务",
                    weight_percent=100,
                    sort_order=0,
                )
            ],
        )
        candidate = Candidate(full_name="AI 重评候选人")
        document = ResumeDocument(
            candidate=candidate,
            original_filename="candidate.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            sha256="a" * 64,
            status="completed",
            redacted_at=datetime.now(UTC),
            text_segments=[
                ResumeTextSegment(
                    segment_key="SEG-0001",
                    source_type="pdf_page",
                    source_index=0,
                    page_number=1,
                    raw_text="电话 13800138000，熟练使用 Python 开发后端服务",
                    normalized_text="电话 13800138000，熟练使用 Python 开发后端服务",
                    redacted_text="电话 [PHONE]，熟练使用 Python 开发后端服务",
                    sort_order=0,
                )
            ],
        )
        profile = CandidateProfile(
            document=document,
            version_number=1,
            source="ai",
            model_name="profile-test",
            prompt_version="profile-v1",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[
                {
                    "name": "Python",
                    "level": "熟练",
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": "Python"}
                    ],
                }
            ],
            certifications=[],
            languages=[],
        )
        db.add_all([recruiter_role, recruiter, job, criteria, candidate, document, profile])
        db.flush()
        criteria_snapshot = {
            "criteria_version_id": str(criteria.id),
            "version_number": 1,
            "pass_threshold": 60,
            "hard_requirements": [
                {
                    "requirement_id": str(requirement_id),
                    "requirement_type": "other",
                    "title": "Python",
                    "description": "具备 Python 开发能力",
                    "expected_value": "熟练",
                    "auto_reject": False,
                    "sort_order": 0,
                }
            ],
            "scoring_dimensions": [
                {
                    "dimension_id": str(dimension_id),
                    "name": "Python 工程能力",
                    "description": "能够建设稳定后端服务",
                    "weight_percent": 100,
                    "sort_order": 0,
                }
            ],
        }
        run = TalentRecommendationRun(
            job=job,
            criteria_version=criteria,
            created_by=recruiter,
            created_by_username_snapshot=recruiter.username,
            created_by_display_name_snapshot=recruiter.display_name,
            idempotency_key=uuid.uuid4(),
            status="rescoring",
            ai_input_mode="raw",
            criteria_snapshot=criteria_snapshot,
            embedding_model_snapshot="test-embedding",
            ai_model_snapshot="test-ai",
            prompt_version_snapshot=RESUME_MATCH_PROMPT_VERSION,
            celery_task_id="rescoring-task-1",
            scope_candidate_count=1,
            retrieved_count=1,
            started_at=datetime.now(UTC),
        )
        result = TalentRecommendationResult(
            run=run,
            candidate=candidate,
            resolved_candidate=candidate,
            candidate_code_snapshot=candidate.candidate_code,
            candidate_name_snapshot=candidate.full_name,
            document=document,
            document_sha256_snapshot=document.sha256,
            document_updated_at_snapshot=document.updated_at,
            candidate_profile=profile,
            profile_version_snapshot=1,
            embedding_model_snapshot="test-embedding",
            embedding_version_snapshot="v1",
            embedding_dimension_snapshot=2,
            vector_rank=1,
            similarity_score=0.8,
            matched_group_ids=[],
            matched_chunks=[],
            status="retrieved",
            ai_dimension_scores=[],
            ai_hard_requirement_results=[],
            ai_strengths=[],
            ai_gaps=[],
            ai_missing_items=[],
            ai_interview_questions=[],
            ai_evidence=[],
        )
        db.add_all([run, result])
        db.commit()
        dependency = RescoringDependencies(
            session_factory=testing_session,
            run_id=run.id,
            result_ids=(result.id,),
            requirement_id=requirement_id,
            dimension_id=dimension_id,
        )
    yield dependency
    Base.metadata.drop_all(engine)
    engine.dispose()


def _add_second_retrieved_result(
    dependency: RescoringDependencies,
) -> uuid.UUID:
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        assert run is not None
        candidate = Candidate(full_name="第二名 AI 重评候选人")
        document = ResumeDocument(
            candidate=candidate,
            original_filename="candidate-2.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=120,
            sha256="b" * 64,
            status="completed",
            redacted_at=datetime.now(UTC),
            text_segments=[
                ResumeTextSegment(
                    segment_key="SEG-0001",
                    source_type="pdf_page",
                    source_index=0,
                    page_number=1,
                    raw_text="熟练使用 Python 开发后端服务",
                    normalized_text="熟练使用 Python 开发后端服务",
                    redacted_text="熟练使用 Python 开发后端服务",
                    sort_order=0,
                )
            ],
        )
        profile = CandidateProfile(
            document=document,
            version_number=1,
            source="ai",
            model_name="profile-test",
            prompt_version="profile-v1",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[
                {
                    "name": "Python",
                    "level": "熟练",
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": "Python"}
                    ],
                }
            ],
            certifications=[],
            languages=[],
        )
        db.add_all([candidate, document, profile])
        db.flush()
        result = TalentRecommendationResult(
            run=run,
            candidate=candidate,
            resolved_candidate=candidate,
            candidate_code_snapshot=candidate.candidate_code,
            candidate_name_snapshot=candidate.full_name,
            document=document,
            document_sha256_snapshot=document.sha256,
            document_updated_at_snapshot=document.updated_at,
            candidate_profile=profile,
            profile_version_snapshot=1,
            embedding_model_snapshot="test-embedding",
            embedding_version_snapshot="v1",
            embedding_dimension_snapshot=2,
            vector_rank=2,
            similarity_score=0.7,
            matched_group_ids=[],
            matched_chunks=[],
            status="retrieved",
            ai_dimension_scores=[],
            ai_hard_requirement_results=[],
            ai_strengths=[],
            ai_gaps=[],
            ai_missing_items=[],
            ai_interview_questions=[],
            ai_evidence=[],
        )
        run.scope_candidate_count = 2
        run.retrieved_count = 2
        db.add(result)
        db.commit()
        return result.id


@pytest.mark.parametrize(
    ("ai_input_mode", "expected_text", "forbidden_text"),
    [
        ("raw", "13800138000", "[PHONE]"),
        ("redacted", "[PHONE]", "13800138000"),
    ],
)
def test_rescoring_uses_locked_input_mode_and_saves_complete_snapshot(
    rescoring_dependencies: RescoringDependencies,
    ai_input_mode: str,
    expected_text: str,
    forbidden_text: str,
) -> None:
    dependency = rescoring_dependencies
    with dependency.session_factory() as db:
        db.execute(
            update(TalentRecommendationRun)
            .where(TalentRecommendationRun.id == dependency.run_id)
            .values(ai_input_mode=ai_input_mode)
        )
        db.commit()
    client = StubAIClient([_analysis(dependency)])

    response = asyncio.run(
        rescore_talent_recommendations(
            dependency.run_id,
            task_id="rescoring-task-1",
            session_factory=dependency.session_factory,
            ai_client=client,
        )
    )

    assert response["status"] == "completed"
    payload = client.calls[0]["payload"]
    serialized_payload = str(payload)
    assert expected_text in serialized_payload
    assert forbidden_text not in serialized_payload
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        result = db.get(TalentRecommendationResult, dependency.result_ids[0])
        assert run is not None and result is not None
        assert run.rescored_count == 1
        assert run.completed_count == 1
        assert run.failed_count == 0
        assert result.status == "completed"
        assert float(result.ai_score or 0) == 88
        assert result.ai_group == "passed"
        assert result.ai_dimension_scores[0]["name"] == "Python 工程能力"
        assert result.ai_hard_requirement_results[0]["status"] == "passed"
        assert result.ai_strengths == ["Python"]
        assert result.ai_interview_questions == ["请介绍 Python 项目"]
        assert result.ai_evidence
        assert result.ai_model_snapshot == "test-ai"
        assert result.prompt_version_snapshot == RESUME_MATCH_PROMPT_VERSION
        assert [event.event_type for event in run.events] == [
            "rescoring_started",
            "completed",
        ]


def test_rescoring_partial_failure_can_retry_only_failed_item(
    rescoring_dependencies: RescoringDependencies,
) -> None:
    dependency = rescoring_dependencies
    second_result_id = _add_second_retrieved_result(dependency)
    first_client = StubAIClient(
        [_analysis(dependency), AIUpstreamError("AI 服务暂时不可用")]
    )
    first = asyncio.run(
        rescore_talent_recommendations(
            dependency.run_id,
            task_id="rescoring-task-1",
            session_factory=dependency.session_factory,
            ai_client=first_client,
        )
    )
    assert first["status"] == "partial"
    assert len(first_client.calls) == 2

    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        first_result = db.get(TalentRecommendationResult, dependency.result_ids[0])
        second_result = db.get(TalentRecommendationResult, second_result_id)
        assert run is not None and first_result is not None and second_result is not None
        assert run.completed_count == 1
        assert run.failed_count == 1
        assert first_result.status == "completed"
        assert second_result.status == "failed"
        run.celery_task_id = "rescoring-retry-1"
        db.commit()

    retry_client = StubAIClient([_analysis(dependency, score=91)])
    retried = asyncio.run(
        rescore_talent_recommendations(
            dependency.run_id,
            task_id="rescoring-retry-1",
            retry_failed_only=True,
            session_factory=dependency.session_factory,
            ai_client=retry_client,
        )
    )
    assert retried["status"] == "completed"
    assert len(retry_client.calls) == 1
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        first_result = db.get(TalentRecommendationResult, dependency.result_ids[0])
        second_result = db.get(TalentRecommendationResult, second_result_id)
        assert run is not None and first_result is not None and second_result is not None
        assert run.completed_count == 2
        assert run.failed_count == 0
        assert first_result.processing_attempt_count == 1
        assert second_result.status == "completed"
        assert second_result.processing_attempt_count == 2
        assert float(second_result.ai_score or 0) == 91


def test_rescoring_invalid_evidence_fails_after_single_repair_attempt(
    rescoring_dependencies: RescoringDependencies,
) -> None:
    dependency = rescoring_dependencies
    invalid = _analysis(dependency, quote="简历中不存在的证据")
    client = StubAIClient([invalid, invalid.model_copy(deep=True)])

    response = asyncio.run(
        rescore_talent_recommendations(
            dependency.run_id,
            task_id="rescoring-task-1",
            session_factory=dependency.session_factory,
            ai_client=client,
        )
    )

    assert response["status"] == "failed"
    assert len(client.calls) == 2
    assert client.calls[1]["validation_feedback"]
    with dependency.session_factory() as db:
        result = db.get(TalentRecommendationResult, dependency.result_ids[0])
        assert result is not None
        assert result.failure_code == "ai_invalid_response"
        assert "13800138000" not in (result.failure_message or "")


def test_rescoring_configuration_change_is_persisted_as_failure(
    rescoring_dependencies: RescoringDependencies,
) -> None:
    dependency = rescoring_dependencies
    client = StubAIClient([], model="different-ai")

    response = asyncio.run(
        rescore_talent_recommendations(
            dependency.run_id,
            task_id="rescoring-task-1",
            session_factory=dependency.session_factory,
            ai_client=client,
        )
    )

    assert response["status"] == "failed"
    assert client.calls == []
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        result = db.get(TalentRecommendationResult, dependency.result_ids[0])
        assert run is not None and result is not None
        assert run.status == "failed"
        assert run.rescored_count == 1
        assert run.completed_count == 0
        assert run.failed_count == 1
        assert result.status == "failed"
        assert result.failure_code == "ai_configuration_changed"
        assert [event.event_type for event in run.events] == ["failed"]


def test_rescoring_cancellation_restores_unfinished_result(
    rescoring_dependencies: RescoringDependencies,
) -> None:
    dependency = rescoring_dependencies
    client = CancellingAIClient(dependency, _analysis(dependency))

    response = asyncio.run(
        rescore_talent_recommendations(
            dependency.run_id,
            task_id="rescoring-task-1",
            session_factory=dependency.session_factory,
            ai_client=client,
        )
    )

    assert response == {"status": "cancelled", "run_id": str(dependency.run_id)}
    assert len(client.calls) == 1
    with dependency.session_factory() as db:
        run = db.get(TalentRecommendationRun, dependency.run_id)
        result = db.get(TalentRecommendationResult, dependency.result_ids[0])
        assert run is not None and result is not None
        assert run.status == "cancelled"
        assert result.status == "retrieved"
        assert result.ai_score is None
        assert result.completed_at is None


def test_rescoring_rejects_superseded_task_without_ai_call(
    rescoring_dependencies: RescoringDependencies,
) -> None:
    dependency = rescoring_dependencies
    client = StubAIClient([])

    response = asyncio.run(
        rescore_talent_recommendations(
            dependency.run_id,
            task_id="old-task",
            session_factory=dependency.session_factory,
            ai_client=client,
        )
    )

    assert response == {"status": "superseded", "run_id": str(dependency.run_id)}
    assert client.calls == []
    with dependency.session_factory() as db:
        result = db.scalar(select(TalentRecommendationResult))
        assert result is not None and result.status == "retrieved"
