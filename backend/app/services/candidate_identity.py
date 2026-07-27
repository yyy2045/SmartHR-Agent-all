from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from app.models import Candidate
from app.services.resume_redactor import RedactionResult


def _values_for(result: RedactionResult, entity_type: str) -> list[str]:
    return [
        match.original_text.strip()
        for segment in result.segments
        for match in segment.matches
        if match.entity_type == entity_type and match.original_text.strip()
    ]


def _preferred_phone(values: Iterable[str]) -> str | None:
    candidates = [value for value in dict.fromkeys(values) if _is_contact_phone(value)]
    if not candidates:
        return None

    def priority(value: str) -> tuple[int, int]:
        digits = "".join(character for character in value if character.isdigit())
        is_mobile = len(digits) == 11 and digits.startswith("1") and digits[1] in "3456789"
        return (0 if is_mobile else 1, len(value))

    return min(candidates, key=priority)


def _is_contact_phone(value: str) -> bool:
    phone = value.strip()
    digits = re.sub(r"\D", "", phone)
    if re.fullmatch(r"1[3-9]\d{9}", digits):
        return True
    if phone.startswith("+") and 8 <= len(digits) <= 15:
        return True
    return re.fullmatch(r"0\d{2,3}[- ]?\d{7,8}", phone) is not None


def normalize_candidate_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).casefold()
    compact = "".join(character for character in normalized if character.isalnum())
    return compact or None


def normalize_candidate_phone(value: str | None) -> str | None:
    if value is None or not _is_contact_phone(value):
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def normalize_candidate_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return normalized or None


def sync_candidate_identity(candidate: Candidate | None, result: RedactionResult) -> None:
    if candidate is None:
        return
    names = _values_for(result, "name")
    emails = _values_for(result, "email")
    candidate.full_name = names[0] if names else None
    candidate.phone = _preferred_phone(_values_for(result, "phone"))
    candidate.email = emails[0].lower() if emails else None
    candidate.full_name_normalized = normalize_candidate_name(candidate.full_name)
    candidate.phone_normalized = normalize_candidate_phone(candidate.phone)
    candidate.email_normalized = normalize_candidate_email(candidate.email)
