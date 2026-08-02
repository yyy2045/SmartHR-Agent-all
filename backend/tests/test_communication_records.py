import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Candidate,
    CommunicationRecord,
    Job,
    JobApplication,
    MessageTemplate,
    MessageTemplateVersion,
    User,
)
from app.services.message_template_defaults import ensure_default_message_templates
from app.services.security import hash_password


@dataclass
class CommunicationRecordDependencies:
    session_factory: sessionmaker[Session]
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    other_application_id: uuid.UUID
    other_candidate_id: uuid.UUID
    template_version_id: uuid.UUID
    actor_id: uuid.UUID


@pytest.fixture
def communication_record_dependencies() -> Generator[
    CommunicationRecordDependencies, None, None
]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with testing_session() as db:
        actor = User(
            username="communication-recruiter",
            password_hash=hash_password("correct-password"),
            display_name="沟通招聘专员",
        )
        job = Job(
            owner=actor,
            title="高级后端工程师",
            department="研发",
            original_jd="负责核心服务开发",
        )
        candidate = Candidate(full_name="候选人甲", phone="13800001234")
        other_candidate = Candidate(full_name="候选人乙", phone="13900005678")
        application = JobApplication(candidate=candidate, job=job)
        other_application = JobApplication(candidate=other_candidate, job=job)
        db.add_all([actor, job, candidate, other_candidate, application, other_application])
        db.commit()
        dependencies = CommunicationRecordDependencies(
            session_factory=testing_session,
            application_id=application.id,
            candidate_id=candidate.id,
            other_application_id=other_application.id,
            other_candidate_id=other_candidate.id,
            template_version_id=uuid.UUID(int=0),
            actor_id=actor.id,
        )

    ensure_default_message_templates(testing_session)
    with testing_session() as db:
        template_version_id = db.scalar(
            select(MessageTemplateVersion.id)
            .join(MessageTemplate)
            .where(MessageTemplate.template_type == "offer_notification")
        )
        assert template_version_id is not None
        dependencies.template_version_id = template_version_id

    yield dependencies
    engine.dispose()


def build_record(
    dependencies: CommunicationRecordDependencies,
    **changes: object,
) -> CommunicationRecord:
    values: dict[str, object] = {
        "application_id": dependencies.application_id,
        "candidate_id": dependencies.candidate_id,
        "context_type": "offer",
        "context_id": uuid.uuid4(),
        "template_version_id": dependencies.template_version_id,
        "record_kind": "sent",
        "correction_sequence": 0,
        "channel": "wechat",
        "recipient_type": "phone",
        "recipient_masked": "138****1234",
        "candidate_name_snapshot": "候选人甲",
        "subject_snapshot": "Offer 通知",
        "body_snapshot": "请通过 [候选人专属链接已隐藏] 查看 Offer。",
        "sent_at": datetime.now(UTC) - timedelta(minutes=1),
        "is_historical": False,
        "idempotency_key": uuid.uuid4(),
        "request_fingerprint": "a" * 64,
        "created_by_id": dependencies.actor_id,
        "created_by_username_snapshot": "communication-recruiter",
        "created_by_display_name_snapshot": "沟通招聘专员",
    }
    values.update(changes)
    return CommunicationRecord(**values)


def test_original_and_historical_records_preserve_safe_snapshots(
    communication_record_dependencies: CommunicationRecordDependencies,
) -> None:
    with communication_record_dependencies.session_factory() as db:
        original = build_record(communication_record_dependencies)
        historical = build_record(
            communication_record_dependencies,
            template_version_id=None,
            channel="email",
            recipient_type="email",
            recipient_masked="c***@example.com",
            is_historical=True,
            historical_note="上线前通过邮件发送，现补录归档",
        )
        db.add_all([original, historical])
        db.commit()

        assert original.application.id == communication_record_dependencies.application_id
        assert original.candidate.id == communication_record_dependencies.candidate_id
        assert original.template_version is not None
        assert original.root_record_id is None
        assert original.correction_sequence == 0
        assert historical.template_version_id is None
        assert historical.historical_note == "上线前通过邮件发送，现补录归档"
        assert db.scalar(select(func.count(CommunicationRecord.id))) == 2


@pytest.mark.parametrize(
    ("changes", "constraint_name"),
    [
        (
            {"recipient_masked": "13800001234"},
            "ck_communication_records_recipient_masked",
        ),
        (
            {"channel": "email", "recipient_type": "phone"},
            "ck_communication_records_channel_recipient",
        ),
        (
            {"channel": "other", "recipient_type": "other"},
            "ck_communication_records_channel_detail",
        ),
        (
            {"is_historical": True},
            "ck_communication_records_historical_note",
        ),
        (
            {"request_fingerprint": "short"},
            "ck_communication_records_fingerprint_length",
        ),
    ],
)
def test_database_constraints_reject_invalid_records(
    communication_record_dependencies: CommunicationRecordDependencies,
    changes: dict[str, object],
    constraint_name: str,
) -> None:
    with communication_record_dependencies.session_factory() as db:
        db.add(build_record(communication_record_dependencies, **changes))
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert constraint_name in str(error.value)


def test_corrections_form_one_linear_chain_for_the_same_application(
    communication_record_dependencies: CommunicationRecordDependencies,
) -> None:
    with communication_record_dependencies.session_factory() as db:
        original = build_record(communication_record_dependencies)
        db.add(original)
        db.commit()

        first_correction = build_record(
            communication_record_dependencies,
            record_kind="correction",
            root_record_id=original.id,
            corrects_record_id=original.id,
            correction_sequence=1,
            correction_reason="原发送时间登记错误",
            sent_at=datetime.now(UTC) - timedelta(minutes=2),
        )
        db.add(first_correction)
        db.commit()

        second_correction = build_record(
            communication_record_dependencies,
            record_kind="correction",
            root_record_id=original.id,
            corrects_record_id=first_correction.id,
            correction_sequence=2,
            correction_reason="补充正确渠道说明",
            channel="other",
            recipient_type="other",
            recipient_masked="外部招聘工具",
            channel_detail="腾讯会议聊天",
        )
        db.add(second_correction)
        db.commit()

        assert second_correction.root_record.id == original.id
        assert second_correction.corrects_record.id == first_correction.id

        branch = build_record(
            communication_record_dependencies,
            record_kind="correction",
            root_record_id=original.id,
            corrects_record_id=original.id,
            correction_sequence=1,
            correction_reason="并发分叉",
        )
        db.add(branch)
        with pytest.raises(IntegrityError):
            db.commit()


def test_record_candidate_must_match_application(
    communication_record_dependencies: CommunicationRecordDependencies,
) -> None:
    with communication_record_dependencies.session_factory() as db:
        record = build_record(
            communication_record_dependencies,
            candidate_id=communication_record_dependencies.other_candidate_id,
            candidate_name_snapshot="候选人乙",
            recipient_masked="139****5678",
        )
        db.add(record)
        with pytest.raises(ValueError, match="候选人不一致"):
            db.commit()


def test_correction_rejects_cross_application_wrong_root_and_sequence(
    communication_record_dependencies: CommunicationRecordDependencies,
) -> None:
    with communication_record_dependencies.session_factory() as db:
        original = build_record(communication_record_dependencies)
        other_original = build_record(
            communication_record_dependencies,
            application_id=communication_record_dependencies.other_application_id,
            candidate_id=communication_record_dependencies.other_candidate_id,
            candidate_name_snapshot="候选人乙",
            recipient_masked="139****5678",
        )
        db.add_all([original, other_original])
        db.commit()

        cross_application = build_record(
            communication_record_dependencies,
            application_id=communication_record_dependencies.other_application_id,
            candidate_id=communication_record_dependencies.other_candidate_id,
            candidate_name_snapshot="候选人乙",
            recipient_masked="139****5678",
            record_kind="correction",
            root_record_id=original.id,
            corrects_record_id=original.id,
            correction_sequence=1,
            correction_reason="错误跨应聘更正",
        )
        db.add(cross_application)
        with pytest.raises(ValueError, match="同一职位应聘"):
            db.commit()
        db.rollback()

        wrong_root = build_record(
            communication_record_dependencies,
            record_kind="correction",
            root_record_id=other_original.id,
            corrects_record_id=original.id,
            correction_sequence=1,
            correction_reason="错误根记录",
        )
        db.add(wrong_root)
        with pytest.raises(ValueError, match="根记录不一致"):
            db.commit()
        db.rollback()

        wrong_sequence = build_record(
            communication_record_dependencies,
            record_kind="correction",
            root_record_id=original.id,
            corrects_record_id=original.id,
            correction_sequence=2,
            correction_reason="错误序号",
        )
        db.add(wrong_sequence)
        with pytest.raises(ValueError, match="序号必须连续"):
            db.commit()


def test_records_are_immutable_and_cannot_be_deleted(
    communication_record_dependencies: CommunicationRecordDependencies,
) -> None:
    with communication_record_dependencies.session_factory() as db:
        record = build_record(communication_record_dependencies)
        db.add(record)
        db.commit()

        record.subject_snapshot = "试图覆盖原记录"
        with pytest.raises(ValueError, match="不可修改"):
            db.commit()
        db.rollback()

        stored = db.get(CommunicationRecord, record.id)
        assert stored is not None
        db.delete(stored)
        with pytest.raises(ValueError, match="不可删除"):
            db.commit()


def test_future_time_raw_offer_link_and_duplicate_idempotency_are_rejected(
    communication_record_dependencies: CommunicationRecordDependencies,
) -> None:
    with communication_record_dependencies.session_factory() as db:
        future = build_record(
            communication_record_dependencies,
            sent_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        db.add(future)
        with pytest.raises(ValueError, match="不能晚于当前时间"):
            db.commit()
        db.rollback()

        raw_link = build_record(
            communication_record_dependencies,
            body_snapshot=(
                "请访问 https://example.com/portal/offers/"
                "raw-token-value-that-must-not-persist"
            ),
        )
        db.add(raw_link)
        with pytest.raises(ValueError, match="不能保存 Offer 原始链接"):
            db.commit()
        db.rollback()

        key = uuid.uuid4()
        db.add(build_record(communication_record_dependencies, idempotency_key=key))
        db.commit()
        db.add(build_record(communication_record_dependencies, idempotency_key=key))
        with pytest.raises(IntegrityError):
            db.commit()
