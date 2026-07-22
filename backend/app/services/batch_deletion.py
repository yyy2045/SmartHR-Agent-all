import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.models import ScreeningBatch
from app.services.file_storage import resolve_private_file

logger = logging.getLogger(__name__)


class BatchDeletionError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedFile:
    original_path: Path
    staged_path: Path


@dataclass
class StagedBatchFiles:
    operation_directory: Path
    files: list[StagedFile]

    def restore(self) -> None:
        errors: list[OSError] = []
        for item in reversed(self.files):
            if not item.staged_path.exists():
                continue
            try:
                if item.original_path.exists():
                    raise FileExistsError(f"恢复目标已经存在：{item.original_path}")
                item.original_path.parent.mkdir(parents=True, exist_ok=True)
                item.staged_path.replace(item.original_path)
            except OSError as error:
                errors.append(error)
        if not errors:
            shutil.rmtree(self.operation_directory, ignore_errors=True)
            return
        raise BatchDeletionError("数据库删除失败后，原始文件恢复不完整") from errors[0]

    def purge(self) -> None:
        shutil.rmtree(self.operation_directory)


def _manifest_path(operation_directory: Path) -> Path:
    return operation_directory / "manifest.json"


def stage_batch_files(
    storage_root: Path,
    *,
    batch_id: uuid.UUID,
    storage_keys: list[str],
) -> StagedBatchFiles:
    resolved_root = storage_root.resolve()
    operation_directory = resolved_root / ".deletions" / uuid.uuid4().hex
    staged_files: list[StagedFile] = []
    entries: list[dict[str, str]] = []
    try:
        for index, storage_key in enumerate(dict.fromkeys(storage_keys)):
            original_path = resolve_private_file(resolved_root, storage_key)
            if not original_path.exists():
                continue
            staged_path = operation_directory / "files" / f"{index:04d}{original_path.suffix}"
            staged_files.append(StagedFile(original_path=original_path, staged_path=staged_path))
            entries.append(
                {
                    "original": original_path.relative_to(resolved_root).as_posix(),
                    "staged": staged_path.relative_to(operation_directory).as_posix(),
                }
            )

        operation_directory.mkdir(parents=True, exist_ok=False)
        _manifest_path(operation_directory).write_text(
            json.dumps(
                {"batch_id": str(batch_id), "files": entries},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        for item in staged_files:
            item.staged_path.parent.mkdir(parents=True, exist_ok=True)
            item.original_path.replace(item.staged_path)
    except (OSError, ValueError) as error:
        staged = StagedBatchFiles(operation_directory, staged_files)
        try:
            staged.restore()
        except BatchDeletionError:
            logger.exception("批次删除暂存失败且文件恢复不完整，batch_id=%s", batch_id)
        raise BatchDeletionError("原始文件删除准备失败，批次数据未删除") from error
    return StagedBatchFiles(operation_directory, staged_files)


def _load_staged_operation(
    storage_root: Path,
    operation_directory: Path,
) -> tuple[uuid.UUID, StagedBatchFiles]:
    payload = json.loads(_manifest_path(operation_directory).read_text(encoding="utf-8"))
    files = [
        StagedFile(
            original_path=resolve_private_file(storage_root, item["original"]),
            staged_path=(operation_directory / item["staged"]).resolve(),
        )
        for item in payload["files"]
    ]
    if any(not item.staged_path.is_relative_to(operation_directory) for item in files):
        raise ValueError("删除暂存清单包含非法路径")
    return uuid.UUID(payload["batch_id"]), StagedBatchFiles(operation_directory, files)


def reconcile_deletion_staging(
    storage_root: Path,
    session_factory: sessionmaker[Session],
) -> None:
    resolved_root = storage_root.resolve()
    staging_root = resolved_root / ".deletions"
    if not staging_root.is_dir():
        return
    for operation_directory in staging_root.iterdir():
        if not operation_directory.is_dir():
            continue
        try:
            batch_id, staged = _load_staged_operation(resolved_root, operation_directory)
            with session_factory() as db:
                batch_exists = db.get(ScreeningBatch, batch_id) is not None
            if batch_exists:
                staged.restore()
                logger.warning("已恢复未提交的批次删除文件，batch_id=%s", batch_id)
            else:
                staged.purge()
                logger.info("已清理已提交的批次删除暂存，batch_id=%s", batch_id)
        except Exception:
            logger.exception("无法协调批次删除暂存目录：%s", operation_directory)
