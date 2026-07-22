import hashlib
import os
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".jpg", ".jpeg", ".png"}
EXPECTED_MIME_TYPES = {
    "pdf": {"application/pdf"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
    "jpg": {"image/jpeg", "image/pjpeg"},
    "png": {"image/png"},
}
GENERIC_MIME_TYPES = {"", "application/octet-stream"}


class FileValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StoredUpload:
    original_filename: str
    file_extension: str
    content_type: str
    detected_type: str
    size_bytes: int
    sha256: str
    storage_key: str


def safe_original_filename(filename: str | None) -> str:
    normalized = (filename or "resume").replace("\\", "/").split("/")[-1].strip()
    return (normalized or "resume")[:255]


def _detected_type_for_extension(extension: str) -> str:
    if extension == ".pdf":
        return "pdf"
    if extension == ".docx":
        return "docx"
    if extension in {".jpg", ".jpeg"}:
        return "jpg"
    if extension == ".png":
        return "png"
    raise FileValidationError("unsupported_extension", "仅支持 PDF、DOCX、JPG 和 PNG 文件")


def _validate_file_signature(path: Path, detected_type: str) -> None:
    size = path.stat().st_size
    with path.open("rb") as file:
        header = file.read(16)
        if size > 1_024:
            file.seek(-1_024, os.SEEK_END)
        else:
            file.seek(0)
        tail = file.read()

    if detected_type == "pdf":
        valid = header.startswith(b"%PDF-") and b"%%EOF" in tail
    elif detected_type == "jpg":
        valid = header.startswith(b"\xff\xd8\xff") and tail.endswith(b"\xff\xd9")
    elif detected_type == "png":
        valid = header.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND\xaeB`\x82" in tail
    else:
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                valid = "[Content_Types].xml" in names and "word/document.xml" in names
        except (OSError, zipfile.BadZipFile):
            valid = False

    if not valid:
        raise FileValidationError("invalid_file_signature", "文件特征不完整或文件已经损坏")


async def store_resume_upload(
    upload: UploadFile,
    *,
    storage_root: Path,
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    max_size_bytes: int,
) -> StoredUpload:
    original_filename = safe_original_filename(upload.filename)
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FileValidationError("unsupported_extension", "仅支持 PDF、DOCX、JPG 和 PNG 文件")

    detected_type = _detected_type_for_extension(extension)
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in EXPECTED_MIME_TYPES[detected_type] | GENERIC_MIME_TYPES:
        raise FileValidationError("mime_mismatch", "文件 MIME 类型与扩展名不匹配")

    storage_root = storage_root.resolve()
    temporary_directory = storage_root / ".tmp"
    temporary_directory.mkdir(parents=True, exist_ok=True)
    temporary_path = temporary_directory / f"{uuid.uuid4().hex}.upload"
    digest = hashlib.sha256()
    size_bytes = 0

    try:
        with temporary_path.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > max_size_bytes:
                    raise FileValidationError(
                        "file_too_large",
                        f"单个文件不能超过 {max_size_bytes // (1024 * 1024)} MB",
                    )
                digest.update(chunk)
                target.write(chunk)

        if size_bytes == 0:
            raise FileValidationError("empty_file", "不能上传空文件")

        _validate_file_signature(temporary_path, detected_type)

        storage_key = f"{job_id}/{batch_id}/{uuid.uuid4().hex}{extension}"
        final_path = storage_root / Path(storage_key)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.replace(final_path)
        return StoredUpload(
            original_filename=original_filename,
            file_extension=extension,
            content_type=content_type,
            detected_type=detected_type,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
            storage_key=storage_key,
        )
    finally:
        temporary_path.unlink(missing_ok=True)


def resolve_private_file(storage_root: Path, storage_key: str) -> Path:
    resolved_root = storage_root.resolve()
    resolved_path = (resolved_root / storage_key).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise FileNotFoundError("非法文件路径")
    return resolved_path


def delete_private_file(storage_root: Path, storage_key: str | None) -> None:
    if not storage_key:
        return
    try:
        resolve_private_file(storage_root, storage_key).unlink(missing_ok=True)
    except OSError:
        return
