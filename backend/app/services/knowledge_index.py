from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import SessionLocal
from app.models import CandidateProfile, ResumeEmbeddingChunk
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingConfigurationError,
    EmbeddingRequestTimeout,
    EmbeddingResponseValidationError,
    EmbeddingUpstreamError,
    get_embedding_client,
)
from app.services.resume_redactor import redact_contact_information

logger = logging.getLogger(__name__)
SessionFactory = sessionmaker[Session]
MAX_CHUNK_TEXT_LENGTH = 4_000


@dataclass(frozen=True)
class KnowledgeChunkDraft:
    chunk_type: str
    chunk_index: int
    chunk_text: str
    source_segment_keys: list[str]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.chunk_text.encode("utf-8")).hexdigest()


def _clean_value(value: object) -> str:
    return redact_contact_information(str(value)).strip() if value is not None else ""


def _source_segment_keys(item: dict[str, object]) -> list[str]:
    evidence = item.get("evidence")
    if not isinstance(evidence, list):
        return []
    keys: list[str] = []
    for reference in evidence:
        if not isinstance(reference, dict):
            continue
        segment_key = _clean_value(reference.get("segment_key"))
        if segment_key and segment_key not in keys:
            keys.append(segment_key)
    return keys


def _format_chunk(
    title: str,
    item: dict[str, object],
    fields: tuple[tuple[str, str], ...],
) -> str:
    lines = [title]
    for field_name, label in fields:
        value = _clean_value(item.get(field_name))
        if value:
            lines.append(f"{label}：{value}")
    return "\n".join(lines)[:MAX_CHUNK_TEXT_LENGTH].strip()


CHUNK_FIELDS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "education": (
        "教育经历",
        (
            ("institution", "学校"),
            ("degree", "学历"),
            ("field_of_study", "专业"),
            ("start_date", "开始时间"),
            ("end_date", "结束时间"),
        ),
    ),
    "work_experience": (
        "工作经历",
        (
            ("company", "公司"),
            ("title", "职位"),
            ("start_date", "开始时间"),
            ("end_date", "结束时间"),
            ("summary", "工作内容"),
        ),
    ),
    "project": (
        "项目经历",
        (("name", "项目"), ("role", "角色"), ("summary", "项目内容")),
    ),
    "skill": (
        "技能",
        (("name", "技能名称"), ("level", "熟练程度")),
    ),
    "certification": (
        "证书",
        (("name", "证书名称"), ("issuer", "颁发机构"), ("obtained_at", "取得时间")),
    ),
    "language": (
        "语言能力",
        (("language", "语言"), ("level", "等级")),
    ),
}


PROFILE_COLLECTIONS = (
    ("education", "education"),
    ("work_experiences", "work_experience"),
    ("projects", "project"),
    ("skills", "skill"),
    ("certifications", "certification"),
    ("languages", "language"),
)


def build_profile_chunks(profile: CandidateProfile) -> list[KnowledgeChunkDraft]:
    detail_chunks: list[KnowledgeChunkDraft] = []
    for profile_field, chunk_type in PROFILE_COLLECTIONS:
        title, fields = CHUNK_FIELDS[chunk_type]
        items = getattr(profile, profile_field)
        for chunk_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            chunk_text = _format_chunk(title, item, fields)
            if chunk_text == title:
                continue
            detail_chunks.append(
                KnowledgeChunkDraft(
                    chunk_type=chunk_type,
                    chunk_index=chunk_index,
                    chunk_text=chunk_text,
                    source_segment_keys=_source_segment_keys(item),
                )
            )

    if not detail_chunks:
        return []
    summary_text = "候选人结构化摘要\n" + "\n\n".join(
        chunk.chunk_text for chunk in detail_chunks
    )
    summary_keys = list(
        dict.fromkeys(
            segment_key
            for chunk in detail_chunks
            for segment_key in chunk.source_segment_keys
        )
    )
    return [
        KnowledgeChunkDraft(
            chunk_type="summary",
            chunk_index=0,
            chunk_text=summary_text[:MAX_CHUNK_TEXT_LENGTH].strip(),
            source_segment_keys=summary_keys,
        ),
        *detail_chunks,
    ]


def _acquire_profile_lock(db: Session, profile_id: uuid.UUID) -> None:
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:profile_id, 0))"),
            {"profile_id": str(profile_id)},
        )


def _failure_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, EmbeddingConfigurationError):
        return "embedding_not_configured", str(error)
    if isinstance(error, EmbeddingRequestTimeout):
        return "embedding_timeout", str(error)
    if isinstance(error, EmbeddingResponseValidationError):
        return "embedding_invalid_response", str(error)
    if isinstance(error, EmbeddingUpstreamError):
        return "embedding_upstream_failed", str(error)
    return "embedding_failed", "简历知识库索引失败，请稍后重试"


def _mark_chunks_failed(
    chunk_ids: list[uuid.UUID],
    operation_id: str,
    error: Exception,
    session_factory: SessionFactory,
) -> dict[str, Any]:
    failure_code, failure_message = _failure_details(error)
    with session_factory() as db:
        chunks = list(
            db.scalars(
                select(ResumeEmbeddingChunk).where(
                    ResumeEmbeddingChunk.id.in_(chunk_ids),
                    ResumeEmbeddingChunk.task_id == operation_id,
                )
            )
        )
        if len(chunks) != len(chunk_ids):
            return {
                "status": "superseded",
                "chunk_count": 0,
            }
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
        "chunk_count": len(chunk_ids),
    }


async def index_candidate_profile(
    profile_id: uuid.UUID,
    *,
    task_id: str | None = None,
    force: bool = False,
    session_factory: SessionFactory = SessionLocal,
    embedding_client: EmbeddingClient | None = None,
) -> dict[str, Any]:
    client = embedding_client or get_embedding_client()
    operation_id = task_id or uuid.uuid4().hex

    with session_factory() as db:
        _acquire_profile_lock(db, profile_id)
        profile = db.get(CandidateProfile, profile_id)
        if profile is None:
            return {"status": "missing", "candidate_profile_id": str(profile_id)}
        drafts = build_profile_chunks(profile)
        if not drafts:
            return {
                "status": "empty",
                "candidate_profile_id": str(profile.id),
                "chunk_count": 0,
            }

        existing = list(
            db.scalars(
                select(ResumeEmbeddingChunk).where(
                    ResumeEmbeddingChunk.candidate_profile_id == profile.id,
                    ResumeEmbeddingChunk.embedding_model == client.model,
                    ResumeEmbeddingChunk.embedding_version == client.version,
                )
            )
        )
        if not force and any(
            chunk.status == "processing" and chunk.task_id != operation_id
            for chunk in existing
        ):
            return {
                "status": "processing",
                "candidate_profile_id": str(profile.id),
                "chunk_count": len(existing),
            }

        existing_map = {
            (chunk.chunk_type, chunk.chunk_index): chunk for chunk in existing
        }
        draft_keys = {(draft.chunk_type, draft.chunk_index) for draft in drafts}
        if not force and len(existing) == len(drafts) and all(
            (draft.chunk_type, draft.chunk_index) in existing_map
            and existing_map[(draft.chunk_type, draft.chunk_index)].content_hash
            == draft.content_hash
            and existing_map[(draft.chunk_type, draft.chunk_index)].status == "completed"
            for draft in drafts
        ):
            return {
                "status": "completed",
                "candidate_profile_id": str(profile.id),
                "chunk_count": len(existing),
                "skipped": True,
            }

        stale_ids = [
            chunk.id
            for chunk in existing
            if (chunk.chunk_type, chunk.chunk_index) not in draft_keys
        ]
        if stale_ids:
            db.execute(
                delete(ResumeEmbeddingChunk).where(
                    ResumeEmbeddingChunk.id.in_(stale_ids)
                )
            )

        prepared_chunks: list[ResumeEmbeddingChunk] = []
        for draft in drafts:
            key = (draft.chunk_type, draft.chunk_index)
            chunk = existing_map.get(key)
            if chunk is None:
                chunk = ResumeEmbeddingChunk(
                    document_id=profile.document_id,
                    candidate_profile_id=profile.id,
                    profile_version=profile.version_number,
                    chunk_type=draft.chunk_type,
                    chunk_index=draft.chunk_index,
                    chunk_text=draft.chunk_text,
                    source_segment_keys=draft.source_segment_keys,
                    content_hash=draft.content_hash,
                    embedding_model=client.model,
                    embedding_dimension=client.dimension,
                    embedding_version=client.version,
                )
                db.add(chunk)
            else:
                chunk.chunk_text = draft.chunk_text
                chunk.source_segment_keys = draft.source_segment_keys
                chunk.content_hash = draft.content_hash
                chunk.embedding_dimension = client.dimension
            chunk.status = "processing"
            chunk.task_id = operation_id
            chunk.attempt_count = (chunk.attempt_count or 0) + 1
            chunk.embedding = None
            chunk.failure_code = None
            chunk.failure_message = None
            chunk.embedded_at = None
            prepared_chunks.append(chunk)
        db.commit()
        prepared = [(chunk.id, chunk.chunk_text) for chunk in prepared_chunks]

    try:
        vectors: list[list[float]] = []
        for start in range(0, len(prepared), client.batch_size):
            texts = [item[1] for item in prepared[start : start + client.batch_size]]
            batch_vectors = await client.embed(texts)
            if len(batch_vectors) != len(texts):
                raise EmbeddingResponseValidationError("Embedding 响应数量不正确")
            vectors.extend(batch_vectors)
        if any(len(vector) != client.dimension for vector in vectors):
            raise EmbeddingResponseValidationError("Embedding 向量维度不正确")
    except (
        EmbeddingConfigurationError,
        EmbeddingRequestTimeout,
        EmbeddingResponseValidationError,
        EmbeddingUpstreamError,
    ) as error:
        return _mark_chunks_failed(
            [item[0] for item in prepared],
            operation_id,
            error,
            session_factory,
        )
    except Exception as error:
        logger.exception("简历知识库索引出现未预期错误，profile_id=%s", profile_id)
        return _mark_chunks_failed(
            [item[0] for item in prepared],
            operation_id,
            error,
            session_factory,
        )

    with session_factory() as db:
        owned_chunks = list(
            db.scalars(
                select(ResumeEmbeddingChunk).where(
                    ResumeEmbeddingChunk.id.in_([item[0] for item in prepared]),
                    ResumeEmbeddingChunk.task_id == operation_id,
                )
            )
        )
        if len(owned_chunks) != len(prepared):
            return {
                "status": "superseded",
                "candidate_profile_id": str(profile_id),
                "chunk_count": 0,
            }
        chunks = {chunk.id: chunk for chunk in owned_chunks}
        embedded_at = datetime.now(UTC)
        for (chunk_id, _), vector in zip(prepared, vectors, strict=True):
            chunk = chunks[chunk_id]
            chunk.embedding = vector
            chunk.status = "completed"
            chunk.failure_code = None
            chunk.failure_message = None
            chunk.embedded_at = embedded_at
        db.commit()
    return {
        "status": "completed",
        "candidate_profile_id": str(profile_id),
        "chunk_count": len(prepared),
        "embedding_model": client.model,
        "embedding_version": client.version,
    }
