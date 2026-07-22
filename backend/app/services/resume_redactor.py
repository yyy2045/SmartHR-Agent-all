from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

EntityType = Literal[
    "name",
    "phone",
    "email",
    "id_number",
    "address",
    "social_account",
]

REPLACEMENTS: dict[EntityType, str] = {
    "name": "",
    "phone": "[PHONE]",
    "email": "[EMAIL]",
    "id_number": "[ID]",
    "address": "[ADDRESS]",
    "social_account": "[SOCIAL]",
}

EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I)
CN_ID_PATTERN = re.compile(r"(?<!\d)(?:\d{17}[0-9Xx]|\d{15})(?!\d)")
SSN_PATTERN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
PHONE_PATTERN = re.compile(r"(?<![\w])(?:\+?\d[\d()\s.-]{5,}\d)(?![\w])")

LABELED_NAME_PATTERN = re.compile(
    r"(?:姓名|候选人姓名|候选人|name|candidate\s+name)\s*[:：]\s*"
    r"(?P<value>[\u4e00-\u9fff·]{2,10}|[A-Za-z][A-Za-z.'’-]*(?:\s+[A-Za-z][A-Za-z.'’-]*){1,3})",
    re.I,
)
LABELED_ID_PATTERN = re.compile(
    r"(?:身份证(?:号|号码)?|证件(?:号|号码)?|护照(?:号|号码)?|passport(?:\s*(?:no|number))?|"
    r"identity\s*(?:no|number)|id\s*(?:no|number))\s*[:：]\s*"
    r"(?P<value>[A-Z0-9][A-Z0-9 -]{5,24})",
    re.I,
)
LABELED_ADDRESS_PATTERN = re.compile(
    r"(?:家庭住址|现居住?地|通讯地址|联系地址|详细地址|住址|home\s+address|"
    r"mailing\s+address|address)\s*[:：]\s*(?P<value>[^\r\n|；;]{4,120})",
    re.I,
)
LABELED_SOCIAL_PATTERN = re.compile(
    r"(?:微信(?:号)?|wechat|qq(?:号)?|linkedin|github|telegram|skype|whatsapp|"
    r"社交账号|微博|小红书)\s*[:：]\s*(?P<value>[^\s|；;，,]{2,120})",
    re.I,
)
CN_PRECISE_ADDRESS_PATTERN = re.compile(
    r"(?:(?:[\u4e00-\u9fff]{2,10})(?:省|自治区|市))?"
    r"(?:[\u4e00-\u9fff]{2,10})(?:市|区|县|旗)"
    r"[\u4e00-\u9fffA-Za-z0-9]{1,40}(?:路|街|道|巷|弄|小区|大厦|公寓|村)"
    r"[\u4e00-\u9fffA-Za-z0-9-]{0,30}\d+(?:号|栋|幢|单元|室)"
)
EN_PRECISE_ADDRESS_PATTERN = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s+){0,6}"
    r"(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|boulevard|blvd|"
    r"court|ct|parkway|pkwy|way)\b(?:[\s,]+(?:apt|suite|unit|#)\s*[A-Za-z0-9-]+)?",
    re.I,
)

HEADER_EXCLUSIONS = {
    "个人简历",
    "求职简历",
    "简历",
    "resume",
    "curriculum vitae",
    "professional summary",
    "个人简介",
    "基本信息",
}


class SegmentLike(Protocol):
    segment_key: str
    normalized_text: str


@dataclass(frozen=True)
class RedactionMatch:
    entity_type: EntityType
    original_text: str
    replacement_text: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class RedactedSegment:
    segment_key: str
    redacted_text: str
    matches: tuple[RedactionMatch, ...]


@dataclass(frozen=True)
class RedactionResult:
    candidate_code: str
    segments: tuple[RedactedSegment, ...]

    @property
    def redaction_count(self) -> int:
        return sum(len(segment.matches) for segment in self.segments)


@dataclass(frozen=True)
class _CandidateMatch:
    entity_type: EntityType
    start: int
    end: int
    replacement: str
    priority: int


def _is_placeholder(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("[") or stripped.upper().startswith("CAND-")


def _discover_names(texts: Sequence[str]) -> tuple[str, ...]:
    names: list[str] = []
    for text in texts:
        for match in LABELED_NAME_PATTERN.finditer(text):
            value = match.group("value").strip()
            if not _is_placeholder(value):
                names.append(value)

    header_lines: list[str] = []
    for text in texts[:3]:
        header_lines.extend(line.strip() for line in text.splitlines() if line.strip())
        if len(header_lines) >= 5:
            break
    for line in header_lines[:5]:
        lowered = line.casefold()
        if lowered in HEADER_EXCLUSIONS or ":" in line or "：" in line or len(line) > 50:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff·]{2,4}", line):
            names.append(line)
            break
        if re.fullmatch(
            r"[A-Z][A-Za-z.'’-]*(?:\s+[A-Z][A-Za-z.'’-]*){1,3}",
            line,
        ):
            names.append(line)
            break

    return tuple(dict.fromkeys(names))


def _append_pattern_matches(
    matches: list[_CandidateMatch],
    text: str,
    pattern: re.Pattern[str],
    entity_type: EntityType,
    replacement: str,
    priority: int,
    *,
    group: str | None = None,
) -> None:
    for regex_match in pattern.finditer(text):
        start, end = regex_match.span(group) if group else regex_match.span()
        value = text[start:end].strip()
        if not value or _is_placeholder(value):
            continue
        leading = len(text[start:end]) - len(text[start:end].lstrip())
        trailing = len(text[start:end]) - len(text[start:end].rstrip())
        start += leading
        end -= trailing
        if start < end:
            matches.append(_CandidateMatch(entity_type, start, end, replacement, priority))


def _phone_matches(text: str) -> list[_CandidateMatch]:
    matches: list[_CandidateMatch] = []
    for match in PHONE_PATTERN.finditer(text):
        value = match.group()
        digit_count = sum(character.isdigit() for character in value)
        if not 7 <= digit_count <= 15:
            continue
        compact = re.sub(r"\D", "", value)
        if len(compact) == 8 and compact.startswith(("19", "20")):
            continue
        matches.append(_CandidateMatch("phone", match.start(), match.end(), "[PHONE]", 30))
    return matches


def _name_matches(text: str, names: Sequence[str], candidate_code: str) -> list[_CandidateMatch]:
    matches: list[_CandidateMatch] = []
    for name in names:
        escaped = re.escape(name)
        if name.isascii():
            pattern = re.compile(rf"(?<![A-Za-z]){escaped}(?![A-Za-z])", re.I)
        else:
            pattern = re.compile(escaped)
        for match in pattern.finditer(text):
            matches.append(
                _CandidateMatch("name", match.start(), match.end(), candidate_code, 10)
            )
    return matches


def _select_non_overlapping(matches: Sequence[_CandidateMatch]) -> tuple[_CandidateMatch, ...]:
    selected: list[_CandidateMatch] = []
    for match in sorted(matches, key=lambda item: (item.start, item.priority, -item.end)):
        if any(match.start < existing.end and match.end > existing.start for existing in selected):
            continue
        selected.append(match)
    return tuple(sorted(selected, key=lambda item: item.start))


def _find_matches(
    text: str,
    names: Sequence[str],
    candidate_code: str,
) -> tuple[_CandidateMatch, ...]:
    matches = _name_matches(text, names, candidate_code)
    _append_pattern_matches(matches, text, EMAIL_PATTERN, "email", "[EMAIL]", 20)
    _append_pattern_matches(matches, text, CN_ID_PATTERN, "id_number", "[ID]", 15)
    _append_pattern_matches(matches, text, SSN_PATTERN, "id_number", "[ID]", 15)
    _append_pattern_matches(
        matches,
        text,
        LABELED_ID_PATTERN,
        "id_number",
        "[ID]",
        15,
        group="value",
    )
    matches.extend(_phone_matches(text))
    _append_pattern_matches(
        matches,
        text,
        LABELED_ADDRESS_PATTERN,
        "address",
        "[ADDRESS]",
        40,
        group="value",
    )
    _append_pattern_matches(matches, text, CN_PRECISE_ADDRESS_PATTERN, "address", "[ADDRESS]", 40)
    _append_pattern_matches(matches, text, EN_PRECISE_ADDRESS_PATTERN, "address", "[ADDRESS]", 40)
    _append_pattern_matches(
        matches,
        text,
        LABELED_SOCIAL_PATTERN,
        "social_account",
        "[SOCIAL]",
        25,
        group="value",
    )
    return _select_non_overlapping(matches)


def redact_resume_segments(
    candidate_code: str,
    segments: Sequence[SegmentLike],
) -> RedactionResult:
    texts = [segment.normalized_text for segment in segments]
    names = _discover_names(texts)
    redacted_segments: list[RedactedSegment] = []

    for segment in segments:
        text = segment.normalized_text
        selected = _find_matches(text, names, candidate_code)
        result_parts: list[str] = []
        cursor = 0
        public_matches: list[RedactionMatch] = []
        for match in selected:
            result_parts.append(text[cursor : match.start])
            result_parts.append(match.replacement)
            public_matches.append(
                RedactionMatch(
                    entity_type=match.entity_type,
                    original_text=text[match.start : match.end],
                    replacement_text=match.replacement,
                    start_offset=match.start,
                    end_offset=match.end,
                )
            )
            cursor = match.end
        result_parts.append(text[cursor:])
        redacted_segments.append(
            RedactedSegment(
                segment_key=segment.segment_key,
                redacted_text="".join(result_parts),
                matches=tuple(public_matches),
            )
        )

    return RedactionResult(candidate_code=candidate_code, segments=tuple(redacted_segments))


def contains_detectable_sensitive_data(text: str) -> bool:
    names = _discover_names([text])
    return bool(_find_matches(text, names, "CAND-REDACTED"))
