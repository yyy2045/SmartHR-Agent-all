import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import SessionLocal
from app.models import ResumeDocument, ResumeRedaction, ResumeTextSegment, ScreeningBatch
from app.services.batch_status import refresh_batch_status
from app.services.candidate_duplicates import detect_candidate_duplicates
from app.services.candidate_identity import sync_candidate_identity
from app.services.file_storage import resolve_private_file
from app.services.resume_parser import ParseResult, ResumeParseError, parse_resume_file
from app.services.resume_redactor import RedactionResult, redact_resume_segments

logger = logging.getLogger(__name__)
SessionFactory = Callable[[], Session]
Parser = Callable[[Path, str], ParseResult]


@dataclass(frozen=True)
class _RedactionInput:
    segment_key: str
    normalized_text: str


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
                "application_id": (
                    str(document.application_id) if document.application_id else ""
                ),
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
        document.redacted_at = None
        document.redaction_count = 0
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

    try:
        redaction_result: RedactionResult = redact_resume_segments(
            f"CAND-{document_id.hex[:12].upper()}",
            [
                _RedactionInput(
                    segment_key=f"SEG-{index:04d}",
                    normalized_text=segment.normalized_text,
                )
                for index, segment in enumerate(result.segments, start=1)
            ],
        )
    except Exception:
        logger.exception("简历脱敏出现未预期错误，document_id=%s", document_id)
        return _mark_failed(
            document_id,
            code="redaction_failed",
            message="简历脱敏失败，请稍后重试",
            session_factory=session_factory,
        )

    with session_factory() as db:
        document = _load_document(db, document_id)
        if document is None:
            return {"status": "missing", "document_id": str(document_id)}
        document.text_segments.clear()
        db.flush()
        stored_segments: list[ResumeTextSegment] = []
        for index, (segment, redacted_segment) in enumerate(
            zip(result.segments, redaction_result.segments, strict=True),
            start=1,
        ):
            stored_segment = ResumeTextSegment(
                segment_key=f"SEG-{index:04d}",
                source_type=segment.source_type,
                source_index=segment.source_index,
                page_number=segment.page_number,
                paragraph_index=segment.paragraph_index,
                raw_text=segment.raw_text,
                normalized_text=segment.normalized_text,
                redacted_text=redacted_segment.redacted_text,
                ocr_confidence=segment.ocr_confidence,
                sort_order=index - 1,
            )
            stored_segment.redactions = [
                ResumeRedaction(
                    entity_type=match.entity_type,
                    original_text=match.original_text,
                    replacement_text=match.replacement_text,
                    start_offset=match.start_offset,
                    end_offset=match.end_offset,
                )
                for match in redacted_segment.matches
            ]
            stored_segments.append(stored_segment)
        document.text_segments = stored_segments
        document.extraction_method = result.extraction_method
        document.segment_count = len(result.segments)
        document.text_character_count = sum(
            len(segment.normalized_text) for segment in result.segments
        )
        document.redaction_count = redaction_result.redaction_count
        sync_candidate_identity(document.candidate, redaction_result)
        detect_candidate_duplicates(db, document=document)
        document.status = "completed"
        document.failure_code = None
        document.failure_message = None
        document.parsed_at = datetime.now(UTC)
        document.redacted_at = document.parsed_at
        refresh_batch_status(document.batch)
        db.commit()
        segment_count = document.segment_count
        application_id = document.application_id

    return {
        "status": "completed",
        "document_id": str(document_id),
        "application_id": str(application_id) if application_id else "",
        "segments": segment_count,
    }
