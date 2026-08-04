import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    ApplicationResumeDocument,
    Candidate,
    CandidateProcess,
    EvidenceCitation,
    Job,
    JobApplication,
    JobCriteriaVersion,
    RecruiterDecision,
    ResumeDocument,
    Role,
    ScreeningBatch,
    ScreeningResult,
    User,
    UserRole,
)
from app.services.candidate_agent_context import build_candidate_agent_context
from app.services.security import hash_password


@pytest.fixture
def candidate_agent_context_session() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _user(username: str, role: Role) -> User:
    return User(
        username=username,
        password_hash=hash_password("correct-password"),
        display_name=username,
        role_assignments=[UserRole(role=role)],
    )


def _seed_context(db: Session) -> tuple[uuid.UUID, uuid.UUID]:
    recruiter_role = Role(key="recruiter", display_name="招聘专员")
    manager_role = Role(key="hiring_manager", display_name="用人经理")
    admin_role = Role(key="administrator", display_name="管理员")
    recruiter = _user("recruiter", recruiter_role)
    manager = _user("manager", manager_role)
    administrator = _user("administrator", admin_role)
    other_recruiter = _user("other-recruiter", recruiter_role)
    db.add_all(
        [
            recruiter_role,
            manager_role,
            admin_role,
            recruiter,
            manager,
            administrator,
            other_recruiter,
        ]
    )
    db.flush()

    job = Job(
        owner_id=recruiter.id,
        hiring_manager_id=manager.id,
        title="后端工程师",
        department="研发中心",
        original_jd="负责后端服务。",
    )
    criteria = JobCriteriaVersion(
        job=job,
        version_number=1,
        status="confirmed",
        pass_threshold=70,
    )
    batch = ScreeningBatch(
        job=job,
        criteria_version=criteria,
        name="Agent 上下文批次",
        status="completed",
    )
    candidate = Candidate(
        full_name="候选人A",
        phone="13800138000",
        email="candidate@example.com",
    )
    application = JobApplication(candidate=candidate, job=job)
    document = ResumeDocument(
        batch=batch,
        candidate=candidate,
        application=application,
        original_filename="candidate-a.pdf",
        file_extension=".pdf",
        content_type="application/pdf",
        detected_type="pdf",
        size_bytes=1024,
        status="completed",
    )
    db.add_all([job, criteria, batch, candidate, application, document])
    db.flush()
    db.add(
        ApplicationResumeDocument(
            application_id=application.id,
            document_id=document.id,
        )
    )
    application.primary_document_id = document.id
    db.add(
        CandidateProcess(
            application=application,
            current_stage="to_interview",
            updated_by_id=recruiter.id,
        )
    )
    screening = ScreeningResult(
        application_id=application.id,
        document_id=document.id,
        criteria_version_id=criteria.id,
        analysis_version=1,
        status="completed",
        ai_group="passed",
        total_score=86,
        pass_threshold=70,
        strengths=["系统设计经验充分"],
        gaps=["团队规模待确认"],
        missing_items=["团队规模"],
        model_name="test-model",
        prompt_version="v1",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db.add(screening)
    db.flush()
    db.add_all(
        [
            EvidenceCitation(
                screening_result_id=screening.id,
                subject_type="dimension",
                subject_key="system_design",
                segment_key="SEG-0001",
                quote="负责核心交易系统重构",
                source_type="pdf_page",
                sort_order=0,
            ),
            RecruiterDecision(
                screening_result_id=screening.id,
                operator_id=recruiter.id,
                sequence_number=1,
                previous_decision="unprocessed",
                decision="shortlisted",
                reason="进入面试",
            ),
        ]
    )
    db.commit()
    return job.id, application.id


def _load_user(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    assert user is not None
    return user


def test_candidate_agent_context_includes_screening_and_recruiter_contacts(
    candidate_agent_context_session: sessionmaker[Session],
) -> None:
    with candidate_agent_context_session() as db:
        job_id, application_id = _seed_context(db)
        context = build_candidate_agent_context(
            db,
            job_id=job_id,
            application_id=application_id,
            actor=_load_user(db, "recruiter"),
        )

    assert context["job"]["title"] == "后端工程师"
    assert context["application"]["current_stage"] == "to_interview"
    assert context["candidate"]["phone"] == "13800138000"
    assert context["candidate"]["email"] == "candidate@example.com"
    assert context["primary_document"]["original_filename"] == "candidate-a.pdf"
    assert context["latest_screening"]["ai_group"] == "passed"
    assert context["latest_screening"]["current_recruiter_decision"] == "shortlisted"
    assert context["latest_screening"]["evidence_citations"][0]["quote"] == "负责核心交易系统重构"


def test_candidate_agent_context_hides_contacts_for_hiring_manager(
    candidate_agent_context_session: sessionmaker[Session],
) -> None:
    with candidate_agent_context_session() as db:
        job_id, application_id = _seed_context(db)
        context = build_candidate_agent_context(
            db,
            job_id=job_id,
            application_id=application_id,
            actor=_load_user(db, "manager"),
        )

    assert context["candidate"]["contacts_visible"] is False
    assert context["candidate"]["phone"] is None
    assert context["candidate"]["email"] is None
    assert context["latest_screening"]["total_score"] == 86.0


def test_candidate_agent_context_returns_404_outside_job_scope(
    candidate_agent_context_session: sessionmaker[Session],
) -> None:
    with candidate_agent_context_session() as db:
        job_id, application_id = _seed_context(db)
        with pytest.raises(HTTPException) as error:
            build_candidate_agent_context(
                db,
                job_id=job_id,
                application_id=application_id,
                actor=_load_user(db, "other-recruiter"),
            )

    assert error.value.status_code == 404
