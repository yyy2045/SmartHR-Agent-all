from datetime import UTC, datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AuditLog,
    Candidate,
    CandidateDuplicateReview,
    CandidateProfile,
    Job,
    JobApplication,
    JobCriteriaVersion,
    ResumeDocument,
    ScreeningBatch,
    User,
)
from app.services.candidate_duplicates import (
    build_experience_fingerprint,
    detect_candidate_duplicates,
)
from app.services.security import hash_password


def _candidate_document(
    db: Session,
    *,
    batch: ScreeningBatch,
    candidate: Candidate,
    filename: str,
    sha256: str,
) -> ResumeDocument:
    application = JobApplication(candidate=candidate, job_id=batch.job_id)
    document = ResumeDocument(
        batch_id=batch.id,
        candidate=candidate,
        application=application,
        original_filename=filename,
        file_extension=".pdf",
        content_type="application/pdf",
        detected_type="pdf",
        size_bytes=100,
        sha256=sha256,
        status="completed",
        parsed_at=datetime.now(UTC),
        redacted_at=datetime.now(UTC),
    )
    db.add(document)
    db.flush()
    return document


def test_duplicate_detection_combines_strong_signals_and_is_idempotent() -> None:
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
        job = Job(owner_id=owner.id, title="后端工程师", department="研发", original_jd="JD")
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(job_id=job.id, version_number=1, status="confirmed")
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="重复检测批次",
            status="completed",
        )
        db.add(batch)
        db.flush()
        first = Candidate(
            full_name="张三",
            full_name_normalized="张三",
            phone="13800138000",
            phone_normalized="13800138000",
            email="zhangsan@example.com",
            email_normalized="zhangsan@example.com",
        )
        second = Candidate(
            full_name="张 三",
            full_name_normalized="张三",
            phone="138 0013 8000",
            phone_normalized="13800138000",
            email="ZHANGSAN@example.com",
            email_normalized="zhangsan@example.com",
        )
        _candidate_document(
            db,
            batch=batch,
            candidate=first,
            filename="first.pdf",
            sha256="a" * 64,
        )
        second_document = _candidate_document(
            db,
            batch=batch,
            candidate=second,
            filename="second.pdf",
            sha256="a" * 64,
        )

        first_run = detect_candidate_duplicates(db, document=second_document)
        second_run = detect_candidate_duplicates(db, document=second_document)
        db.commit()

        assert len(first_run) == 1
        assert len(second_run) == 1
        review = db.scalar(select(CandidateDuplicateReview))
        assert review is not None
        assert review.confidence == "strong"
        assert review.signals == ["email_exact", "phone_exact", "resume_sha256_exact"]
        assert db.scalar(select(func.count(CandidateDuplicateReview.id))) == 1
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "candidate.duplicate_detected"
                )
            )
            == 1
        )
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_duplicate_detection_uses_name_and_experience_as_weak_signal() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    experience = [
        {
            "company": "示例科技",
            "title": "后端工程师",
            "start_date": "2021-01",
            "end_date": "2024-06",
        }
    ]
    with Session(engine) as db:
        owner = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
        )
        db.add(owner)
        db.flush()
        job = Job(owner_id=owner.id, title="平台工程师", department="研发", original_jd="JD")
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(job_id=job.id, version_number=1, status="confirmed")
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="弱信号批次",
            status="completed",
        )
        db.add(batch)
        db.flush()
        fingerprint = build_experience_fingerprint(experience)
        first = Candidate(
            full_name="李雷",
            full_name_normalized="李雷",
            experience_fingerprint=fingerprint,
        )
        second = Candidate(full_name="李 雷", full_name_normalized="李雷")
        _candidate_document(
            db,
            batch=batch,
            candidate=first,
            filename="first.pdf",
            sha256="a" * 64,
        )
        second_document = _candidate_document(
            db,
            batch=batch,
            candidate=second,
            filename="second.pdf",
            sha256="b" * 64,
        )
        profile = CandidateProfile(
            document_id=second_document.id,
            version_number=1,
            source="ai",
            model_name="stub-model",
            prompt_version="resume-match-v2",
            education=[],
            work_experiences=experience,
            projects=[],
            skills=[],
            certifications=[],
            languages=[],
        )
        db.add(profile)
        reviews = detect_candidate_duplicates(
            db,
            document=second_document,
            profile=profile,
        )
        db.commit()

        assert len(reviews) == 1
        assert reviews[0].confidence == "weak"
        assert reviews[0].signals == ["name_experience_exact"]
        assert second.experience_fingerprint == fingerprint
    Base.metadata.drop_all(engine)
    engine.dispose()
