from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from app.models import CandidateProfile, JobCriteriaVersion, ResumeDocument
from app.services.resume_redactor import contains_detectable_sensitive_data


class ModelPayloadSecurityError(RuntimeError):
    pass


def _candidate_profile_payload(profile: CandidateProfile) -> dict[str, Any]:
    return {
        "education": profile.education,
        "work_experiences": profile.work_experiences,
        "projects": profile.projects,
        "skills": profile.skills,
        "certifications": profile.certifications,
        "languages": profile.languages,
    }


def validate_candidate_profile_payload(
    document: ResumeDocument,
    profile_payload: dict[str, Any],
) -> None:
    serialized = json.dumps(profile_payload, ensure_ascii=False)
    original_values = {
        redaction.original_text
        for segment in document.text_segments
        for redaction in segment.redactions
        if redaction.original_text
    }
    if any(value in serialized for value in original_values):
        raise ModelPayloadSecurityError("修正后的候选人资料包含原始敏感信息")
    if contains_detectable_sensitive_data(serialized):
        raise ModelPayloadSecurityError("修正后的候选人资料包含可识别的敏感信息")


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


def build_resume_analysis_payload(
    document: ResumeDocument,
    criteria_version: JobCriteriaVersion,
    candidate_profile: CandidateProfile | None = None,
) -> dict[str, Any]:
    resume_payload = build_resume_model_payload(document)
    payload = {
        **resume_payload,
        "criteria": {
            "criteria_version_id": str(criteria_version.id),
            "pass_threshold": criteria_version.pass_threshold,
            "hard_requirements": [
                {
                    "requirement_id": str(requirement.id),
                    "requirement_type": requirement.requirement_type,
                    "title": requirement.title,
                    "description": requirement.description,
                    "expected_value": requirement.expected_value,
                    "auto_reject": requirement.auto_reject,
                }
                for requirement in sorted(
                    criteria_version.hard_requirements,
                    key=lambda item: item.sort_order,
                )
            ],
            "scoring_dimensions": [
                {
                    "dimension_id": str(dimension.id),
                    "name": dimension.name,
                    "description": dimension.description,
                }
                for dimension in sorted(
                    criteria_version.scoring_dimensions,
                    key=lambda item: item.sort_order,
                )
            ],
        },
    }
    if candidate_profile is not None:
        profile_payload = _candidate_profile_payload(candidate_profile)
        validate_candidate_profile_payload(document, profile_payload)
        payload["candidate_profile_override"] = profile_payload
    return payload
