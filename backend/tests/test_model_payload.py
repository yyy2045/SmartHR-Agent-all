import uuid
from datetime import UTC, datetime

import pytest

from app.models import ResumeDocument, ResumeTextSegment
from app.services.model_payload import ModelPayloadSecurityError, build_resume_model_payload


def make_document(redacted_text: str | None) -> ResumeDocument:
    document = ResumeDocument(
        id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        batch_id=uuid.uuid4(),
        original_filename="李雷的简历.pdf",
        status="completed",
        redacted_at=datetime.now(UTC),
    )
    document.text_segments = [
        ResumeTextSegment(
            segment_key="SEG-0001",
            source_type="pdf_page",
            source_index=1,
            page_number=1,
            raw_text="电话：13912345678",
            normalized_text="电话：13912345678",
            redacted_text=redacted_text,
            sort_order=0,
        )
    ]
    return document


def test_model_payload_excludes_filename_raw_text_and_image_data() -> None:
    payload = build_resume_model_payload(make_document("电话：[PHONE]"))

    assert payload == {
        "candidate_code": "CAND-111111112222",
        "segments": [{"segment_key": "SEG-0001", "text": "电话：[PHONE]"}],
    }
    serialized = str(payload)
    assert "李雷" not in serialized
    assert "13912345678" not in serialized
    assert "raw_text" not in serialized
    assert "image" not in serialized


def test_model_payload_rejects_missing_or_residual_redaction() -> None:
    with pytest.raises(ModelPayloadSecurityError, match="缺少脱敏文本"):
        build_resume_model_payload(make_document(None))

    with pytest.raises(ModelPayloadSecurityError, match="发现敏感信息"):
        build_resume_model_payload(make_document("电话：13912345678"))
