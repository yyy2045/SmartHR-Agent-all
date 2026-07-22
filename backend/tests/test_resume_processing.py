import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base
from app.models import Job, JobCriteriaVersion, ResumeDocument, ScreeningBatch, User
from app.services.model_payload import send_resume_model_payload
from app.services.resume_parser import ParsedSegment, ParseResult, ResumeParseError
from app.services.resume_processing import process_resume_document
from app.services.security import hash_password


@pytest.fixture
def processing_dependencies(
    tmp_path: Path,
) -> Generator[tuple[sessionmaker[Session], uuid.UUID], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    storage_key = "job/batch/resume.pdf"
    file_path = tmp_path / storage_key
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"resume")

    with testing_session() as db:
        user = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
        )
        db.add(user)
        db.flush()
        job = Job(owner_id=user.id, title="工程师", department="研发", original_jd="JD")
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=user.id,
        )
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="解析测试批次",
            status="processing",
        )
        db.add(batch)
        db.flush()
        document = ResumeDocument(
            batch_id=batch.id,
            original_filename="resume.pdf",
            file_extension=".pdf",
            content_type="application/pdf",
            detected_type="pdf",
            size_bytes=6,
            sha256="a" * 64,
            storage_key=storage_key,
            status="queued",
        )
        db.add(document)
        db.commit()
        document_id = document.id

    previous_root = settings.file_storage_root
    settings.file_storage_root = tmp_path
    yield testing_session, document_id
    settings.file_storage_root = previous_root
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_processing_saves_stable_segments_and_completes_batch(
    processing_dependencies: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    testing_session, document_id = processing_dependencies

    def parser(_: Path, detected_type: str) -> ParseResult:
        assert detected_type == "pdf"
        return ParseResult(
            extraction_method="pdf_text",
            segments=[
                ParsedSegment(
                    source_type="pdf_page",
                    source_index=1,
                    page_number=1,
                    raw_text="  Python  ",
                    normalized_text="Python",
                ),
                ParsedSegment(
                    source_type="pdf_page",
                    source_index=2,
                    page_number=2,
                    raw_text="FastAPI",
                    normalized_text="FastAPI",
                ),
            ],
        )

    result = process_resume_document(
        document_id,
        task_id="task-1",
        session_factory=testing_session,
        parser=parser,
    )

    assert result == {
        "status": "completed",
        "document_id": str(document_id),
        "segments": 2,
    }
    with testing_session() as db:
        document = db.scalar(select(ResumeDocument).where(ResumeDocument.id == document_id))
        assert document is not None
        assert document.status == "completed"
        assert document.extraction_method == "pdf_text"
        assert document.segment_count == 2
        assert document.text_character_count == 13
        assert document.processing_attempt_count == 1
        assert document.task_id == "task-1"
        assert document.redacted_at is not None
        assert document.redaction_count == 0
        assert [segment.segment_key for segment in document.text_segments] == [
            "SEG-0001",
            "SEG-0002",
        ]
        assert [segment.redacted_text for segment in document.text_segments] == [
            "Python",
            "FastAPI",
        ]
        assert document.batch.status == "completed"

    repeated = process_resume_document(
        document_id,
        session_factory=testing_session,
        parser=lambda *_: pytest.fail("完成的文件不应重复解析"),
    )
    assert repeated["status"] == "completed"


def test_processing_redacts_before_model_payload_and_keeps_original_evidence(
    processing_dependencies: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    testing_session, document_id = processing_dependencies
    original = (
        "姓名：李雷\n电话：13912345678\n邮箱：li.lei@example.com\n"
        "地址：上海市浦东新区世纪大道100号8室\n微信：lilei_hr"
    )

    def parser(_: Path, __: str) -> ParseResult:
        return ParseResult(
            extraction_method="pdf_text",
            segments=[
                ParsedSegment(
                    source_type="pdf_page",
                    source_index=1,
                    page_number=1,
                    raw_text=original,
                    normalized_text=original,
                )
            ],
        )

    process_resume_document(
        document_id,
        session_factory=testing_session,
        parser=parser,
    )

    with testing_session() as db:
        document = db.scalar(select(ResumeDocument).where(ResumeDocument.id == document_id))
        assert document is not None
        assert document.redaction_count == 5
        segment = document.text_segments[0]
        assert segment.segment_key == "SEG-0001"
        assert segment.normalized_text == original
        assert segment.redacted_text is not None
        assert "李雷" not in segment.redacted_text
        assert "13912345678" not in segment.redacted_text
        assert "li.lei@example.com" not in segment.redacted_text
        assert {item.entity_type for item in segment.redactions} == {
            "name",
            "phone",
            "email",
            "address",
            "social_account",
        }

        captured_payloads: list[dict[str, object]] = []
        send_resume_model_payload(document, captured_payloads.append)

        assert captured_payloads == [
            {
                "candidate_code": document.candidate_code,
                "segments": [
                    {
                        "segment_key": "SEG-0001",
                        "text": segment.redacted_text,
                    }
                ],
            }
        ]
        serialized = str(captured_payloads)
        for sensitive_value in (
            "李雷",
            "13912345678",
            "li.lei@example.com",
            "上海市浦东新区世纪大道100号8室",
            "lilei_hr",
        ):
            assert sensitive_value not in serialized


def test_processing_failure_keeps_original_file_and_marks_batch(
    processing_dependencies: tuple[sessionmaker[Session], uuid.UUID],
) -> None:
    testing_session, document_id = processing_dependencies

    def parser(_: Path, __: str) -> ParseResult:
        raise ResumeParseError("empty_text", "未识别到有效文本")

    result = process_resume_document(
        document_id,
        session_factory=testing_session,
        parser=parser,
    )

    assert result["status"] == "failed"
    assert result["code"] == "empty_text"
    with testing_session() as db:
        document = db.scalar(select(ResumeDocument).where(ResumeDocument.id == document_id))
        assert document is not None
        assert document.status == "failed"
        assert document.failure_message == "未识别到有效文本"
        assert document.storage_key == "job/batch/resume.pdf"
        assert document.batch.status == "failed"
