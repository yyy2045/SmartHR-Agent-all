import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Candidate, Job, JobApplication, User
from app.services.security import hash_password


def test_candidate_can_apply_to_multiple_jobs_but_only_once_per_job() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        owner = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
        )
        db.add(owner)
        db.flush()
        candidate = Candidate(full_name="测试候选人")
        first_job = Job(
            owner_id=owner.id,
            title="后端工程师",
            department="研发",
            original_jd="JD",
        )
        second_job = Job(
            owner_id=owner.id,
            title="平台工程师",
            department="研发",
            original_jd="JD",
        )
        db.add_all([candidate, first_job, second_job])
        db.flush()
        db.add_all(
            [
                JobApplication(candidate=candidate, job=first_job),
                JobApplication(candidate=candidate, job=second_job),
            ]
        )
        db.commit()

        db.add(JobApplication(candidate=candidate, job=first_job))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(JobApplication(candidate=candidate, job=first_job, status="merged"))
        db.commit()

    Base.metadata.drop_all(engine)
    engine.dispose()
