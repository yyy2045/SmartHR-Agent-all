import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AiEvaluationDataset,
    AiEvaluationErrorCase,
    AiEvaluationResult,
    AiEvaluationRun,
    AiEvaluationSample,
    User,
)
from app.services.security import hash_password


@pytest.fixture
def ai_evaluation_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _seed_dataset(db: Session) -> AiEvaluationDataset:
    admin = User(
        username=f"admin-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("correct-password"),
        display_name="管理员",
    )
    dataset = AiEvaluationDataset(
        code=f"resume-basic-{uuid.uuid4().hex[:8]}",
        name="简历评分基础评测集",
        scenario="resume_analysis",
        description="覆盖推荐、保留和淘汰三类结论。",
        created_by=admin,
    )
    db.add(dataset)
    db.commit()
    return dataset


def _seed_sample(db: Session, dataset: AiEvaluationDataset, case_key: str) -> AiEvaluationSample:
    sample = AiEvaluationSample(
        dataset=dataset,
        case_key=case_key,
        title=f"样本 {case_key}",
        scenario=dataset.scenario,
        difficulty="medium",
        input_payload={
            "job": {"title": "后端工程师"},
            "resume": {"text": "5 年 Python 与 FastAPI 经验"},
        },
        expected_output={"recommendation": "recommend"},
        expected_recommendation="recommend",
        expected_evidence_keywords=["Python", "FastAPI"],
        tags=["backend", "python"],
    )
    db.add(sample)
    db.commit()
    return sample


def _seed_run_and_result(
    db: Session,
) -> tuple[AiEvaluationDataset, AiEvaluationRun, AiEvaluationResult]:
    dataset = _seed_dataset(db)
    sample = _seed_sample(db, dataset, "resume-001")
    run = AiEvaluationRun(
        dataset=dataset,
        name="Prompt v1 评测",
        scenario=dataset.scenario,
        status="succeeded",
        model_name="gpt-test",
        prompt_version="resume-analysis-v1",
        run_config={"mode": "deterministic"},
        metrics_summary={"pass_rate": 1.0},
        total_samples=1,
        completed_samples=1,
        passed_samples=1,
        failed_samples=0,
        average_score=1.0,
        completed_at=datetime.now(UTC),
    )
    result = AiEvaluationResult(
        run=run,
        sample=sample,
        status="passed",
        score=1.0,
        actual_output={"recommendation": "recommend", "evidence": ["Python"]},
        expected_snapshot=sample.expected_output,
        error_types=[],
        evidence_coverage_score=1.0,
        format_valid=True,
        recommendation_matched=True,
    )
    db.add(result)
    db.commit()
    return dataset, run, result


def test_ai_evaluation_dataset_orders_samples_and_enforces_case_key(
    ai_evaluation_session_factory: sessionmaker[Session],
) -> None:
    with ai_evaluation_session_factory() as db:
        dataset = _seed_dataset(db)
        _seed_sample(db, dataset, "resume-002")
        _seed_sample(db, dataset, "resume-001")
        db.expire_all()
        stored = db.scalars(select(AiEvaluationDataset)).one()

        case_keys = [sample.case_key for sample in stored.samples]

    assert case_keys == ["resume-001", "resume-002"]

    with ai_evaluation_session_factory() as db:
        dataset = _seed_dataset(db)
        _seed_sample(db, dataset, "resume-001")
        duplicate = AiEvaluationSample(
            dataset=dataset,
            case_key="resume-001",
            title="重复样本",
            scenario=dataset.scenario,
            input_payload={},
            expected_output={},
            expected_evidence_keywords=[],
            tags=[],
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


def test_ai_evaluation_run_requires_completed_at_for_final_status(
    ai_evaluation_session_factory: sessionmaker[Session],
) -> None:
    with ai_evaluation_session_factory() as db:
        dataset = _seed_dataset(db)
        run = AiEvaluationRun(
            dataset=dataset,
            name="缺失完成时间",
            scenario=dataset.scenario,
            status="succeeded",
            run_config={},
            metrics_summary={},
        )
        db.add(run)

        with pytest.raises(IntegrityError):
            db.commit()


def test_ai_evaluation_result_enforces_unique_sample_and_score_range(
    ai_evaluation_session_factory: sessionmaker[Session],
) -> None:
    with ai_evaluation_session_factory() as db:
        dataset, run, result = _seed_run_and_result(db)
        duplicate = AiEvaluationResult(
            run=run,
            sample=result.sample,
            status="failed",
            score=0.5,
            actual_output={},
            expected_snapshot={},
            error_types=["evidence_missing"],
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        another_sample = _seed_sample(db, dataset, "resume-002")
        invalid_score = AiEvaluationResult(
            run=run,
            sample=another_sample,
            status="failed",
            score=1.5,
            actual_output={},
            expected_snapshot={},
            error_types=["wrong_recommendation"],
        )
        db.add(invalid_score)
        with pytest.raises(IntegrityError):
            db.commit()


def test_ai_evaluation_error_case_tracks_result_and_requires_resolution_time(
    ai_evaluation_session_factory: sessionmaker[Session],
) -> None:
    with ai_evaluation_session_factory() as db:
        dataset, run, result = _seed_run_and_result(db)
        error_case = AiEvaluationErrorCase(
            result=result,
            dataset=dataset,
            run=run,
            sample=result.sample,
            error_type="evidence_missing",
            severity="high",
            title="证据引用不足",
            description="回答没有引用简历或知识库证据。",
            expected_behavior="引用候选人简历中的 Python 项目经历。",
            actual_behavior="只给出泛化评价。",
        )
        db.add(error_case)
        db.commit()
        result_id = result.id
        db.expire_all()

        stored = db.scalars(select(AiEvaluationErrorCase)).one()

    assert stored.status == "open"
    assert stored.result_id == result_id

    with ai_evaluation_session_factory() as db:
        dataset, run, result = _seed_run_and_result(db)
        invalid_resolved = AiEvaluationErrorCase(
            result=result,
            dataset=dataset,
            run=run,
            sample=result.sample,
            error_type="hallucination",
            severity="critical",
            status="resolved",
            title="幻觉案例",
        )
        db.add(invalid_resolved)
        with pytest.raises(IntegrityError):
            db.commit()
