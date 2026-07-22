from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.models import ResumeDocument
from app.services.resume_redactor import contains_detectable_sensitive_data


class ModelPayloadSecurityError(RuntimeError):
    pass


def build_resume_model_payload(document: ResumeDocument) -> dict[str, Any]:
    if document.status != "completed" or document.redacted_at is None:
        raise ModelPayloadSecurityError("简历尚未完成本地脱敏")

    segments = []
    original_values: set[str] = set()
    for segment in sorted(document.text_segments, key=lambda item: item.sort_order):
        if segment.redacted_text is None:
            raise ModelPayloadSecurityError(f"片段 {segment.segment_key} 缺少脱敏文本")
        segments.append(
            {
                "segment_key": segment.segment_key,
                "text": segment.redacted_text,
            }
        )
        original_values.update(
            redaction.original_text
            for redaction in segment.redactions
            if redaction.original_text
        )

    payload: dict[str, Any] = {
        "candidate_code": document.candidate_code,
        "segments": segments,
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    if any(value in serialized for value in original_values):
        raise ModelPayloadSecurityError("模型载荷仍包含已识别的原始敏感信息")
    if contains_detectable_sensitive_data("\n".join(item["text"] for item in segments)):
        raise ModelPayloadSecurityError("模型载荷通过发送前检查时发现敏感信息")
    return payload


def send_resume_model_payload(
    document: ResumeDocument,
    sender: Callable[[dict[str, Any]], Any],
) -> Any:
    return sender(build_resume_model_payload(document))
