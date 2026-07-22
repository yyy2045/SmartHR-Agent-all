from dataclasses import dataclass

from app.services.resume_redactor import (
    contains_detectable_sensitive_data,
    redact_resume_segments,
)


@dataclass(frozen=True)
class Segment:
    segment_key: str
    normalized_text: str


def test_redacts_chinese_personal_information_and_preserves_avatar_marker() -> None:
    original = (
        "姓名：张伟\n"
        "电话：13800138000\n"
        "邮箱：zhang.wei@example.com\n"
        "身份证号：110105199001011234\n"
        "地址：北京市海淀区中关村大街1号3单元502室\n"
        "微信：zhangwei_88\n"
        "头像标识：avatar-001"
    )
    result = redact_resume_segments(
        "CAND-0001",
        [
            Segment("SEG-0001", original),
            Segment("SEG-0002", "张伟拥有 8 年 Python 开发经验。"),
        ],
    )

    assert [segment.segment_key for segment in result.segments] == ["SEG-0001", "SEG-0002"]
    combined = "\n".join(segment.redacted_text for segment in result.segments)
    for sensitive_value in (
        "张伟",
        "13800138000",
        "zhang.wei@example.com",
        "110105199001011234",
        "北京市海淀区中关村大街1号3单元502室",
        "zhangwei_88",
    ):
        assert sensitive_value not in combined
    assert "姓名：CAND-0001" in combined
    assert "[PHONE]" in combined
    assert "[EMAIL]" in combined
    assert "[ID]" in combined
    assert "[ADDRESS]" in combined
    assert "[SOCIAL]" in combined
    assert "头像标识：avatar-001" in combined
    assert {match.entity_type for segment in result.segments for match in segment.matches} == {
        "name",
        "phone",
        "email",
        "id_number",
        "address",
        "social_account",
    }
    assert not contains_detectable_sensitive_data(combined)


def test_redacts_english_personal_information() -> None:
    original = (
        "John Smith\n"
        "Phone: +1 (415) 555-2671\n"
        "Email: john.smith@example.org\n"
        "SSN: 123-45-6789\n"
        "Address: 1600 Amphitheatre Parkway, Unit 8\n"
        "LinkedIn: https://linkedin.com/in/john-smith"
    )
    result = redact_resume_segments("CAND-A1B2C3", [Segment("SEG-0001", original)])
    redacted = result.segments[0].redacted_text

    for sensitive_value in (
        "John Smith",
        "+1 (415) 555-2671",
        "john.smith@example.org",
        "123-45-6789",
        "1600 Amphitheatre Parkway, Unit 8",
        "https://linkedin.com/in/john-smith",
    ):
        assert sensitive_value not in redacted
    assert redacted.startswith("CAND-A1B2C3")
    assert not contains_detectable_sensitive_data(redacted)


def test_does_not_redact_non_sensitive_numbers_city_or_avatar_identifiers() -> None:
    text = (
        "个人简历\n"
        "2018 至 2024 年负责 Python 3.12 与 ISO 9001 项目。\n"
        "意向城市：上海\n"
        "头像：profile-photo.png\n"
        "头像标识：avatar_user_001"
    )
    result = redact_resume_segments("CAND-0002", [Segment("SEG-0001", text)])

    assert result.redaction_count == 0
    assert result.segments[0].redacted_text == text
    assert not contains_detectable_sensitive_data(text)
