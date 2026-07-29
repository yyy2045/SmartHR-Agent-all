from collections.abc import Generator

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
    ResumeDocument,
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
