import io
import uuid
import zipfile
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    AuditLog,
    CandidateProfile,
    Job,
    JobCriteriaVersion,
    RecruiterDecision,
    ResumeDocument,
    ResumeRedaction,
    ResumeTextSegment,
    ScreeningBatch,
    ScreeningResult,
    User,
)
from app.redis_client import get_session_store
from app.services.batch_deletion import (
    BatchDeletionError,
    StagedBatchFiles,
    reconcile_deletion_staging,
)
from app.services.file_storage import resolve_private_file
from app.services.security import hash_password
from app.services.session_store import SessionStore

VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
VALID_PNG = b"\x89PNG\r\n\x1a\nminimal-IEND\xaeB`\x82"
VALID_JPEG = b"\xff\xd8\xff\xe0minimal-jpeg\xff\xd9"


@dataclass(frozen=True)
class BatchDependencies:
    job_id: str
    criteria_version_id: str
    session_factory: sessionmaker[Session]
    enqueued_document_ids: list[str]


def make_docx() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return output.getvalue()


@pytest.fixture
def batch_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[BatchDependencies, None, None]:
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
            display_name="测试招聘专员",
        )
        db.add(user)
        db.flush()
        job = Job(
            owner_id=user.id,
            title="平台工程师",
            department="研发中心",
            original_jd="负责平台工程建设。",
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
        db.add(criteria)
        db.commit()
        job_id = str(job.id)
        criteria_version_id = str(criteria.id)

    session_store = SessionStore(
        redis_client=fakeredis.FakeRedis(decode_responses=True),
        ttl_seconds=3600,
    )

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    def override_session_store() -> SessionStore:
        return session_store

    previous_storage_root = settings.file_storage_root
    previous_max_size = settings.max_resume_file_size_mb
    previous_max_count = settings.max_batch_file_count
    settings.file_storage_root = tmp_path
    settings.max_resume_file_size_mb = 20
    settings.max_batch_file_count = 2
    enqueued_document_ids: list[str] = []

    def enqueue(document_id: object) -> str:
        value = str(document_id)
        enqueued_document_ids.append(value)
        return f"test-task-{value}"

    monkeypatch.setattr("app.api.routes.batches.enqueue_resume_parsing", enqueue)
    dependencies = BatchDependencies(
        job_id=job_id,
        criteria_version_id=criteria_version_id,
        session_factory=testing_session,
        enqueued_document_ids=enqueued_document_ids,
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_session_store
    yield dependencies
    app.dependency_overrides.clear()
    settings.file_storage_root = previous_storage_root
    settings.max_resume_file_size_mb = previous_max_size
    settings.max_batch_file_count = previous_max_count
    Base.metadata.drop_all(engine)
    engine.dispose()


async def login(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/login",
        json={"username": "recruiter", "password": "correct-password"},
    )
    assert response.status_code == 200


async def upload_single_resume(
    client: httpx.AsyncClient,
    dependencies: BatchDependencies,
    *,
    filename: str,
    marker: bytes,
) -> tuple[dict[str, object], Path]:
    response = await client.post(
        f"/jobs/{dependencies.job_id}/batches",
        data={"criteria_version_id": dependencies.criteria_version_id},
        files={"files": (filename, VALID_PDF + marker, "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    document_id = uuid.UUID(body["documents"][0]["id"])
    with dependencies.session_factory() as db:
        document = db.get(ResumeDocument, document_id)
        assert document is not None and document.storage_key is not None
        file_path = resolve_private_file(settings.file_storage_root, document.storage_key)
    assert file_path.is_file()
    return body, file_path


@pytest.mark.asyncio
async def test_batch_routes_require_authentication(
    batch_dependencies: BatchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    job_id = batch_dependencies.job_id
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/jobs/{job_id}/batches")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_all_supported_resume_formats_are_accepted(
    batch_dependencies: BatchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    job_id = batch_dependencies.job_id
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        document_batch = await client.post(
            f"/jobs/{job_id}/batches",
            data={"criteria_version_id": batch_dependencies.criteria_version_id},
            files=[
                ("files", ("resume.pdf", VALID_PDF, "application/pdf")),
                (
                    "files",
                    (
                        "resume.docx",
                        make_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ),
            ],
        )
        image_batch = await client.post(
            f"/jobs/{job_id}/batches",
            data={"criteria_version_id": batch_dependencies.criteria_version_id},
            files=[
                ("files", ("resume.jpg", VALID_JPEG, "image/jpeg")),
                ("files", ("resume.png", VALID_PNG, "image/png")),
            ],
        )

    assert document_batch.status_code == 201
    assert image_batch.status_code == 201
    bodies = [document_batch.json(), image_batch.json()]
    assert all(body["status"] == "processing" for body in bodies)
    assert all(body["total_count"] == 2 for body in bodies)
    assert all(body["success_count"] == 0 for body in bodies)
    assert all(body["processing_count"] == 2 for body in bodies)
    assert {
        item["detected_type"] for body in bodies for item in body["documents"]
    } == {
        "pdf",
        "docx",
        "jpg",
        "png",
    }


@pytest.mark.asyncio
async def test_partial_failure_download_duplicate_and_retry(
    batch_dependencies: BatchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    job_id = batch_dependencies.job_id
    criteria_version_id = batch_dependencies.criteria_version_id
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.post(
            f"/jobs/{job_id}/batches",
            data={"criteria_version_id": criteria_version_id, "name": "第一批简历"},
            files=[
                ("files", ("../../private.pdf", VALID_PDF, "application/pdf")),
                ("files", ("fake.png", VALID_PDF, "image/png")),
            ],
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "processing"
        assert body["success_count"] == 0
        assert body["failed_count"] == 1
        valid_document = next(item for item in body["documents"] if item["status"] == "queued")
        failed_document = next(item for item in body["documents"] if item["status"] == "failed")
        assert valid_document["original_filename"] == "private.pdf"
        assert failed_document["failure_code"] == "invalid_file_signature"

        download = await client.get(
            f"/jobs/{job_id}/batches/{body['id']}/documents/{valid_document['id']}/file"
        )
        assert download.status_code == 200
        assert download.content == VALID_PDF

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as anonymous:
            unauthorized_download = await anonymous.get(
                f"/jobs/{job_id}/batches/{body['id']}/documents/{valid_document['id']}/file"
            )
        assert unauthorized_download.status_code == 401

        retry = await client.put(
            f"/jobs/{job_id}/batches/{body['id']}/documents/{failed_document['id']}/retry",
            files={"file": ("replacement.png", VALID_PNG, "image/png")},
        )
        assert retry.status_code == 200
        assert retry.json()["status"] == "queued"
        assert retry.json()["attempt_count"] == 2

        refreshed = await client.get(f"/jobs/{job_id}/batches/{body['id']}")
        assert refreshed.json()["status"] == "processing"
        assert refreshed.json()["processing_count"] == 2

        duplicate = await client.post(
            f"/jobs/{job_id}/batches",
            data={"criteria_version_id": criteria_version_id},
            files={"files": ("duplicate.pdf", VALID_PDF, "application/pdf")},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["status"] == "failed"
        assert duplicate.json()["documents"][0]["failure_code"] == "duplicate_file"

    stored_files = [path for path in settings.file_storage_root.rglob("*") if path.is_file()]
    assert len(stored_files) == 2
    assert all(path.name not in {"private.pdf", "replacement.png"} for path in stored_files)
    with batch_dependencies.session_factory() as db:
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "resume.file_viewed")
        )
    assert audit is not None
    assert audit.actor_username == "recruiter"
    assert str(audit.target_id) == valid_document["id"]
    assert str(audit.batch_id) == body["id"]


@pytest.mark.asyncio
async def test_batch_limits_and_mime_validation(
    batch_dependencies: BatchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    job_id = batch_dependencies.job_id
    criteria_version_id = batch_dependencies.criteria_version_id
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        too_many = await client.post(
            f"/jobs/{job_id}/batches",
            data={"criteria_version_id": criteria_version_id},
            files=[
                ("files", (f"resume-{index}.pdf", VALID_PDF, "application/pdf"))
                for index in range(3)
            ],
        )
        assert too_many.status_code == 422
        assert "最多上传 2 份" in too_many.text

        settings.max_resume_file_size_mb = 1
        large_pdf = b"%PDF-1.4\n" + (b"0" * (1024 * 1024)) + b"%%EOF"
        validation_response = await client.post(
            f"/jobs/{job_id}/batches",
            data={"criteria_version_id": criteria_version_id},
            files=[
                ("files", ("large.pdf", large_pdf, "application/pdf")),
                ("files", ("wrong.pdf", VALID_PDF, "image/png")),
            ],
        )

    assert validation_response.status_code == 201
    documents = validation_response.json()["documents"]
    assert {item["failure_code"] for item in documents} == {
        "file_too_large",
        "mime_mismatch",
    }


@pytest.mark.asyncio
async def test_upload_queues_parsing_and_failed_parse_can_retry(
    batch_dependencies: BatchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        created = await client.post(
            f"/jobs/{batch_dependencies.job_id}/batches",
            data={"criteria_version_id": batch_dependencies.criteria_version_id},
            files={"files": ("resume.pdf", VALID_PDF, "application/pdf")},
        )
        assert created.status_code == 201
        document = created.json()["documents"][0]
        assert document["status"] == "queued"
        assert batch_dependencies.enqueued_document_ids == [document["id"]]

        with batch_dependencies.session_factory() as db:
            stored_document = db.get(ResumeDocument, uuid.UUID(document["id"]))
            assert stored_document is not None
            stored_document.status = "failed"
            stored_document.failure_code = "empty_text"
            stored_document.failure_message = "未识别到有效文本"
            stored_document.batch.status = "failed"
            db.commit()

        retried = await client.post(
            f"/jobs/{batch_dependencies.job_id}/batches/{created.json()['id']}"
            f"/documents/{document['id']}/parse-retry"
        )

    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["failure_code"] is None
    assert batch_dependencies.enqueued_document_ids == [document["id"], document["id"]]


@pytest.mark.asyncio
async def test_parse_retry_requires_original_and_detail_returns_segments(
    batch_dependencies: BatchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        invalid = await client.post(
            f"/jobs/{batch_dependencies.job_id}/batches",
            data={"criteria_version_id": batch_dependencies.criteria_version_id},
            files={"files": ("fake.png", VALID_PDF, "image/png")},
        )
        invalid_body = invalid.json()
        invalid_document = invalid_body["documents"][0]
        no_original_retry = await client.post(
            f"/jobs/{batch_dependencies.job_id}/batches/{invalid_body['id']}"
            f"/documents/{invalid_document['id']}/parse-retry"
        )
        assert no_original_retry.status_code == 409
        assert "重新选择文件" in no_original_retry.text

        created = await client.post(
            f"/jobs/{batch_dependencies.job_id}/batches",
            data={"criteria_version_id": batch_dependencies.criteria_version_id},
            files={"files": ("profile.pdf", VALID_PDF + b"profile", "application/pdf")},
        )
        body = created.json()
        document_id = body["documents"][0]["id"]
        with batch_dependencies.session_factory() as db:
            document = db.get(ResumeDocument, uuid.UUID(document_id))
            assert document is not None
            document.status = "completed"
            document.extraction_method = "pdf_text"
            document.segment_count = 1
            document.text_character_count = 14
            document.batch.status = "completed"
            document.text_segments.append(
                ResumeTextSegment(
                    segment_key="SEG-0001",
                    source_type="pdf_page",
                    source_index=1,
                    page_number=1,
                    raw_text="Python Engineer",
                    normalized_text="Python Engineer",
                    sort_order=0,
                )
            )
            db.commit()

        detail = await client.get(
            f"/jobs/{batch_dependencies.job_id}/batches/{body['id']}"
            f"/documents/{document_id}"
        )

    assert detail.status_code == 200
    assert detail.json()["extraction_method"] == "pdf_text"
    assert detail.json()["candidate_code"] == body["documents"][0]["candidate_code"]
    assert detail.json()["text_segments"] == [
        {
            "id": detail.json()["text_segments"][0]["id"],
            "document_id": document_id,
            "segment_key": "SEG-0001",
            "source_type": "pdf_page",
            "source_index": 1,
            "page_number": 1,
            "paragraph_index": None,
            "raw_text": "Python Engineer",
            "normalized_text": "Python Engineer",
            "redacted_text": None,
            "ocr_confidence": None,
            "sort_order": 0,
        }
    ]


@pytest.mark.asyncio
async def test_document_detail_respects_job_ownership(
    batch_dependencies: BatchDependencies,
) -> None:
    with batch_dependencies.session_factory() as db:
        other_user = User(
            username="other-recruiter",
            password_hash=hash_password("other-password"),
            display_name="其他招聘专员",
        )
        db.add(other_user)
        db.flush()
        other_job = Job(
            owner_id=other_user.id,
            title="私有职位",
            department="其他部门",
            original_jd="不可跨用户访问",
        )
        db.add(other_job)
        db.flush()
        other_criteria = JobCriteriaVersion(
            job_id=other_job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=other_user.id,
        )
        db.add(other_criteria)
        db.flush()
        other_batch = ScreeningBatch(
            job_id=other_job.id,
            criteria_version_id=other_criteria.id,
            name="私有批次",
        )
        db.add(other_batch)
        db.flush()
        other_document = ResumeDocument(
            batch_id=other_batch.id,
            original_filename="private.pdf",
            status="failed",
        )
        db.add(other_document)
        db.commit()
        path = (
            f"/jobs/{other_job.id}/batches/{other_batch.id}"
            f"/documents/{other_document.id}"
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.get(path)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_batch_permanent_delete_cascades_database_and_private_file(
    batch_dependencies: BatchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        body, file_path = await upload_single_resume(
            client,
            batch_dependencies,
            filename="delete-success.pdf",
            marker=b"delete-success",
        )
        batch_id = uuid.UUID(body["id"])
        document_id = uuid.UUID(body["documents"][0]["id"])
        with batch_dependencies.session_factory() as db:
            document = db.get(ResumeDocument, document_id)
            user = db.scalar(select(User).where(User.username == "recruiter"))
            assert document is not None and user is not None
            document.status = "completed"
            segment = ResumeTextSegment(
                document=document,
                segment_key="SEG-0001",
                source_type="pdf_page",
                source_index=1,
                page_number=1,
                raw_text="姓名：测试候选人，Python 工程经验",
                normalized_text="姓名：测试候选人，Python 工程经验",
                redacted_text="姓名：[姓名]，Python 工程经验",
                sort_order=0,
            )
            segment.redactions = [
                ResumeRedaction(
                    entity_type="name",
                    original_text="测试候选人",
                    replacement_text="[姓名]",
                    start_offset=3,
                    end_offset=8,
                )
            ]
            profile = CandidateProfile(
                document=document,
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
            result = ScreeningResult(
                document=document,
                candidate_profile=profile,
                criteria_version_id=uuid.UUID(batch_dependencies.criteria_version_id),
                analysis_version=1,
                status="completed",
                ai_group="passed",
                total_score=Decimal("88.00"),
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
            result.recruiter_decisions = [
                RecruiterDecision(
                    operator_id=user.id,
                    sequence_number=1,
                    previous_decision="unprocessed",
                    decision="shortlisted",
                    reason="测试级联删除",
                    is_auto_rejection_override=False,
                )
            ]
            db.add_all([segment, result])
            db.commit()

        deleted = await client.request(
            "DELETE",
            f"/jobs/{batch_dependencies.job_id}/batches/{body['id']}",
            json={"confirmation": "永久删除"},
        )

    assert deleted.status_code == 200
    assert deleted.json() == {
        "status": "deleted",
        "batch_id": str(batch_id),
        "deleted_document_count": 1,
        "deleted_file_count": 1,
        "message": None,
    }
    assert not file_path.exists()
    staging_root = settings.file_storage_root / ".deletions"
    assert not staging_root.exists() or not any(staging_root.iterdir())
    with batch_dependencies.session_factory() as db:
        assert db.get(ScreeningBatch, batch_id) is None
        assert db.get(ResumeDocument, document_id) is None
        for model in (
            ResumeTextSegment,
            ResumeRedaction,
            CandidateProfile,
            ScreeningResult,
            RecruiterDecision,
        ):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "batch.permanent_delete",
                AuditLog.result == "success",
            )
        )
    assert audit is not None
    assert audit.actor_username == "recruiter"
    assert audit.target_id == batch_id
    assert audit.details == {"document_count": 1, "file_count": 1}


@pytest.mark.asyncio
async def test_batch_delete_requires_confirmation_and_preserves_data(
    batch_dependencies: BatchDependencies,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        body, file_path = await upload_single_resume(
            client,
            batch_dependencies,
            filename="delete-confirmation.pdf",
            marker=b"delete-confirmation",
        )
        response = await client.request(
            "DELETE",
            f"/jobs/{batch_dependencies.job_id}/batches/{body['id']}",
            json={"confirmation": "确认"},
        )

    assert response.status_code == 422
    assert "永久删除" in response.text
    assert file_path.is_file()
    batch_id = uuid.UUID(body["id"])
    with batch_dependencies.session_factory() as db:
        assert db.get(ScreeningBatch, batch_id) is not None
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "batch.permanent_delete",
                AuditLog.result == "failure",
            )
        )
    assert audit is not None
    assert audit.details == {"reason": "confirmation_mismatch"}


@pytest.mark.asyncio
async def test_batch_delete_staging_failure_preserves_database_and_file(
    batch_dependencies: BatchDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        body, file_path = await upload_single_resume(
            client,
            batch_dependencies,
            filename="delete-stage-failure.pdf",
            marker=b"delete-stage-failure",
        )

        def fail_staging(*_: object, **__: object) -> None:
            raise BatchDeletionError("原始文件删除准备失败，批次数据未删除")

        monkeypatch.setattr("app.api.routes.batches.stage_batch_files", fail_staging)
        response = await client.request(
            "DELETE",
            f"/jobs/{batch_dependencies.job_id}/batches/{body['id']}",
            json={"confirmation": "永久删除"},
        )

    assert response.status_code == 500
    assert "批次数据未删除" in response.text
    assert file_path.is_file()
    with batch_dependencies.session_factory() as db:
        assert db.get(ScreeningBatch, uuid.UUID(body["id"])) is not None
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "batch.permanent_delete",
                AuditLog.result == "failure",
            )
        )
    assert audit is not None
    assert audit.details == {"reason": "file_staging_failed"}


@pytest.mark.asyncio
async def test_batch_delete_database_failure_restores_private_file(
    batch_dependencies: BatchDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        body, file_path = await upload_single_resume(
            client,
            batch_dependencies,
            filename="delete-database-failure.pdf",
            marker=b"delete-database-failure",
        )
        original_commit = Session.commit
        failed_once = False

        def fail_batch_delete_commit(session: Session) -> None:
            nonlocal failed_once
            if not failed_once and any(
                isinstance(item, ScreeningBatch) for item in session.deleted
            ):
                failed_once = True
                raise RuntimeError("simulated database failure")
            original_commit(session)

        monkeypatch.setattr(Session, "commit", fail_batch_delete_commit)
        response = await client.request(
            "DELETE",
            f"/jobs/{batch_dependencies.job_id}/batches/{body['id']}",
            json={"confirmation": "永久删除"},
        )

    assert failed_once is True
    assert response.status_code == 500
    assert "原始文件已恢复" in response.text
    assert file_path.is_file()
    staging_root = settings.file_storage_root / ".deletions"
    assert not staging_root.exists() or not any(staging_root.iterdir())
    with batch_dependencies.session_factory() as db:
        assert db.get(ScreeningBatch, uuid.UUID(body["id"])) is not None
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "batch.permanent_delete",
                AuditLog.result == "failure",
            )
        )
    assert audit is not None
    assert audit.details == {"reason": "database_delete_failed"}


@pytest.mark.asyncio
async def test_batch_delete_reports_cleanup_pending_and_startup_finishes_cleanup(
    batch_dependencies: BatchDependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        body, file_path = await upload_single_resume(
            client,
            batch_dependencies,
            filename="delete-cleanup-pending.pdf",
            marker=b"delete-cleanup-pending",
        )

        def fail_purge(_: StagedBatchFiles) -> None:
            raise OSError("simulated cleanup failure")

        monkeypatch.setattr(StagedBatchFiles, "purge", fail_purge)
        response = await client.request(
            "DELETE",
            f"/jobs/{batch_dependencies.job_id}/batches/{body['id']}",
            json={"confirmation": "永久删除"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "cleanup_pending"
    assert response.json()["deleted_file_count"] == 0
    assert "服务重启" in response.json()["message"]
    assert not file_path.exists()
    batch_id = uuid.UUID(body["id"])
    with batch_dependencies.session_factory() as db:
        assert db.get(ScreeningBatch, batch_id) is None
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "batch.file_cleanup_pending")
        )
    assert audit is not None
    assert audit.result == "failure"
    staging_root = settings.file_storage_root / ".deletions"
    assert staging_root.is_dir() and any(staging_root.iterdir())

    monkeypatch.undo()
    reconcile_deletion_staging(
        settings.file_storage_root,
        batch_dependencies.session_factory,
    )
    assert not staging_root.exists() or not any(staging_root.iterdir())


@pytest.mark.asyncio
async def test_batch_delete_blocks_anonymous_and_foreign_owner(
    batch_dependencies: BatchDependencies,
) -> None:
    with batch_dependencies.session_factory() as db:
        other_user = User(
            username="foreign-owner",
            password_hash=hash_password("foreign-password"),
            display_name="其他招聘专员",
        )
        db.add(other_user)
        db.flush()
        job = Job(
            owner_id=other_user.id,
            title="其他职位",
            department="其他部门",
            original_jd="私有职位",
        )
        db.add(job)
        db.flush()
        criteria = JobCriteriaVersion(
            job_id=job.id,
            version_number=1,
            status="confirmed",
            confirmed_by_id=other_user.id,
        )
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="私有批次",
        )
        db.add(batch)
        db.commit()
        path = f"/jobs/{job.id}/batches/{batch.id}"
        batch_id = batch.id

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.request(
            "DELETE",
            path,
            json={"confirmation": "永久删除"},
        )
        await login(client)
        foreign = await client.request(
            "DELETE",
            path,
            json={"confirmation": "永久删除"},
        )

    assert anonymous.status_code == 401
    assert foreign.status_code == 404
    with batch_dependencies.session_factory() as db:
        assert db.get(ScreeningBatch, batch_id) is not None
