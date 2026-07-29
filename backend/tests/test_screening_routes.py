import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    ApplicationResumeDocument,
    AuditLog,
    Candidate,
    CandidateProfile,
    DimensionScore,
    EvidenceCitation,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ResumeTextSegment,
    Role,
    ScoringDimension,
    ScreeningBatch,
    ScreeningResult,
    User,
    UserRole,
)
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore


@dataclass(frozen=True)
class ScreeningRouteDependencies:
    job_id: uuid.UUID
    batch_id: uuid.UUID
    application_id: uuid.UUID
    document_id: uuid.UUID
    result_id: uuid.UUID
    citation_id: uuid.UUID
    session_factory: sessionmaker[Session]
    enqueued_document_ids: list[uuid.UUID]


def link_document_to_application(
    db: Session,
    *,
    job_id: uuid.UUID,
    document: ResumeDocument,
) -> JobApplication:
    candidate = Candidate()
    application = JobApplication(candidate=candidate, job_id=job_id)
    document.candidate = candidate
    document.application = application
    db.add(document)
    db.flush()
    db.add(
        ApplicationResumeDocument(
            application_id=application.id,
            document_id=document.id,
        )
    )
    application.primary_document_id = document.id
    db.flush()
    return application


@pytest.fixture
def screening_route_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[ScreeningRouteDependencies, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        roles = {
            "recruiter": Role(key="recruiter", display_name="招聘专员"),
            "hiring_manager": Role(key="hiring_manager", display_name="用人经理"),
        }
        user = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
            role_assignments=[UserRole(role=roles["recruiter"])],
        )
        manager = User(
            username="manager",
            password_hash=hash_password("manager-password"),
            display_name="用人经理",
            role_assignments=[UserRole(role=roles["hiring_manager"])],
        )
        db.add_all([*roles.values(), user, manager])
        db.flush()
        job = Job(
            owner_id=user.id,
            hiring_manager_id=manager.id,
            title="工程师",
            department="研发",
            original_jd="JD",
        )
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_by_id=user.id,
        )
        dimension = ScoringDimension(
            name="工程能力",
            description="工程实践",
            weight_percent=100,
            sort_order=0,
        )
        criteria.scoring_dimensions = [dimension]
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="结果测试",
            status="completed",
            ai_input_mode="redacted",
        )
        db.add(batch)
        db.flush()
        document = ResumeDocument(
            batch_id=batch.id,
            original_filename="resume.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
            segment_count=1,
        )
        segment = ResumeTextSegment(
            segment_key="SEG-0001",
            source_type="pdf_page",
            source_index=1,
            page_number=1,
            raw_text="Python 工程经验",
            normalized_text="Python 工程经验",
            redacted_text="Python 工程经验",
            sort_order=0,
        )
        document.text_segments = [segment]
        application = link_document_to_application(
            db,
            job_id=job.id,
            document=document,
        )
        profile = CandidateProfile(
            document_id=document.id,
            version_number=1,
            source="ai",
            model_name="stub-model",
            prompt_version="resume-match-v1",
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
        result = ScreeningResult(
            application_id=application.id,
            document_id=document.id,
            candidate_profile=profile,
            criteria_version_id=criteria.id,
            analysis_version=1,
            status="completed",
            ai_group="passed",
            total_score=Decimal("88.00"),
            pass_threshold=60,
            hard_requirement_results=[],
            strengths=["Python"],
            gaps=[],
            missing_items=[],
            interview_questions=["请介绍工程实践。"],
            model_name="stub-model",
            prompt_version="resume-match-v1",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        score = DimensionScore(
            scoring_dimension_id=dimension.id,
            dimension_name=dimension.name,
            score=88,
            weight_percent=100,
            weighted_score=Decimal("88.00"),
            rationale="具有工程经验。",
            missing_items=[],
            sort_order=0,
        )
        result.dimension_scores = [score]
        result.evidence_citations = [
            EvidenceCitation(
                dimension_score=score,
                segment=segment,
                subject_type="dimension",
                subject_key=str(dimension.id),
                segment_key="SEG-0001",
                quote="Python 工程经验",
                source_type="pdf_page",
                page_number=1,
                sort_order=0,
            )
        ]
        db.add(result)
        db.commit()

    session_store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    def override_session_store() -> SessionStore:
        return session_store

    enqueued_document_ids: list[uuid.UUID] = []

    def enqueue(document_id: uuid.UUID, **_: object) -> str:
        enqueued_document_ids.append(document_id)
        return "analysis-task-1"

    monkeypatch.setattr("app.api.routes.batches.enqueue_resume_analysis", enqueue)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_session_store
    yield ScreeningRouteDependencies(
        job_id=job.id,
        batch_id=batch.id,
        application_id=application.id,
        document_id=document.id,
        result_id=result.id,
        citation_id=result.evidence_citations[0].id,
        session_factory=testing_session,
        enqueued_document_ids=enqueued_document_ids,
    )
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(
    client: httpx.AsyncClient,
    username: str = "recruiter",
    password: str = "correct-password",
) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_hiring_manager_reads_screening_but_not_sensitive_evidence_or_decisions(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    result_path = f"/jobs/{dependency.job_id}/screening-results/{dependency.result_id}"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, "manager", "manager-password")
        listed = await client.get(f"/jobs/{dependency.job_id}/screening-results")
        detail = await client.get(result_path)
        evidence = await client.get(f"{result_path}/evidence/{dependency.citation_id}")
        decision = await client.post(
            f"{result_path}/decisions",
            json={"decision": "shortlisted", "reason": "越权操作"},
        )

    assert listed.status_code == 200
    assert detail.status_code == 200
    assert evidence.status_code == 403
    assert decision.status_code == 403


@pytest.mark.asyncio
async def test_analysis_detail_requires_authentication_and_returns_evidence(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    path = (
        f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}"
        f"/documents/{dependency.document_id}/analysis"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get(path)
        await login(client)
        response = await client.get(path)

    assert anonymous.status_code == 401
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["ai_group"] == "passed"
    assert body["total_score"] == 88.0
    assert body["candidate_profile"]["skills"][0]["name"] == "Python"
    assert body["dimension_scores"][0]["evidence"][0]["segment_key"] == "SEG-0001"
    assert body["evidence"][0]["page_number"] == 1


@pytest.mark.asyncio
async def test_analysis_retry_queues_completed_document_and_blocks_processing_result(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    path = (
        f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}"
        f"/documents/{dependency.document_id}/analysis-retry"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        queued = await client.post(path)
        with dependency.session_factory() as db:
            batch = db.get(ScreeningBatch, dependency.batch_id)
            assert batch is not None
            db.add(
                ScreeningResult(
                    application_id=dependency.application_id,
                    document_id=dependency.document_id,
                    criteria_version_id=batch.criteria_version_id,
                    analysis_version=2,
                    status="processing",
                    pass_threshold=60,
                    hard_requirement_results=[],
                    strengths=[],
                    gaps=[],
                    missing_items=[],
                    interview_questions=[],
                    model_name="stub-model",
                    prompt_version="resume-match-v1",
                    started_at=datetime.now(UTC),
                )
            )
            db.commit()
        blocked = await client.post(path)

    assert queued.status_code == 202
    assert queued.json() == {"status": "queued", "task_id": "analysis-task-1"}
    assert dependency.enqueued_document_ids == [dependency.document_id]
    assert blocked.status_code == 409
    assert "正在进行" in blocked.text


@pytest.mark.asyncio
async def test_screening_result_list_filters_and_sorts_by_ai_group(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    with dependency.session_factory() as db:
        batch = db.get(ScreeningBatch, dependency.batch_id)
        assert batch is not None
        for index, (ai_group, score) in enumerate(
            (("low_match", "95.00"), ("auto_rejected", "99.00")),
            start=2,
        ):
            document = ResumeDocument(
                batch_id=batch.id,
                original_filename=f"resume-{index}.pdf",
                file_extension=".pdf",
                content_type="application/pdf",
                detected_type="pdf",
                size_bytes=100,
                status="completed",
                parsed_at=datetime.now(UTC),
                redacted_at=datetime.now(UTC),
            )
            application = link_document_to_application(
                db,
                job_id=dependency.job_id,
                document=document,
            )
            db.add(
                ScreeningResult(
                    application_id=application.id,
                    document_id=document.id,
                    criteria_version_id=batch.criteria_version_id,
                    analysis_version=1,
                    status="completed",
                    ai_group=ai_group,
                    total_score=Decimal(score),
                    pass_threshold=60,
                    hard_requirement_results=[],
                    strengths=[],
                    gaps=[],
                    missing_items=[],
                    interview_questions=[],
                    model_name="stub-model",
                    prompt_version="resume-match-v1",
                    started_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
            )
        db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get(f"/jobs/{dependency.job_id}/screening-results")
        await login(client)
        response = await client.get(f"/jobs/{dependency.job_id}/screening-results")
        filtered = await client.get(
            f"/jobs/{dependency.job_id}/screening-results",
            params={"ai_group": "low_match", "min_score": 90, "max_score": 100},
        )
        empty = await client.get(
            f"/jobs/{dependency.job_id}/screening-results",
            params={"decision": "shortlisted"},
        )
        invalid = await client.get(
            f"/jobs/{dependency.job_id}/screening-results",
            params={"min_score": 90, "max_score": 80},
        )

    assert anonymous.status_code == 401
    assert response.status_code == 200
    assert [item["ai_group"] for item in response.json()] == [
        "passed",
        "low_match",
        "auto_rejected",
    ]
    assert filtered.status_code == 200
    assert [item["total_score"] for item in filtered.json()] == [95.0]
    assert empty.json() == []
    assert invalid.status_code == 422
    assert "最低分" in invalid.text


@pytest.mark.asyncio
async def test_result_detail_exposes_original_evidence_and_decision_history(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    result_path = f"/jobs/{dependency.job_id}/screening-results/{dependency.result_id}"
    evidence_path = f"{result_path}/evidence/{dependency.citation_id}"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        detail = await client.get(result_path)
        evidence = await client.get(evidence_path)
        foreign = await client.get(
            f"/jobs/{uuid.uuid4()}/screening-results/{dependency.result_id}"
        )

    assert detail.status_code == 200
    assert detail.json()["current_decision"] == "unprocessed"
    assert detail.json()["decision_history"] == []
    assert evidence.status_code == 200
    assert evidence.json()["segment_key"] == "SEG-0001"
    assert evidence.json()["original_text"] == "Python 工程经验"
    assert evidence.json()["page_number"] == 1
    assert foreign.status_code == 404
    with dependency.session_factory() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "resume.original_evidence_viewed"
            )
        )
    assert audit is not None
    assert audit.actor_username == "recruiter"
    assert audit.target_id == dependency.citation_id
    assert audit.job_id == dependency.job_id
    assert audit.batch_id == dependency.batch_id
    assert audit.details == {"screening_result_id": str(dependency.result_id)}


@pytest.mark.asyncio
async def test_recruiter_decisions_keep_before_after_operator_and_time(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    path = f"/jobs/{dependency.job_id}/screening-results/{dependency.result_id}/decisions"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        shortlisted = await client.post(
            path,
            json={"decision": "shortlisted", "reason": "技术能力符合当前岗位"},
        )
        unchanged = await client.post(path, json={"decision": "shortlisted"})
        pending = await client.post(
            path,
            json={"decision": "pending", "reason": "等待业务负责人复核"},
        )
        rejected = await client.post(
            path,
            json={"decision": "rejected", "reason": "人工复核后确认不匹配"},
        )
        detail = await client.get(
            f"/jobs/{dependency.job_id}/screening-results/{dependency.result_id}"
        )
        filtered = await client.get(
            f"/jobs/{dependency.job_id}/screening-results",
            params={"decision": "rejected"},
        )

    assert shortlisted.status_code == 201
    assert shortlisted.json()["previous_decision"] == "unprocessed"
    assert shortlisted.json()["operator_display_name"] == "招聘专员"
    assert shortlisted.json()["created_at"]
    assert unchanged.status_code == 409
    assert pending.status_code == 201
    assert pending.json()["previous_decision"] == "shortlisted"
    assert rejected.status_code == 201
    assert rejected.json()["previous_decision"] == "pending"
    assert detail.json()["current_decision"] == "rejected"
    assert [item["decision"] for item in detail.json()["decision_history"]] == [
        "shortlisted",
        "pending",
        "rejected",
    ]
    assert len(filtered.json()) == 1
    with dependency.session_factory() as db:
        audits = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.action == "screening.decision_changed")
                .order_by(AuditLog.created_at)
            )
        )
    assert [item.details["decision"] for item in audits] == [
        "shortlisted",
        "pending",
        "rejected",
    ]
    assert [item.details["previous_decision"] for item in audits] == [
        "unprocessed",
        "shortlisted",
        "pending",
    ]
    assert all(item.actor_username == "recruiter" for item in audits)


@pytest.mark.asyncio
async def test_auto_rejection_recovery_requires_reason(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    with dependency.session_factory() as db:
        result = db.get(ScreeningResult, dependency.result_id)
        assert result is not None
        result.ai_group = "auto_rejected"
        db.commit()

    path = f"/jobs/{dependency.job_id}/screening-results/{dependency.result_id}/decisions"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        missing_reason = await client.post(path, json={"decision": "pending"})
        recovered = await client.post(
            path,
            json={"decision": "pending", "reason": "证书信息需要面试时再次确认"},
        )

    assert missing_reason.status_code == 422
    assert "必须填写原因" in missing_reason.text
    assert recovered.status_code == 201
    assert recovered.json()["is_auto_rejection_override"] is True
    with dependency.session_factory() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "screening.auto_rejection_overridden"
            )
        )
    assert audit is not None
    assert audit.actor_username == "recruiter"
    assert audit.target_id == dependency.result_id
    assert audit.details == {"decision": "pending"}


@pytest.mark.asyncio
async def test_candidate_comparison_enforces_count_job_and_analysis_version(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    with dependency.session_factory() as db:
        batch = db.get(ScreeningBatch, dependency.batch_id)
        assert batch is not None
        dimension = db.scalar(
            select(ScoringDimension).where(
                ScoringDimension.criteria_version_id == batch.criteria_version_id
            )
        )
        assert dimension is not None

        second_document = ResumeDocument(
            batch_id=batch.id,
            original_filename="resume-second.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
        )
        second_application = link_document_to_application(
            db,
            job_id=dependency.job_id,
            document=second_document,
        )
        second_result = ScreeningResult(
            application_id=second_application.id,
            document_id=second_document.id,
            criteria_version_id=batch.criteria_version_id,
            analysis_version=1,
            status="completed",
            ai_group="low_match",
            total_score=Decimal("55.00"),
            pass_threshold=60,
            hard_requirement_results=[],
            strengths=["学习能力"],
            gaps=["经验较少"],
            missing_items=["证书信息"],
            interview_questions=[],
            model_name="stub-model",
            prompt_version="resume-match-v1",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        second_result.dimension_scores = [
            DimensionScore(
                scoring_dimension_id=dimension.id,
                dimension_name=dimension.name,
                score=55,
                weight_percent=100,
                weighted_score=Decimal("55.00"),
                rationale="基础能力符合，但经验不足。",
                missing_items=[],
                sort_order=0,
            )
        ]
        db.add(second_result)

        version_mismatch_document = ResumeDocument(
            batch_id=batch.id,
            original_filename="resume-version-two.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
        )
        version_mismatch_application = link_document_to_application(
            db,
            job_id=dependency.job_id,
            document=version_mismatch_document,
        )
        version_mismatch_result = ScreeningResult(
            application_id=version_mismatch_application.id,
            document_id=version_mismatch_document.id,
            criteria_version_id=batch.criteria_version_id,
            analysis_version=2,
            status="completed",
            ai_group="passed",
            total_score=Decimal("90.00"),
            pass_threshold=60,
            hard_requirement_results=[],
            strengths=[],
            gaps=[],
            missing_items=[],
            interview_questions=[],
            model_name="stub-model",
            prompt_version="resume-match-v1",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(version_mismatch_result)

        owner = db.scalar(select(User).where(User.username == "recruiter"))
        assert owner is not None
        foreign_job = Job(
            owner_id=owner.id,
            title="另一个职位",
            department="研发",
            original_jd="JD",
        )
        db.add(foreign_job)
        db.flush()
        foreign_criteria = JobCriteriaVersion(
            job_id=foreign_job.id,
            version_number=1,
            status="confirmed",
            pass_threshold=60,
            confirmed_by_id=owner.id,
        )
        db.add(foreign_criteria)
        db.flush()
        foreign_batch = ScreeningBatch(
            job_id=foreign_job.id,
            criteria_version_id=foreign_criteria.id,
            name="跨职位",
            status="completed",
        )
        db.add(foreign_batch)
        db.flush()
        foreign_document = ResumeDocument(
            batch_id=foreign_batch.id,
            original_filename="foreign.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
        )
        foreign_application = link_document_to_application(
            db,
            job_id=foreign_job.id,
            document=foreign_document,
        )
        foreign_result = ScreeningResult(
            application_id=foreign_application.id,
            document_id=foreign_document.id,
            criteria_version_id=foreign_criteria.id,
            analysis_version=1,
            status="completed",
            ai_group="passed",
            total_score=Decimal("80.00"),
            pass_threshold=60,
            hard_requirement_results=[],
            strengths=[],
            gaps=[],
            missing_items=[],
            interview_questions=[],
            model_name="stub-model",
            prompt_version="resume-match-v1",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(foreign_result)
        db.commit()

        second_result_id = second_result.id
        second_candidate_code = second_document.candidate_code
        mismatch_result_id = version_mismatch_result.id
        foreign_result_id = foreign_result.id

    path = f"/jobs/{dependency.job_id}/screening-results/compare"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        valid = await client.post(
            path,
            json={"result_ids": [str(second_result_id), str(dependency.result_id)]},
        )
        too_few = await client.post(path, json={"result_ids": [str(dependency.result_id)]})
        too_many = await client.post(
            path,
            json={
                "result_ids": [
                    str(dependency.result_id),
                    str(second_result_id),
                    str(mismatch_result_id),
                    str(foreign_result_id),
                ]
            },
        )
        duplicate = await client.post(
            path,
            json={"result_ids": [str(dependency.result_id), str(dependency.result_id)]},
        )
        mismatch = await client.post(
            path,
            json={"result_ids": [str(dependency.result_id), str(mismatch_result_id)]},
        )
        cross_job = await client.post(
            path,
            json={"result_ids": [str(dependency.result_id), str(foreign_result_id)]},
        )

    assert valid.status_code == 200
    body = valid.json()
    assert body["criteria_version_number"] == 1
    assert body["analysis_version"] == 1
    assert body["candidates"][0]["candidate_code"] == second_candidate_code
    assert body["candidates"][1]["document_id"] == str(dependency.document_id)
    assert [item["total_score"] for item in body["candidates"]] == [55.0, 88.0]
    assert body["candidates"][0]["dimension_scores"][0]["dimension_name"] == "工程能力"
    assert too_few.status_code == 422
    assert too_many.status_code == 422
    assert duplicate.status_code == 422
    assert mismatch.status_code == 422
    assert "同一职位标准和同一分析版本" in mismatch.text
    assert cross_job.status_code == 404


@pytest.mark.asyncio
async def test_profile_correction_creates_version_and_queues_only_target_candidate(
    screening_route_dependencies: ScreeningRouteDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = screening_route_dependencies
    enqueued: list[tuple[uuid.UUID, dict[str, object]]] = []

    def enqueue(document_id: uuid.UUID, **kwargs: object) -> str:
        enqueued.append((document_id, kwargs))
        return "correction-task-1"

    monkeypatch.setattr(
        "app.api.routes.candidate_versions.enqueue_resume_analysis",
        enqueue,
    )
    with dependency.session_factory() as db:
        result = db.get(ScreeningResult, dependency.result_id)
        assert result is not None
        source = result.candidate_profile
        assert source is not None
        source_id = source.id
        criteria_id = result.criteria_version_id
        payload = {
            "source_profile_id": str(source.id),
            "criteria_version_id": str(criteria_id),
            "education": source.education,
            "work_experiences": source.work_experiences,
            "projects": source.projects,
            "skills": [
                {
                    "name": "Python 3",
                    "level": "精通",
                    "evidence": [
                        {"segment_key": "SEG-0001", "quote": "Python"}
                    ],
                }
            ],
            "certifications": source.certifications,
            "languages": source.languages,
        }

    base = (
        f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}"
        f"/documents/{dependency.document_id}"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        corrected = await client.post(f"{base}/profile-corrections", json=payload)
        profiles = await client.get(f"{base}/profiles")
        history = await client.get(f"{base}/analysis-history")

    assert corrected.status_code == 201
    body = corrected.json()
    assert body["profile"]["version_number"] == 2
    assert body["profile"]["source"] == "manual"
    assert body["profile"]["source_profile_id"] == str(source_id)
    assert body["profile"]["skills"][0]["name"] == "Python 3"
    assert body["reanalysis"]["status"] == "queued"
    assert body["reanalysis"]["analysis_version"] == 2
    assert enqueued == [
        (
                dependency.document_id,
                {
                    "application_id": dependency.application_id,
                    "criteria_version_id": criteria_id,
                "candidate_profile_id": uuid.UUID(body["profile"]["id"]),
                "analysis_version": 2,
            },
        )
    ]
    assert profiles.status_code == 200
    assert [item["version_number"] for item in profiles.json()] == [2, 1]
    assert history.status_code == 200
    assert [item["analysis_version"] for item in history.json()] == [1]
    with dependency.session_factory() as db:
        audits = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action.in_(
                        [
                            "candidate.profile_corrected",
                            "screening.reanalysis_requested",
                        ]
                    )
                )
            )
        )
    assert {item.action for item in audits} == {
        "candidate.profile_corrected",
        "screening.reanalysis_requested",
    }
    rerun_audit = next(
        item for item in audits if item.action == "screening.reanalysis_requested"
    )
    assert rerun_audit.details["scope"] == "candidate_after_correction"
    assert rerun_audit.details["analysis_version"] == 2


@pytest.mark.asyncio
async def test_profile_correction_rejects_sensitive_data(
    screening_route_dependencies: ScreeningRouteDependencies,
) -> None:
    dependency = screening_route_dependencies
    with dependency.session_factory() as db:
        result = db.get(ScreeningResult, dependency.result_id)
        assert result is not None and result.candidate_profile is not None
        source = result.candidate_profile
        payload = {
            "source_profile_id": str(source.id),
            "criteria_version_id": str(result.criteria_version_id),
            "education": source.education,
            "work_experiences": source.work_experiences,
            "projects": source.projects,
            "skills": [{"name": "联系电话 13912345678", "level": "", "evidence": []}],
            "certifications": source.certifications,
            "languages": source.languages,
        }

    path = (
        f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}"
        f"/documents/{dependency.document_id}/profile-corrections"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.post(path, json=payload)

    assert response.status_code == 422
    assert "敏感信息" in response.text
    with dependency.session_factory() as db:
        assert (
            db.scalar(
                select(func.count(CandidateProfile.id)).where(
                    CandidateProfile.document_id == dependency.document_id
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_batch_reanalysis_uses_shared_version_and_latest_profiles(
    screening_route_dependencies: ScreeningRouteDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = screening_route_dependencies
    with dependency.session_factory() as db:
        batch = db.get(ScreeningBatch, dependency.batch_id)
        first_result = db.get(ScreeningResult, dependency.result_id)
        assert batch is not None and first_result is not None
        second_document = ResumeDocument(
            batch_id=batch.id,
            original_filename="batch-rerun.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=100,
            status="completed",
            parsed_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC),
        )
        second_application = link_document_to_application(
            db,
            job_id=dependency.job_id,
            document=second_document,
        )
        second_profile = CandidateProfile(
            document=second_document,
            version_number=1,
            source="ai",
            model_name="stub-model",
            prompt_version="resume-match-v1",
            education=[],
            work_experiences=[],
            projects=[],
            skills=[],
            certifications=[],
            languages=[],
        )
        second_result = ScreeningResult(
            application_id=second_application.id,
            document=second_document,
            candidate_profile=second_profile,
            criteria_version_id=batch.criteria_version_id,
            analysis_version=1,
            status="completed",
            ai_group="passed",
            total_score=Decimal("70.00"),
            pass_threshold=60,
            hard_requirement_results=[],
            strengths=[],
            gaps=[],
            missing_items=[],
            interview_questions=[],
            model_name="stub-model",
            prompt_version="resume-match-v1",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(second_result)
        db.commit()
        criteria_id = batch.criteria_version_id
        first_profile_id = first_result.candidate_profile_id
        second_document_id = second_document.id
        second_profile_id = second_profile.id

    enqueued: list[tuple[uuid.UUID, dict[str, object]]] = []

    def enqueue(document_id: uuid.UUID, **kwargs: object) -> str:
        enqueued.append((document_id, kwargs))
        return f"task-{len(enqueued)}"

    monkeypatch.setattr(
        "app.api.routes.candidate_versions.enqueue_resume_analysis",
        enqueue,
    )
    path = f"/jobs/{dependency.job_id}/batches/{dependency.batch_id}/reanalysis"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.post(path, json={"criteria_version_id": str(criteria_id)})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["analysis_version"] == 2
    assert body["queued_count"] == 2
    assert body["failed_count"] == 0
    assert body["skipped_count"] == 0
    assert {item[0] for item in enqueued} == {
        dependency.document_id,
        second_document_id,
    }
    assert {item[1]["analysis_version"] for item in enqueued} == {2}
    assert {item[1]["candidate_profile_id"] for item in enqueued} == {
        first_profile_id,
        second_profile_id,
    }
    with dependency.session_factory() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "screening.reanalysis_requested",
                AuditLog.target_type == "screening_batch",
            )
        )
    assert audit is not None
    assert audit.target_id == dependency.batch_id
    assert audit.result == "success"
    assert audit.details == {
        "scope": "batch",
        "criteria_version_id": str(criteria_id),
        "analysis_version": 2,
        "queued_count": 2,
        "failed_count": 0,
        "skipped_count": 0,
    }
