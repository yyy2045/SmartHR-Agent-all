import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Candidate,
    CandidateAgentExchange,
    CandidateAgentReport,
    CandidateAgentSession,
    Job,
    JobApplication,
    User,
)
from app.services.security import hash_password


@pytest.fixture
def candidate_agent_session_factory() -> Generator[sessionmaker[Session], None, None]:
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


def _seed_session(db: Session) -> CandidateAgentSession:
    username = f"recruiter-{uuid.uuid4().hex[:8]}"
    recruiter = User(
        username=username,
        password_hash=hash_password("correct-password"),
        display_name="招聘专员",
    )
    db.add(recruiter)
    db.flush()
    job = Job(
        owner_id=recruiter.id,
        title="后端工程师",
        department="研发中心",
        original_jd="负责后端服务开发。",
    )
    candidate = Candidate(full_name="候选人A")
    application = JobApplication(candidate=candidate, job=job)
    session = CandidateAgentSession(
        job=job,
        application=application,
        title="候选人A 问答",
        created_by=recruiter,
    )
    db.add(session)
    db.commit()
    return session


def test_candidate_agent_session_orders_exchanges(
    candidate_agent_session_factory: sessionmaker[Session],
) -> None:
    with candidate_agent_session_factory() as db:
        session = _seed_session(db)
        session.exchanges.extend(
            [
                CandidateAgentExchange(
                    sequence_number=2,
                    idempotency_key=uuid.uuid4(),
                    status="succeeded",
                    question="主要风险是什么？",
                    answer="业务面评价缺失，需要补充核实。",
                    evidence_snapshot={"application_id": str(session.application_id)},
                    evidence_references=[
                        {"source_type": "interview", "source_label": "业务面"}
                    ],
                    knowledge_citations=[],
                    created_by=session.created_by,
                ),
                CandidateAgentExchange(
                    sequence_number=1,
                    idempotency_key=uuid.uuid4(),
                    status="succeeded",
                    question="适合这个岗位吗？",
                    answer="可以进入下一轮，但需要人工确认。",
                    evidence_snapshot={"application_id": str(session.application_id)},
                    evidence_references=[
                        {"source_type": "screening", "source_label": "AI 初筛"}
                    ],
                    knowledge_citations=[],
                    created_by=session.created_by,
                ),
            ]
        )
        db.commit()
        db.expire_all()
        stored = db.scalars(select(CandidateAgentSession)).one()
        sequence_numbers = [item.sequence_number for item in stored.exchanges]
        first_question = stored.exchanges[0].question

    assert sequence_numbers == [1, 2]
    assert first_question == "适合这个岗位吗？"


def test_candidate_agent_exchange_enforces_idempotency_and_sequence(
    candidate_agent_session_factory: sessionmaker[Session],
) -> None:
    same_key = uuid.uuid4()
    with candidate_agent_session_factory() as db:
        session = _seed_session(db)
        session.exchanges.append(
            CandidateAgentExchange(
                sequence_number=1,
                idempotency_key=same_key,
                status="pending",
                question="他的优势是什么？",
                evidence_snapshot={},
                evidence_references=[],
                knowledge_citations=[],
            )
        )
        session.exchanges.append(
            CandidateAgentExchange(
                sequence_number=2,
                idempotency_key=same_key,
                status="pending",
                question="重复请求",
                evidence_snapshot={},
                evidence_references=[],
                knowledge_citations=[],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    with candidate_agent_session_factory() as db:
        session = _seed_session(db)
        session.exchanges.append(
            CandidateAgentExchange(
                sequence_number=1,
                idempotency_key=uuid.uuid4(),
                status="pending",
                question="他的优势是什么？",
                evidence_snapshot={},
                evidence_references=[],
                knowledge_citations=[],
            )
        )
        session.exchanges.append(
            CandidateAgentExchange(
                sequence_number=1,
                idempotency_key=uuid.uuid4(),
                status="pending",
                question="重复序号",
                evidence_snapshot={},
                evidence_references=[],
                knowledge_citations=[],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_candidate_agent_report_persists_content(
    candidate_agent_session_factory: sessionmaker[Session],
) -> None:
    with candidate_agent_session_factory() as db:
        session = _seed_session(db)
        db.add(
            CandidateAgentReport(
                application_id=session.application_id,
                job_id=session.job_id,
                idempotency_key=uuid.uuid4(),
                status="succeeded",
                match_assessment="整体匹配度较高。",
                strengths=["系统重构经验"],
                risks=["团队规模未明确"],
                overall_recommendation="next_round",
                evidence_references=[
                    {"source_type": "latest_screening", "source_label": "AI 初筛"}
                ],
                tool_trajectory=[
                    {"name": "get_latest_screening", "step": 0, "status": "succeeded"}
                ],
                ai_call_log_ids=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                created_by_id=session.created_by_id,
            )
        )
        db.commit()
        db.expire_all()
        stored = db.scalars(select(CandidateAgentReport)).one()

    assert stored.status == "succeeded"
    assert stored.match_assessment == "整体匹配度较高。"
    assert stored.strengths == ["系统重构经验"]
    assert stored.overall_recommendation == "next_round"
    assert stored.tool_trajectory[0]["name"] == "get_latest_screening"
    assert stored.ai_call_log_ids == ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]


def test_candidate_agent_report_enforces_idempotency(
    candidate_agent_session_factory: sessionmaker[Session],
) -> None:
    same_key = uuid.uuid4()
    with candidate_agent_session_factory() as db:
        session = _seed_session(db)
        db.add(
            CandidateAgentReport(
                application_id=session.application_id,
                job_id=session.job_id,
                idempotency_key=same_key,
                status="pending",
            )
        )
        db.add(
            CandidateAgentReport(
                application_id=session.application_id,
                job_id=session.job_id,
                idempotency_key=same_key,
                status="pending",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_candidate_agent_succeeded_exchange_requires_answer(
    candidate_agent_session_factory: sessionmaker[Session],
) -> None:
    with candidate_agent_session_factory() as db:
        session = _seed_session(db)
        session.exchanges.append(
            CandidateAgentExchange(
                sequence_number=1,
                idempotency_key=uuid.uuid4(),
                status="succeeded",
                question="可以录用吗？",
                answer=None,
                evidence_snapshot={},
                evidence_references=[],
                knowledge_citations=[],
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
