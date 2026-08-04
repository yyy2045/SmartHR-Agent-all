from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.config import settings
from app.database import SessionLocal
from app.models import (
    RecruitmentKnowledgeBase,
    RecruitmentKnowledgeChunk,
    RecruitmentKnowledgeDocument,
    RecruitmentKnowledgeDocumentVersion,
    User,
)
from app.schemas.recruitment_knowledge import (
    RecruitmentKnowledgeDocumentVersionCreateRequest,
)
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingConfigurationError,
    EmbeddingRequestTimeout,
    EmbeddingResponseValidationError,
    EmbeddingUpstreamError,
    get_embedding_client,
)
from app.services.resume_parser import ResumeParseError, normalize_resume_text, parse_resume_file

SessionFactory = sessionmaker[Session]
DEFAULT_KNOWLEDGE_BASE_NAME = "默认招聘知识库"
MAX_KNOWLEDGE_CHUNK_TEXT_LENGTH = 1_800
KNOWLEDGE_CHUNK_OVERLAP = 160
SUPPORTED_KNOWLEDGE_EXTENSIONS = {
    ".txt": "text",
    ".md": "markdown",
    ".pdf": "pdf",
    ".docx": "docx",
}


class RecruitmentKnowledgeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class KnowledgeChunkDraft:
    chunk_index: int
    chunk_text: str
    heading_path: list[str]
    source_locator: str | None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.chunk_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ParsedKnowledgeUpload:
    raw_text: str
    parser_name: str
    parser_version: str
    storage_key: str
    source_filename: str
    mime_type: str | None
    content_hash: str


def _content_hash(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _actor_snapshot(actor: User) -> dict[str, object]:
    return {
        "created_by_id": actor.id,
        "created_by_username": actor.username,
        "created_by_display_name": actor.display_name,
    }


def _published_actor_snapshot(actor: User) -> dict[str, object]:
    return {
        "published_by_id": actor.id,
        "published_by_username": actor.username,
        "published_by_display_name": actor.display_name,
        "published_at": datetime.now(UTC),
    }


def ensure_default_knowledge_base(db: Session, actor: User) -> RecruitmentKnowledgeBase:
    knowledge_base = db.scalar(
        select(RecruitmentKnowledgeBase).where(
            RecruitmentKnowledgeBase.name == DEFAULT_KNOWLEDGE_BASE_NAME
        )
    )
    if knowledge_base is not None:
        return knowledge_base
    knowledge_base = RecruitmentKnowledgeBase(
        name=DEFAULT_KNOWLEDGE_BASE_NAME,
        description="用于保存招聘制度、岗位标准、面试评分、Offer 规则和沟通话术。",
        **_actor_snapshot(actor),
    )
    db.add(knowledge_base)
    db.flush()
    return knowledge_base


def list_knowledge_bases(db: Session) -> list[RecruitmentKnowledgeBase]:
    return list(
        db.scalars(
            select(RecruitmentKnowledgeBase).order_by(
                RecruitmentKnowledgeBase.status,
                RecruitmentKnowledgeBase.created_at,
            )
        )
    )


def _normalize_tags(tags: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        value = normalize_resume_text(str(tag))[:40]
        if value and value not in normalized:
            normalized.append(value)
    return normalized[:20]


def _paragraphs_with_headings(raw_text: str) -> list[tuple[str, list[str], str | None]]:
    normalized = normalize_resume_text(raw_text)
    headings: list[str] = []
    paragraphs: list[tuple[str, list[str], str | None]] = []
    buffer: list[str] = []
    paragraph_index = 1

    def flush() -> None:
        nonlocal paragraph_index
        text = "\n".join(buffer).strip()
        if text:
            paragraphs.append((text, [*headings], f"第 {paragraph_index} 段"))
            paragraph_index += 1
        buffer.clear()

    for line in normalized.split("\n"):
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("#"):
            flush()
            title = stripped.lstrip("#").strip()
            if title:
                level = min(len(stripped) - len(stripped.lstrip("#")), 6)
                headings = [*headings[: level - 1], title]
            continue
        buffer.append(stripped)
    flush()
    return paragraphs


def build_knowledge_chunks(raw_text: str) -> list[KnowledgeChunkDraft]:
    paragraphs = _paragraphs_with_headings(raw_text)
    if not paragraphs:
        raise RecruitmentKnowledgeError("empty_text", "知识文档未包含有效文本")

    drafts: list[KnowledgeChunkDraft] = []
    current_lines: list[str] = []
    current_headings: list[str] = []
    current_locator: str | None = None

    def flush() -> None:
        nonlocal current_locator
        text = "\n\n".join(current_lines).strip()
        if not text:
            return
        drafts.append(
            KnowledgeChunkDraft(
                chunk_index=len(drafts),
                chunk_text=text[:MAX_KNOWLEDGE_CHUNK_TEXT_LENGTH],
                heading_path=[*current_headings],
                source_locator=current_locator,
            )
        )
        current_lines.clear()
        current_locator = None

    for paragraph, headings, locator in paragraphs:
        candidate_length = len("\n\n".join([*current_lines, paragraph]))
        if current_lines and candidate_length > MAX_KNOWLEDGE_CHUNK_TEXT_LENGTH:
            overlap = current_lines[-1][-KNOWLEDGE_CHUNK_OVERLAP:] if current_lines else ""
            flush()
            if overlap:
                current_lines.append(overlap)
        if not current_lines:
            current_headings = [*headings]
            current_locator = locator
        current_lines.append(paragraph)
    flush()
    return drafts


def _get_or_create_document(
    db: Session,
    payload: RecruitmentKnowledgeDocumentVersionCreateRequest,
    actor: User,
) -> tuple[RecruitmentKnowledgeBase, RecruitmentKnowledgeDocument]:
    knowledge_base = (
        db.get(RecruitmentKnowledgeBase, payload.knowledge_base_id)
        if payload.knowledge_base_id
        else ensure_default_knowledge_base(db, actor)
    )
    if knowledge_base is None:
        raise RecruitmentKnowledgeError("knowledge_base_not_found", "知识库不存在")
    if knowledge_base.status != "active":
        raise RecruitmentKnowledgeError("knowledge_base_inactive", "知识库已停用")

    document = db.scalar(
        select(RecruitmentKnowledgeDocument)
        .where(
            RecruitmentKnowledgeDocument.knowledge_base_id == knowledge_base.id,
            RecruitmentKnowledgeDocument.title == payload.title.strip(),
        )
        .options(selectinload(RecruitmentKnowledgeDocument.versions))
    )
    if document is not None:
        if document.status == "archived":
            raise RecruitmentKnowledgeError("document_archived", "知识文档已归档，不能新增版本")
        return knowledge_base, document

    document = RecruitmentKnowledgeDocument(
        knowledge_base=knowledge_base,
        title=payload.title.strip(),
        summary=payload.summary.strip() if payload.summary else None,
        category=payload.category,
        tags=_normalize_tags(payload.tags),
        visibility_scope=payload.visibility_scope,
        related_job_id=payload.related_job_id,
        current_version_number=None,
        **_actor_snapshot(actor),
    )
    db.add(document)
    db.flush()
    return knowledge_base, document


def _next_version_number(db: Session, document_id: uuid.UUID) -> int:
    current_max = db.scalar(
        select(func.max(RecruitmentKnowledgeDocumentVersion.version_number)).where(
            RecruitmentKnowledgeDocumentVersion.document_id == document_id
        )
    )
    return int(current_max or 0) + 1


def create_manual_knowledge_version(
    db: Session,
    payload: RecruitmentKnowledgeDocumentVersionCreateRequest,
    *,
    actor: User,
    source_type: str = "manual",
    source_filename: str | None = None,
    storage_key: str | None = None,
    mime_type: str | None = None,
    parser_name: str = "plain_text",
    parser_version: str = "v1",
    content_hash: str | None = None,
) -> tuple[
    RecruitmentKnowledgeDocument,
    RecruitmentKnowledgeDocumentVersion,
    list[RecruitmentKnowledgeChunk],
]:
    raw_text = normalize_resume_text(payload.raw_text)
    drafts = build_knowledge_chunks(raw_text)
    knowledge_base, document = _get_or_create_document(db, payload, actor)

    existing = db.scalar(
        select(RecruitmentKnowledgeDocumentVersion)
        .where(
            RecruitmentKnowledgeDocumentVersion.document_id == document.id,
            RecruitmentKnowledgeDocumentVersion.idempotency_key == payload.idempotency_key,
        )
        .options(selectinload(RecruitmentKnowledgeDocumentVersion.chunks))
    )
    if existing is not None:
        return document, existing, list(existing.chunks)

    for version in document.versions:
        if version.status == "published":
            version.status = "retired"

    version_number = _next_version_number(db, document.id)
    version = RecruitmentKnowledgeDocumentVersion(
        document=document,
        version_number=version_number,
        status="published",
        idempotency_key=payload.idempotency_key,
        source_type=source_type,
        source_filename=source_filename,
        storage_key=storage_key,
        mime_type=mime_type,
        content_hash=content_hash or _content_hash(raw_text),
        change_note=payload.change_note.strip(),
        raw_text=raw_text,
        parser_name=parser_name,
        parser_version=parser_version,
        chunk_count=len(drafts),
        **_actor_snapshot(actor),
        **_published_actor_snapshot(actor),
    )
    db.add(version)
    db.flush()

    chunks = _create_chunks(db, knowledge_base, document, version, drafts)
    document.summary = payload.summary.strip() if payload.summary else document.summary
    document.category = payload.category
    document.tags = _normalize_tags(payload.tags)
    document.visibility_scope = payload.visibility_scope
    document.related_job_id = payload.related_job_id
    document.current_version_number = version_number
    document.resource_version += 1
    db.flush()
    return document, version, chunks


def _create_chunks(
    db: Session,
    knowledge_base: RecruitmentKnowledgeBase,
    document: RecruitmentKnowledgeDocument,
    version: RecruitmentKnowledgeDocumentVersion,
    drafts: list[KnowledgeChunkDraft],
) -> list[RecruitmentKnowledgeChunk]:
    chunks: list[RecruitmentKnowledgeChunk] = []
    embedding_model = settings.embedding_model or "unconfigured"
    for draft in drafts:
        chunk = RecruitmentKnowledgeChunk(
            knowledge_base=knowledge_base,
            document=document,
            document_version=version,
            chunk_index=draft.chunk_index,
            chunk_text=draft.chunk_text,
            heading_path=draft.heading_path,
            source_locator=draft.source_locator,
            content_hash=draft.content_hash,
            embedding_model=embedding_model,
            embedding_dimension=settings.embedding_dimension,
            embedding_version=settings.embedding_version,
        )
        db.add(chunk)
        chunks.append(chunk)
    db.flush()
    return chunks


def _knowledge_storage_path(storage_root: Path, storage_key: str) -> Path:
    root = (storage_root / "recruitment-knowledge").resolve()
    path = (root / storage_key).resolve()
    if not path.is_relative_to(root):
        raise RecruitmentKnowledgeError("invalid_storage_key", "知识库文件路径非法")
    return path


async def parse_and_store_knowledge_upload(
    upload: UploadFile,
    *,
    storage_root: Path,
    max_size_mb: int,
) -> ParsedKnowledgeUpload:
    filename = Path(upload.filename or "knowledge.txt").name
    extension = Path(filename).suffix.lower()
    detected_type = SUPPORTED_KNOWLEDGE_EXTENSIONS.get(extension)
    if detected_type is None:
        raise RecruitmentKnowledgeError("unsupported_file_type", "仅支持 TXT、Markdown、PDF、DOCX")

    max_size = max_size_mb * 1024 * 1024
    content = await upload.read()
    if not content:
        raise RecruitmentKnowledgeError("empty_file", "知识文档不能为空")
    if len(content) > max_size:
        raise RecruitmentKnowledgeError("file_too_large", f"知识文档不能超过 {max_size_mb} MB")

    storage_key = f"{uuid.uuid4().hex}{extension}"
    path = _knowledge_storage_path(storage_root, storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    try:
        if detected_type in {"text", "markdown"}:
            try:
                raw_text = content.decode("utf-8")
            except UnicodeDecodeError:
                raw_text = content.decode("gb18030")
            parser_name = detected_type
        else:
            parsed = parse_resume_file(path, detected_type)
            raw_text = "\n\n".join(segment.normalized_text for segment in parsed.segments)
            parser_name = parsed.extraction_method
    except (UnicodeDecodeError, ResumeParseError) as error:
        path.unlink(missing_ok=True)
        if isinstance(error, ResumeParseError):
            raise RecruitmentKnowledgeError(error.code, error.message) from error
        raise RecruitmentKnowledgeError("invalid_text_encoding", "文本文件编码无法识别") from error

    normalized = normalize_resume_text(raw_text)
    if not normalized:
        path.unlink(missing_ok=True)
        raise RecruitmentKnowledgeError("empty_text", "知识文档未包含有效文本")

    return ParsedKnowledgeUpload(
        raw_text=normalized,
        parser_name=parser_name,
        parser_version="v1",
        storage_key=storage_key,
        source_filename=filename,
        mime_type=upload.content_type,
        content_hash=_content_hash(content),
    )


async def index_recruitment_knowledge_version(
    version_id: uuid.UUID,
    *,
    task_id: str | None = None,
    force: bool = False,
    session_factory: SessionFactory = SessionLocal,
    embedding_client: EmbeddingClient | None = None,
) -> dict[str, Any]:
    client = embedding_client or get_embedding_client()
    operation_id = task_id or uuid.uuid4().hex

    with session_factory() as db:
        version = db.get(RecruitmentKnowledgeDocumentVersion, version_id)
        if version is None:
            return {"status": "missing", "version_id": str(version_id)}
        chunks = list(
            db.scalars(
                select(RecruitmentKnowledgeChunk)
                .where(RecruitmentKnowledgeChunk.document_version_id == version.id)
                .order_by(RecruitmentKnowledgeChunk.chunk_index)
            )
        )
        if not chunks:
            return {"status": "empty", "version_id": str(version.id), "chunk_count": 0}
        if not force and any(chunk.status == "processing" for chunk in chunks):
            return {
                "status": "processing",
                "version_id": str(version.id),
                "chunk_count": len(chunks),
            }
        if not force and all(
            chunk.status == "completed"
            and chunk.embedding
            and chunk.embedding_model == client.model
            and chunk.embedding_version == client.version
            and chunk.embedding_dimension == client.dimension
            for chunk in chunks
        ):
            return {
                "status": "completed",
                "version_id": str(version.id),
                "chunk_count": len(chunks),
                "skipped": True,
            }
        for chunk in chunks:
            chunk.status = "processing"
            chunk.task_id = operation_id
            chunk.attempt_count = (chunk.attempt_count or 0) + 1
            chunk.embedding_model = client.model
            chunk.embedding_dimension = client.dimension
            chunk.embedding_version = client.version
            chunk.embedding = None
            chunk.failure_code = None
            chunk.failure_message = None
            chunk.embedded_at = None
        db.commit()
        prepared = [(chunk.id, chunk.chunk_text) for chunk in chunks]

    try:
        vectors: list[list[float]] = []
        for start in range(0, len(prepared), client.batch_size):
            texts = [item[1] for item in prepared[start : start + client.batch_size]]
            vectors.extend(await client.embed(texts))
        if len(vectors) != len(prepared):
            raise EmbeddingResponseValidationError("Embedding 响应数量不正确")
        if any(len(vector) != client.dimension for vector in vectors):
            raise EmbeddingResponseValidationError("Embedding 向量维度不正确")
    except (
        EmbeddingConfigurationError,
        EmbeddingRequestTimeout,
        EmbeddingResponseValidationError,
        EmbeddingUpstreamError,
    ) as error:
        return _mark_knowledge_chunks_failed(
            [item[0] for item in prepared], operation_id, error, session_factory
        )

    with session_factory() as db:
        owned_chunks = list(
            db.scalars(
                select(RecruitmentKnowledgeChunk).where(
                    RecruitmentKnowledgeChunk.id.in_([item[0] for item in prepared]),
                    RecruitmentKnowledgeChunk.task_id == operation_id,
                )
            )
        )
        if len(owned_chunks) != len(prepared):
            return {"status": "superseded", "version_id": str(version_id), "chunk_count": 0}
        chunk_by_id = {chunk.id: chunk for chunk in owned_chunks}
        embedded_at = datetime.now(UTC)
        for (chunk_id, _), vector in zip(prepared, vectors, strict=True):
            chunk = chunk_by_id[chunk_id]
            chunk.embedding = vector
            chunk.status = "completed"
            chunk.failure_code = None
            chunk.failure_message = None
            chunk.embedded_at = embedded_at
        db.commit()
    return {
        "status": "completed",
        "version_id": str(version_id),
        "chunk_count": len(prepared),
        "embedding_model": client.model,
        "embedding_version": client.version,
    }


def _mark_knowledge_chunks_failed(
    chunk_ids: list[uuid.UUID],
    operation_id: str,
    error: Exception,
    session_factory: SessionFactory,
) -> dict[str, Any]:
    failure_code, failure_message = _failure_details(error)
    with session_factory() as db:
        chunks = list(
            db.scalars(
                select(RecruitmentKnowledgeChunk).where(
                    RecruitmentKnowledgeChunk.id.in_(chunk_ids),
                    RecruitmentKnowledgeChunk.task_id == operation_id,
                )
            )
        )
        for chunk in chunks:
            chunk.status = "failed"
            chunk.embedding = None
            chunk.failure_code = failure_code
            chunk.failure_message = failure_message
            chunk.embedded_at = None
        db.commit()
    return {
        "status": "failed",
        "code": failure_code,
        "message": failure_message,
        "chunk_count": len(chunks),
    }


def _failure_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, EmbeddingConfigurationError):
        return "embedding_not_configured", str(error)
    if isinstance(error, EmbeddingRequestTimeout):
        return "embedding_timeout", str(error)
    if isinstance(error, EmbeddingResponseValidationError):
        return "embedding_invalid_response", str(error)
    if isinstance(error, EmbeddingUpstreamError):
        return "embedding_upstream_failed", str(error)
    return "embedding_failed", "企业招聘知识库索引失败，请稍后重试"
