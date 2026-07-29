import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    ApplicationResumeDocument,
    AuditLog,
    Candidate,
    CandidateDuplicateReview,
    CandidateProfile,
    HardRequirement,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeTextSegment,
    ScoringDimension,
    ScreeningBatch,
    ScreeningResult,
    User,
)
from app.schemas.screening import ResumeAnalysisDraft
from app.services.ai_client import AIConfigurationError
from app.services.candidate_duplicates import build_experience_fingerprint
from app.services.resume_analysis import (
    _find_source_quote,
    analyze_resume_document,
    screening_result_sort_key,
)
from app.services.security import hash_password


@dataclass(frozen=True)
class AnalysisDependencies:
    session_factory: sessionmaker[Session]
    document_id: uuid.UUID
    criteria_version_id: uuid.UUID
    requirement_ids: dict[str, uuid.UUID]
    dimension_ids: dict[str, uuid.UUID]


class StubAnalysisClient:
    def __init__(
        self,
        analysis: ResumeAnalysisDraft | None = None,
        error: Exception | None = None,
        repair_analysis: ResumeAnalysisDraft | None = None,
    ) -> None:
        self.model = "stub-resume-model"
        self.analysis = analysis
        self.error = error
        self.repair_analysis = repair_analysis
        self.payloads: list[dict[str, object]] = []
        self.validation_feedback: list[str | None] = []

    async def analyze_resume(
        self,
        payload: dict[str, object],
        *,
        validation_feedback: str | None = None,
        previous_analysis: dict[str, object] | None = None,
    ) -> ResumeAnalysisDraft:
        self.payloads.append(payload)
        self.validation_feedback.append(validation_feedback)
        if validation_feedback is not None:
            assert previous_analysis is not None
        if self.error is not None:
            raise self.error
        if validation_feedback is not None and self.repair_analysis is not None:
            return self.repair_analysis
        assert self.analysis is not None
        return self.analysis


@pytest.fixture
def analysis_dependencies() -> Generator[AnalysisDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        user = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
        )
        db.add(user)
        db.flush()
        job = Job(
            owner_id=user.id,
            title="后端工程师",
            department="研发中心",
            original_jd="负责 Python 服务开发。",
        )
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            pass_threshold=70,
            confirmed_by_id=user.id,
            confirmed_at=datetime.now(UTC),
        )
        criteria.hard_requirements = [
            HardRequirement(
                requirement_type="min_experience_years",
                title="至少三年经验",
                expected_value="3 年",
                auto_reject=True,
                sort_order=0,
            ),
            HardRequirement(
                requirement_type="min_education",
                title="本科及以上",
                expected_value="本科",
                auto_reject=True,
                sort_order=1,
            ),
            HardRequirement(
                requirement_type="required_certification",
                title="云平台认证",
                expected_value="AWS SAA",
                auto_reject=True,
                sort_order=2,
            ),
            HardRequirement(
                requirement_type="language_level",
                title="英语等级",
                expected_value="CET-6",
                auto_reject=True,
                sort_order=3,
            ),
            HardRequirement(
                requirement_type="other",
                title="互联网行业经历",
                expected_value="2 年",
                auto_reject=False,
                sort_order=4,
            ),
        ]
        criteria.scoring_dimensions = [
            ScoringDimension(
                name="系统设计",
                description="可扩展系统设计能力",
                weight_percent=60,
                sort_order=0,
            ),
            ScoringDimension(
                name="工程质量",
                description="测试和稳定性意识",
                weight_percent=40,
                sort_order=1,
            ),
        ]
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="AI 分析测试",
            status="completed",
        )
        db.add(batch)
        db.flush()
        candidate = Candidate(full_name="李雷", full_name_normalized="李雷")
        application = JobApplication(candidate=candidate, job_id=job.id)
        document = ResumeDocument(
            batch_id=batch.id,
            candidate=candidate,
            application=application,
            original_filename="private.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            sha256="a" * 64,
            storage_key="private/storage.pdf",
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
            segment_count=2,
            text_character_count=100,
        )
        document.text_segments = [
            ResumeTextSegment(
                segment_key="SEG-0001",
                source_type="pdf_page",
                source_index=1,
                page_number=1,
                raw_text="姓名：李雷，5 年 Python 经验，AWS SAA。",
                normalized_text="姓名：李雷，5 年 Python 经验，AWS SAA。",
                redacted_text="CAND-TEST，5 年 Python 经验，AWS SAA。",
                sort_order=0,
            ),
            ResumeTextSegment(
                segment_key="SEG-0002",
                source_type="pdf_page",
                source_index=2,
                page_number=2,
                raw_text="负责微服务架构和自动化测试。",
                normalized_text="负责微服务架构和自动化测试。",
                redacted_text="负责微服务架构和自动化测试。",
                sort_order=1,
            ),
        ]
        db.add(document)
        db.flush()
        db.add(
            ApplicationResumeDocument(
                application_id=application.id,
                document_id=document.id,
            )
        )
        application.primary_document_id = document.id
        db.commit()
        requirement_ids = {
            item.requirement_type: item.id for item in criteria.hard_requirements
        }
        dimension_ids = {item.name: item.id for item in criteria.scoring_dimensions}
        dependencies = AnalysisDependencies(
            session_factory=testing_session,
            document_id=document.id,
            criteria_version_id=criteria.id,
            requirement_ids=requirement_ids,
            dimension_ids=dimension_ids,
        )

    yield dependencies
    Base.metadata.drop_all(engine)
    engine.dispose()


def valid_analysis(
    dependencies: AnalysisDependencies,
    *,
    experience_status: str = "passed",
    system_score: int = 80,
    quality_score: int = 40,
) -> ResumeAnalysisDraft:
    requirement_ids = dependencies.requirement_ids
    dimension_ids = dependencies.dimension_ids
    experience_evidence = [
        {
            "segment_key": "SEG-0001",
            "quote": "5 年 Python 经验",
        }
    ]
    return ResumeAnalysisDraft.model_validate(
        {
            "candidate_profile": {
                "education": [],
                "work_experiences": [
                    {
                        "company": "示例科技",
                        "title": "后端工程师",
                        "summary": "负责微服务架构",
                        "evidence": [
                            {
                                "segment_key": "SEG-0002",
                                "quote": "负责微服务架构",
                            }
                        ],
                    }
                ],
                "projects": [
                    {
                        "name": "微服务平台",
                        "role": "核心开发",
                        "summary": "微服务架构",
                        "evidence": [
                            {
                                "segment_key": "SEG-0002",
                                "quote": "微服务架构",
                            }
                        ],
                    }
                ],
                "skills": [
                    {
                        "name": "Python",
                        "level": "熟练",
                        "evidence": experience_evidence,
                    }
                ],
                "certifications": [
                    {
                        "name": "AWS SAA",
                        "evidence": [
                            {"segment_key": "SEG-0001", "quote": "AWS SAA"}
                        ],
                    }
                ],
                "languages": [],
            },
            "hard_requirements": [
                {
                    "requirement_id": requirement_ids["min_experience_years"],
                    "status": experience_status,
                    "rationale": "简历明确写明 5 年经验。",
                    "evidence": experience_evidence,
                },
                {
                    "requirement_id": requirement_ids["min_education"],
                    "status": "unknown",
                    "rationale": "简历未提及学历。",
                    "evidence": [],
                },
                {
                    "requirement_id": requirement_ids["required_certification"],
                    "status": "passed",
                    "rationale": "明确列出 AWS SAA。",
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": "AWS SAA"}
                    ],
                },
                {
                    "requirement_id": requirement_ids["language_level"],
                    "status": "unknown",
                    "rationale": "简历未提及英语等级。",
                    "evidence": [],
                },
                {
                    "requirement_id": requirement_ids["other"],
                    "status": "failed",
                    "rationale": "仅有技术经历，没有互联网行业说明。",
                    "evidence": [
                        {
                            "segment_key": "SEG-0002",
                            "quote": "负责微服务架构和自动化测试",
                        }
                    ],
                },
            ],
            "dimension_scores": [
                {
                    "dimension_id": dimension_ids["系统设计"],
                    "score": system_score,
                    "rationale": "具有微服务架构经验。",
                    "missing_items": [],
                    "evidence": [
                        {"segment_key": "SEG-0002", "quote": "微服务架构"}
                    ],
                },
                {
                    "dimension_id": dimension_ids["工程质量"],
                    "score": quality_score,
                    "rationale": "提及自动化测试。",
                    "missing_items": ["缺少测试覆盖率数据"],
                    "evidence": [
                        {"segment_key": "SEG-0002", "quote": "自动化测试"}
                    ],
                },
            ],
            "strengths": ["Python 与微服务经验"],
            "gaps": ["学历和英语等级待确认"],
            "missing_items": ["学历", "英语等级"],
            "interview_questions": ["请说明系统扩展性设计。"],
        }
    )


@pytest.mark.asyncio
async def test_completed_analysis_generates_weak_duplicate_review(
    analysis_dependencies: AnalysisDependencies,
) -> None:
    analysis = valid_analysis(analysis_dependencies)
    experience = [
        item.model_dump(mode="json")
        for item in analysis.candidate_profile.work_experiences
    ]
    with analysis_dependencies.session_factory() as db:
        source_document = db.get(ResumeDocument, analysis_dependencies.document_id)
        assert source_document is not None
        existing = Candidate(
            full_name="李 雷",
            full_name_normalized="李雷",
            experience_fingerprint=build_experience_fingerprint(experience),
        )
        existing_application = JobApplication(
            candidate=existing,
            job_id=source_document.batch.job_id,
        )
        db.add(
            ResumeDocument(
                batch_id=source_document.batch_id,
                candidate=existing,
                application=existing_application,
                original_filename="existing.pdf",
                file_extension=".pdf",
                content_type="application/pdf",
                detected_type="pdf",
                size_bytes=100,
                sha256="b" * 64,
                status="completed",
            )
        )
        db.commit()

    response = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=StubAnalysisClient(analysis),
    )

    assert response["status"] == "completed"
    with analysis_dependencies.session_factory() as db:
        review = db.scalar(select(CandidateDuplicateReview))
        assert review is not None
        assert review.confidence == "weak"
        assert review.signals == ["name_experience_exact"]


@pytest.mark.asyncio
async def test_analysis_saves_profile_weighted_score_and_low_match_group(
    analysis_dependencies: AnalysisDependencies,
) -> None:
    client = StubAnalysisClient(valid_analysis(analysis_dependencies))

    response = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=client,
    )

    assert response["status"] == "completed"
    assert response["group"] == "low_match"
    assert response["total_score"] == 64.0
    payload = client.payloads[0]
    assert payload["candidate_code"].startswith("CAND-")
    assert "private.pdf" not in str(payload)
    assert "李雷" in str(payload)
    assert "total_score" not in str(payload)

    with analysis_dependencies.session_factory() as db:
        result = db.scalar(
            select(ScreeningResult)
            .where(ScreeningResult.document_id == analysis_dependencies.document_id)
            .options(
                selectinload(ScreeningResult.candidate_profile),
                selectinload(ScreeningResult.dimension_scores),
                selectinload(ScreeningResult.evidence_citations),
            )
        )
        assert result is not None
        assert result.status == "completed"
        assert result.ai_group == "low_match"
        assert result.total_score == Decimal("64.00")
        assert result.candidate_profile is not None
        assert result.candidate_profile.version_number == 1
        assert result.candidate_profile.model_name == "stub-resume-model"
        assert {item.dimension_name for item in result.dimension_scores} == {
            "系统设计",
            "工程质量",
        }
        assert len(result.evidence_citations) >= 8
        hard_results = result.hard_requirement_results
        education = next(
            item for item in hard_results if item["requirement_type"] == "min_education"
        )
        assert education["status"] == "unknown"
        assert result.document.status == "completed"


@pytest.mark.asyncio
async def test_explicit_objective_failure_auto_rejects_but_other_failure_does_not(
    analysis_dependencies: AnalysisDependencies,
) -> None:
    passed_client = StubAnalysisClient(valid_analysis(analysis_dependencies))
    passed = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=passed_client,
    )
    assert passed["group"] == "low_match"

    rejected_client = StubAnalysisClient(
        valid_analysis(
            analysis_dependencies,
            experience_status="failed",
            system_score=95,
            quality_score=95,
        )
    )
    rejected = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=rejected_client,
    )
    assert rejected["group"] == "auto_rejected"
    assert rejected["total_score"] == 95.0
    assert rejected["analysis_version"] == 2
    with analysis_dependencies.session_factory() as db:
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "screening.auto_rejected")
        )
    assert audit is not None
    assert audit.actor_user_id is None
    assert audit.actor_username == "system"
    assert audit.target_id is not None
    assert audit.result == "success"
    assert audit.details == {
        "analysis_version": 2,
        "criteria_version_id": str(analysis_dependencies.criteria_version_id),
    }


@pytest.mark.asyncio
async def test_evidence_format_differences_are_canonicalized_to_source_text(
    analysis_dependencies: AnalysisDependencies,
) -> None:
    formatted = valid_analysis(analysis_dependencies).model_copy(deep=True)
    formatted.candidate_profile.skills[0].evidence[0].quote = (
        "５ 年 Ｐｙｔｈｏｎ 经验。"
    )
    client = StubAnalysisClient(formatted)

    response = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=client,
    )

    assert response["status"] == "completed"
    assert len(client.payloads) == 1
    with analysis_dependencies.session_factory() as db:
        result = db.scalar(
            select(ScreeningResult)
            .where(ScreeningResult.document_id == analysis_dependencies.document_id)
            .options(selectinload(ScreeningResult.evidence_citations))
        )
        assert result is not None
        skill_evidence = next(
            item
            for item in result.evidence_citations
            if item.subject_type == "profile" and item.subject_key == "skill:0"
        )
        assert skill_evidence.quote == "5 年 Python 经验"


def test_evidence_format_matching_does_not_hide_fact_changes() -> None:
    assert _find_source_quote("具有 25 年 Python 经验", "2.5 年 Python 经验") is None
    assert _find_source_quote("熟悉 C 语言", "C#") is None


@pytest.mark.asyncio
async def test_contract_failure_is_repaired_once_before_persistence(
    analysis_dependencies: AnalysisDependencies,
) -> None:
    invalid = valid_analysis(analysis_dependencies).model_copy(deep=True)
    invalid.dimension_scores[0].evidence[0].quote = "模型改写的系统架构经验"
    repaired = valid_analysis(analysis_dependencies).model_copy(deep=True)
    client = StubAnalysisClient(invalid, repair_analysis=repaired)

    response = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=client,
    )

    assert response["status"] == "completed"
    assert len(client.payloads) == 2
    assert client.validation_feedback[0] is None
    assert "SEG-0002" in (client.validation_feedback[1] or "")


@pytest.mark.asyncio
async def test_invalid_evidence_and_configuration_failure_are_isolated(
    analysis_dependencies: AnalysisDependencies,
) -> None:
    invalid = valid_analysis(analysis_dependencies).model_copy(deep=True)
    invalid.dimension_scores[0].evidence[0].quote = "不存在的原文"
    invalid_client = StubAnalysisClient(invalid)
    invalid_response = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=invalid_client,
    )
    assert invalid_response["status"] == "failed"
    assert invalid_response["code"] == "ai_invalid_response"
    assert len(invalid_client.payloads) == 2

    config_response = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=StubAnalysisClient(error=AIConfigurationError("未配置模型")),
    )
    assert config_response["status"] == "failed"
    assert config_response["code"] == "ai_not_configured"

    with analysis_dependencies.session_factory() as db:
        document = db.get(ResumeDocument, analysis_dependencies.document_id)
        assert document is not None
        assert document.status == "completed"
        assert db.scalar(select(func.count(CandidateProfile.id))) == 0


@pytest.mark.asyncio
async def test_reanalysis_uses_manual_profile_and_preserves_previous_result(
    analysis_dependencies: AnalysisDependencies,
) -> None:
    initial = await analyze_resume_document(
        analysis_dependencies.document_id,
        session_factory=analysis_dependencies.session_factory,
        ai_client=StubAnalysisClient(valid_analysis(analysis_dependencies)),
    )
    assert initial["status"] == "completed"

    with analysis_dependencies.session_factory() as db:
        source = db.scalar(
            select(CandidateProfile).where(
                CandidateProfile.document_id == analysis_dependencies.document_id
            )
        )
        assert source is not None
        manual = CandidateProfile(
            document_id=source.document_id,
            version_number=2,
            source="manual",
            source_profile_id=source.id,
            model_name="manual-correction",
            prompt_version="profile-correction-v1",
            education=source.education,
            work_experiences=source.work_experiences,
            projects=source.projects,
            skills=[
                {
                    "name": "Python 3",
                    "level": "精通",
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": "Python"}
                    ],
                }
            ],
            certifications=source.certifications,
            languages=source.languages,
        )
        db.add(manual)
        db.commit()
        manual_id = manual.id

    rerun_client = StubAnalysisClient(
        valid_analysis(analysis_dependencies, system_score=90, quality_score=80)
    )
    rerun = await analyze_resume_document(
        analysis_dependencies.document_id,
        criteria_version_id=analysis_dependencies.criteria_version_id,
        candidate_profile_id=manual_id,
        analysis_version=2,
        session_factory=analysis_dependencies.session_factory,
        ai_client=rerun_client,
    )

    assert rerun["status"] == "completed"
    assert rerun["analysis_version"] == 2
    assert rerun["total_score"] == 86.0
    override = rerun_client.payloads[0]["candidate_profile_override"]
    assert isinstance(override, dict)
    assert override["skills"][0]["name"] == "Python 3"

    with analysis_dependencies.session_factory() as db:
        results = list(
            db.scalars(
                select(ScreeningResult)
                .where(ScreeningResult.document_id == analysis_dependencies.document_id)
                .order_by(ScreeningResult.analysis_version)
            )
        )
        assert [item.analysis_version for item in results] == [1, 2]
        assert results[0].candidate_profile_id != manual_id
        assert results[1].candidate_profile_id == manual_id
        assert db.scalar(select(func.count(CandidateProfile.id))) == 2

    failed = await analyze_resume_document(
        analysis_dependencies.document_id,
        criteria_version_id=analysis_dependencies.criteria_version_id,
        candidate_profile_id=manual_id,
        analysis_version=3,
        session_factory=analysis_dependencies.session_factory,
        ai_client=StubAnalysisClient(error=AIConfigurationError("模型暂不可用")),
    )
    assert failed["status"] == "failed"

    with analysis_dependencies.session_factory() as db:
        completed_versions = list(
            db.scalars(
                select(ScreeningResult.analysis_version).where(
                    ScreeningResult.document_id == analysis_dependencies.document_id,
                    ScreeningResult.status == "completed",
                )
            )
        )
        assert sorted(completed_versions) == [1, 2]


def test_default_result_sorting_uses_group_then_descending_score() -> None:
    results = [
        ScreeningResult(ai_group="auto_rejected", total_score=Decimal("99")),
        ScreeningResult(ai_group="passed", total_score=Decimal("70")),
        ScreeningResult(ai_group="low_match", total_score=Decimal("58")),
        ScreeningResult(ai_group="passed", total_score=Decimal("90")),
    ]

    ordered = sorted(results, key=screening_result_sort_key)

    assert [(item.ai_group, item.total_score) for item in ordered] == [
        ("passed", Decimal("90")),
        ("passed", Decimal("70")),
        ("low_match", Decimal("58")),
        ("auto_rejected", Decimal("99")),
    ]
