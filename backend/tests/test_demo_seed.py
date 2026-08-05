from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.demo.seed import (
    DEMO_EVALUATION_DATASET_CODE,
    DEMO_JOB_TITLE,
    DEMO_KNOWLEDGE_BASE_NAME,
    seed_demo_data,
)
from app.models import (
    AiCallLog,
    AiEvaluationDataset,
    AiEvaluationErrorCase,
    AiEvaluationSample,
    AiTask,
    Candidate,
    CandidateProcess,
    Job,
    JobApplication,
    RecruitmentKnowledgeBase,
    RecruitmentKnowledgeDocument,
    ResumeDocument,
    ScreeningResult,
    User,
)


@pytest.fixture
def demo_seed_session_factory() -> Generator[sessionmaker[Session], None, None]:
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


def test_seed_demo_data_creates_core_showcase_records(
    demo_seed_session_factory: sessionmaker[Session],
) -> None:
    with demo_seed_session_factory() as db:
        summary = seed_demo_data(db)

        job = db.scalar(select(Job).where(Job.title == DEMO_JOB_TITLE))
        dataset = db.scalar(
            select(AiEvaluationDataset).where(
                AiEvaluationDataset.code == DEMO_EVALUATION_DATASET_CODE
            )
        )
        knowledge_base = db.scalar(
            select(RecruitmentKnowledgeBase).where(
                RecruitmentKnowledgeBase.name == DEMO_KNOWLEDGE_BASE_NAME
            )
        )

        assert summary.users == 4
        assert summary.jobs == 1
        assert summary.candidates == 4
        assert summary.applications == 4
        assert summary.ai_tasks == 3
        assert summary.ai_calls == 3
        assert summary.knowledge_documents == 2
        assert summary.evaluation_samples == 3

        assert job is not None
        assert dataset is not None
        assert knowledge_base is not None
        assert db.scalar(select(func.count(User.id)).where(User.username.like("demo-%"))) == 4
        assert db.scalar(select(func.count(CandidateProcess.id))) == 4
        assert db.scalar(select(func.count(ScreeningResult.id))) == 4
        assert db.scalar(select(func.count(ResumeDocument.id))) == 4
        assert db.scalar(select(func.count(AiEvaluationErrorCase.id))) == 1
        assert db.scalar(select(func.count(RecruitmentKnowledgeDocument.id))) == 2


def test_seed_demo_data_is_idempotent(
    demo_seed_session_factory: sessionmaker[Session],
) -> None:
    with demo_seed_session_factory() as db:
        first = seed_demo_data(db)
        second = seed_demo_data(db)

        assert first == second
        assert db.scalar(select(func.count(Job.id)).where(Job.title == DEMO_JOB_TITLE)) == 1
        assert db.scalar(select(func.count(Candidate.id))) == 4
        assert db.scalar(select(func.count(JobApplication.id))) == 4
        assert db.scalar(select(func.count(AiTask.id))) == 3
        assert db.scalar(select(func.count(AiCallLog.id))) == 3
        assert (
            db.scalar(
                select(func.count(AiEvaluationSample.id))
                .join(AiEvaluationDataset)
                .where(AiEvaluationDataset.code == DEMO_EVALUATION_DATASET_CODE)
            )
            == 3
        )
