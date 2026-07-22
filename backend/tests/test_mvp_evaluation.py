from collections import Counter

import pytest

from app.evaluation import load_dataset, run_mvp_evaluation


def test_mvp_dataset_has_fixed_required_coverage() -> None:
    dataset = load_dataset()

    assert dataset.version == "mvp-v1"
    assert len(dataset.jobs) == 3
    assert len(dataset.resumes) == 30
    assert Counter(item.job_key for item in dataset.resumes) == {
        "backend": 10,
        "data": 10,
        "product": 10,
    }
    assert Counter(item.language for item in dataset.resumes) == {
        "zh-CN": 15,
        "en-US": 15,
    }
    assert Counter(item.format for item in dataset.resumes) == {
        "pdf": 6,
        "docx": 6,
        "scanned_pdf": 6,
        "jpg": 6,
        "png": 6,
    }
    assert set(item.scenario for item in dataset.resumes) == {
        "high_match",
        "low_match",
        "hard_failure",
        "missing_information",
        "ambiguous_context",
    }
    assert Counter(item.expected_group for item in dataset.resumes) == {
        "passed": 12,
        "low_match": 12,
        "auto_rejected": 6,
    }


@pytest.mark.asyncio
async def test_mvp_evaluation_generates_and_validates_complete_fixed_dataset() -> None:
    report = await run_mvp_evaluation()

    assert report.passed, report.issues
    assert report.job_count == 3
    assert report.resume_count == 30
    assert report.generated_file_count == 30
    assert report.completed_analysis_count == 30
    assert report.payload_leak_count == 0
    assert report.actual_group_counts == report.expected_group_counts
    assert report.redaction_types == [
        "address",
        "email",
        "id_number",
        "name",
        "phone",
        "social_account",
    ]
    assert report.issues == []
