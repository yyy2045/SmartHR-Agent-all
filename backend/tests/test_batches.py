import io
import zipfile
from collections.abc import Generator
from pathlib import Path

import fakeredis
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import Job, JobCriteriaVersion, User
from app.redis_client import get_session_store
from app.services.security import hash_password
from app.services.session_store import SessionStore

VALID_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
VALID_PNG = b"\x89PNG\r\n\x1a\nminimal-IEND\xaeB`\x82"
VALID_JPEG = b"\xff\xd8\xff\xe0minimal-jpeg\xff\xd9"


def make_docx() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return output.getvalue()


@pytest.fixture
def batch_dependencies(tmp_path: Path) -> Generator[dict[str, str], None, None]:
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
        ids = {"job_id": str(job.id), "criteria_version_id": str(criteria.id)}

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
    settings.max_batch_file_count = 50
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_store] = override_session_store
    yield ids
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


@pytest.mark.asyncio
async def test_batch_routes_require_authentication(batch_dependencies: dict[str, str]) -> None:
    transport = httpx.ASGITransport(app=app)
    job_id = batch_dependencies["job_id"]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/jobs/{job_id}/batches")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_all_supported_resume_formats_are_accepted(
    batch_dependencies: dict[str, str],
) -> None:
    transport = httpx.ASGITransport(app=app)
    job_id = batch_dependencies["job_id"]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        response = await client.post(
            f"/jobs/{job_id}/batches",
            data={"criteria_version_id": batch_dependencies["criteria_version_id"]},
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
                ("files", ("resume.jpg", VALID_JPEG, "image/jpeg")),
                ("files", ("resume.png", VALID_PNG, "image/png")),
            ],
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ready"
    assert body["total_count"] == 4
    assert body["success_count"] == 4
    assert {item["detected_type"] for item in body["documents"]} == {
        "pdf",
        "docx",
        "jpg",
        "png",
    }


@pytest.mark.asyncio
async def test_partial_failure_download_duplicate_and_retry(
    batch_dependencies: dict[str, str],
) -> None:
    transport = httpx.ASGITransport(app=app)
    job_id = batch_dependencies["job_id"]
    criteria_version_id = batch_dependencies["criteria_version_id"]
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
        assert body["status"] == "partial_failure"
        assert body["success_count"] == 1
        assert body["failed_count"] == 1
        valid_document = next(item for item in body["documents"] if item["status"] == "uploaded")
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
        assert retry.json()["status"] == "uploaded"
        assert retry.json()["attempt_count"] == 2

        refreshed = await client.get(f"/jobs/{job_id}/batches/{body['id']}")
        assert refreshed.json()["status"] == "ready"
        assert refreshed.json()["success_count"] == 2

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


@pytest.mark.asyncio
async def test_batch_limits_and_mime_validation(batch_dependencies: dict[str, str]) -> None:
    transport = httpx.ASGITransport(app=app)
    job_id = batch_dependencies["job_id"]
    criteria_version_id = batch_dependencies["criteria_version_id"]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client)
        too_many = await client.post(
            f"/jobs/{job_id}/batches",
            data={"criteria_version_id": criteria_version_id},
            files=[
                ("files", (f"resume-{index}.pdf", VALID_PDF, "application/pdf"))
                for index in range(51)
            ],
        )
        assert too_many.status_code == 422
        assert "最多上传 50 份" in too_many.text

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
