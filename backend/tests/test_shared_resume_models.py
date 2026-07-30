from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import ForeignKeyConstraint, create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    ApplicationResumeDocument,
    Candidate,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ScreeningResult,
    User,
)
from app.services.security import hash_password


@pytest.fixture
def shared_resume_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        yield db
    engine.dispose()


def _create_application(
    db: Session,
    *,
    candidate: Candidate,
    owner: User,
    title: str,
) -> JobApplication:
    job = Job(
        owner=owner,
        title=title,
        department="研发中心",
        original_jd=f"{title}职位说明",
    )
    application = JobApplication(candidate=candidate, job=job)
    db.add(application)
    db.flush()
    return application


def test_one_resume_asset_can_be_shared_by_two_applications(
    shared_resume_session: Session,
) -> None:
    owner = User(
        username="shared-resume-recruiter",
        password_hash=hash_password("correct-password"),
        display_name="招聘专员",
    )
    candidate = Candidate(full_name="共享简历候选人")
    shared_resume_session.add_all([owner, candidate])
    shared_resume_session.flush()
    first_application = _create_application(
        shared_resume_session,
        candidate=candidate,
        owner=owner,
        title="后端工程师",
    )
    second_application = _create_application(
        shared_resume_session,
        candidate=candidate,
        owner=owner,
        title="平台工程师",
    )
    document = ResumeDocument(
        batch_id=None,
        candidate=candidate,
        application=first_application,
        original_filename="candidate.pdf",
        file_extension=".pdf",
        content_type="application/pdf",
        detected_type="pdf",
        size_bytes=1024,
        storage_key="private/shared/candidate.pdf",
        status="completed",
    )
    shared_resume_session.add(document)
    shared_resume_session.flush()
    shared_resume_session.add_all(
        [
            ApplicationResumeDocument(
                application_id=first_application.id,
                document_id=document.id,
            ),
            ApplicationResumeDocument(
                application_id=second_application.id,
                document_id=document.id,
            ),
        ]
    )
    shared_resume_session.commit()

    first_application.primary_document_id = document.id
    second_application.primary_document_id = document.id
    shared_resume_session.commit()
    shared_resume_session.refresh(first_application)
    shared_resume_session.refresh(second_application)

    assert first_application.primary_document is document
    assert second_application.primary_document is document
    assert first_application.shared_documents == [document]
    assert second_application.shared_documents == [document]
    assert shared_resume_session.scalar(select(func.count(ResumeDocument.id))) == 1


def test_primary_resume_declares_membership_foreign_key() -> None:
    constraint = next(
        item
        for item in JobApplication.__table__.constraints
        if isinstance(item, ForeignKeyConstraint)
        and item.name == "fk_job_applications_primary_document_link"
    )

    assert [column.name for column in constraint.columns] == [
        "id",
        "primary_document_id",
    ]
    assert [element.target_fullname for element in constraint.elements] == [
        "application_resume_documents.application_id",
        "application_resume_documents.document_id",
    ]
    assert constraint.deferrable is True
    assert constraint.initially == "DEFERRED"


def test_shared_resume_keeps_screening_results_isolated_by_application(
    shared_resume_session: Session,
) -> None:
    owner = User(
        username="screening-isolation-recruiter",
        password_hash=hash_password("correct-password"),
        display_name="招聘专员",
    )
    candidate = Candidate(full_name="跨职位候选人")
    shared_resume_session.add_all([owner, candidate])
    shared_resume_session.flush()
    applications = [
        _create_application(
            shared_resume_session,
            candidate=candidate,
            owner=owner,
            title=title,
        )
        for title in ("后端工程师", "平台工程师")
    ]
    criteria = [
        JobCriteriaVersion(job=application.job, version_number=1, status="confirmed")
        for application in applications
    ]
    document = ResumeDocument(
        candidate=candidate,
        application=applications[0],
        original_filename="shared.pdf",
        status="completed",
    )
    shared_resume_session.add_all([*criteria, document])
    shared_resume_session.flush()
    for application in applications:
        shared_resume_session.add(
            ApplicationResumeDocument(
                application_id=application.id,
                document_id=document.id,
            )
        )
        application.primary_document_id = document.id
    now = datetime.now(UTC)
    shared_resume_session.add_all(
        [
            ScreeningResult(
                application_id=application.id,
                document_id=document.id,
                criteria_version_id=criteria_item.id,
                analysis_version=1,
                status="completed",
                ai_group=group,
                total_score=Decimal(score),
                pass_threshold=60,
                model_name="test-model",
                prompt_version="v1",
                started_at=now,
                completed_at=now,
            )
            for application, criteria_item, group, score in zip(
                applications,
                criteria,
                ("passed", "low_match"),
                ("88", "52"),
                strict=True,
            )
        ]
    )
    shared_resume_session.commit()

    first_results = list(
        shared_resume_session.scalars(
            select(ScreeningResult).where(
                ScreeningResult.application_id == applications[0].id
            )
        )
    )
    second_results = list(
        shared_resume_session.scalars(
            select(ScreeningResult).where(
                ScreeningResult.application_id == applications[1].id
            )
        )
    )

    assert [item.ai_group for item in first_results] == ["passed"]
    assert [item.ai_group for item in second_results] == ["low_match"]
    assert first_results[0].document_id == second_results[0].document_id
