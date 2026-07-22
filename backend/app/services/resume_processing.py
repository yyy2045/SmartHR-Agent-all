import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import SessionLocal
from app.models import ResumeDocument, ResumeTextSegment, ScreeningBatch
from app.services.batch_status import refresh_batch_status
from app.services.file_storage import resolve_private_file
from app.services.resume_parser import ParseResult, ResumeParseError, parse_resume_file

logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]
Parser = Callable[[Path, str], ParseResult]


def _load_document(db: Session, document_id: uuid.UUID) -> ResumeDocument | None:
    return db.scalar(
        select(ResumeDocument)
        .where(ResumeDocument.id == document_id)
        .options(
            selectinload(ResumeDocument.text_segments),
            selectinload(ResumeDocument.batch).selectinload(ScreeningBatch.documents),
        )
    )


def _mark_failed(
    document_id: uuid.UUID,
    *,
    code: str,
    message: str,
    session_factory: SessionFactory,
) -> dict[str, str]:
    with session_factory() as db:
        document = _load_document(db, document_id)
        if document is None:
            return {"status": "missing", "document_id": str(document_id)}
        document.status = "failed"
        document.failure_code = code
        document.failure_message = message
        refresh_batch_status(document.batch)
        db.commit()
    return {"status": "failed", "document_id": str(document_id), "code": code}


def process_resume_document(
    document_id: uuid.UUID,
    *,
    task_id: str | None = None,
    session_factory: SessionFactory = SessionLocal,
    parser: Parser = parse_resume_file,
) -> dict[str, str | int]:
    with session_factory() as db:
        document = _load_document(db, document_id)
        if document is None:
            return {"status": "missing", "document_id": str(document_id)}
        if document.status == "completed":
            return {
                "status": "completed",
                "document_id": str(document_id),
                "segments": document.segment_count,
            }
        if not document.storage_key:
            document.status = "failed"
            document.failure_code = "file_unavailable"
            document.failure_message = "原始文件不可用，无法开始解析"
            refresh_batch_status(document.batch)
            db.commit()
            return {
                "status": "failed",
                "document_id": str(document_id),
                "code": "file_unavailable",
            }

        document.status = "processing"
        document.processing_attempt_count += 1
        document.processing_started_at = datetime.now(UTC)
        document.parsed_at = None
        if task_id:
            document.task_id = task_id
        document.failure_code = None
        document.failure_message = None
        detected_type = document.detected_type
        storage_key = document.storage_key
        refresh_batch_status(document.batch)
        db.commit()

    try:
        path = resolve_private_file(settings.file_storage_root, storage_key)
        if not path.is_file():
            raise ResumeParseError("file_unavailable", "原始文件不存在")
        result = parser(path, detected_type)
    except ResumeParseError as error:
        return _mark_failed(
            document_id,
            code=error.code,
            message=error.message,
            session_factory=session_factory,
        )
    except Exception:
        logger.exception("简历解析出现未预期错误，document_id=%s", document_id)
        return _mark_failed(
            document_id,
            code="parse_failed",
            message="简历解析失败，请稍后重试",
            session_factory=session_factory,
        )

    with session_factory() as db:
        document = _load_document(db, document_id)
        if document is None:
            return {"status": "missing", "document_id": str(document_id)}
        document.text_segments = [
            ResumeTextSegment(
                segment_key=f"SEG-{index:04d}",
                source_type=segment.source_type,
                source_index=segment.source_index,
                page_number=segment.page_number,
                paragraph_index=segment.paragraph_index,
                raw_text=segment.raw_text,
                normalized_text=segment.normalized_text,
                ocr_confidence=segment.ocr_confidence,
                sort_order=index - 1,
            )
            for index, segment in enumerate(result.segments, start=1)
        ]
        document.extraction_method = result.extraction_method
        document.segment_count = len(result.segments)
        document.text_character_count = sum(
            len(segment.normalized_text) for segment in result.segments
        )
        document.status = "completed"
        document.failure_code = None
        document.failure_message = None
        document.parsed_at = datetime.now(UTC)
        refresh_batch_status(document.batch)
        db.commit()
        segment_count = document.segment_count

    return {
        "status": "completed",
        "document_id": str(document_id),
        "segments": segment_count,
    }
