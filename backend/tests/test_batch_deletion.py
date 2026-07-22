import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Job, JobCriteriaVersion, ScreeningBatch, User
from app.services.batch_deletion import (
    BatchDeletionError,
    reconcile_deletion_staging,
    stage_batch_files,
)
from app.services.security import hash_password


@pytest.fixture
def deletion_session_factory() -> Generator[sessionmaker[Session], None, None]:
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


def create_batch(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as db:
        user = User(
            username="recruiter",
            password_hash=hash_password("correct-password"),
            display_name="招聘专员",
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
            confirmed_by_id=user.id,
        )
        db.add(criteria)
        db.flush()
        batch = ScreeningBatch(
            job_id=job.id,
            criteria_version_id=criteria.id,
            name="删除协调测试",
        )
        db.add(batch)
        db.commit()
        return batch.id


def test_stage_batch_files_restores_already_moved_files_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "private" / "first.pdf"
    second = tmp_path / "private" / "second.pdf"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    original_replace = Path.replace

    def fail_second_move(source: Path, target: Path) -> Path:
        if source.resolve() == second.resolve():
            raise OSError("simulated move failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_second_move)

    with pytest.raises(BatchDeletionError, match="批次数据未删除"):
        stage_batch_files(
            tmp_path,
            batch_id=uuid.uuid4(),
            storage_keys=["private/first.pdf", "private/second.pdf"],
        )

    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    staging_root = tmp_path / ".deletions"
    assert not staging_root.exists() or not any(staging_root.iterdir())


def test_reconcile_restores_uncommitted_and_purges_committed_deletion(
    tmp_path: Path,
    deletion_session_factory: sessionmaker[Session],
) -> None:
    batch_id = create_batch(deletion_session_factory)
    original = tmp_path / "private" / "resume.pdf"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"resume")

    uncommitted = stage_batch_files(
        tmp_path,
        batch_id=batch_id,
        storage_keys=["private/resume.pdf"],
    )
    assert not original.exists()
    assert uncommitted.operation_directory.is_dir()

    reconcile_deletion_staging(tmp_path, deletion_session_factory)

    assert original.read_bytes() == b"resume"
    assert not uncommitted.operation_directory.exists()

    committed = stage_batch_files(
        tmp_path,
        batch_id=batch_id,
        storage_keys=["private/resume.pdf"],
    )
    with deletion_session_factory() as db:
        batch = db.get(ScreeningBatch, batch_id)
        assert batch is not None
        db.delete(batch)
        db.commit()

    reconcile_deletion_staging(tmp_path, deletion_session_factory)

    assert not original.exists()
    assert not committed.operation_directory.exists()
