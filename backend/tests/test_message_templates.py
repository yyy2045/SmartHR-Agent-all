import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import MessageTemplate, MessageTemplateVersion
from app.models.message import MESSAGE_TEMPLATE_TYPES
from app.services.message_template_defaults import (
    DEFAULT_MESSAGE_TEMPLATES,
    ensure_default_message_templates,
)


@pytest.fixture
def template_session_factory() -> Generator[sessionmaker[Session], None, None]:
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

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _custom_template(name: str, *, status: str = "active") -> MessageTemplate:
    template = MessageTemplate(
        template_type="interview_invitation",
        name=name,
        status=status,
        current_version_number=1,
        resource_version=1,
        created_by_username="tester",
        created_by_display_name="测试人员",
    )
    template.versions.append(
        MessageTemplateVersion(
            version_number=1,
            idempotency_key=uuid.uuid4(),
            subject="面试通知",
            body="请按时参加面试。",
            variables=[],
            created_by_username="tester",
            created_by_display_name="测试人员",
        )
    )
    return template


def test_default_templates_are_idempotent_and_do_not_overwrite_changes(
    template_session_factory: sessionmaker[Session],
) -> None:
    ensure_default_message_templates(template_session_factory)
    with template_session_factory() as db:
        templates = list(db.scalars(select(MessageTemplate).order_by(MessageTemplate.system_key)))
        assert len(templates) == 7
        assert {item.template_type for item in templates} == set(MESSAGE_TEMPLATE_TYPES)
        assert all(len(item.versions) == 1 for item in templates)
        assert all(item.current_version is item.versions[0] for item in templates)
        target = db.get(MessageTemplate, DEFAULT_MESSAGE_TEMPLATES[0].template_id)
        assert target is not None
        target.name = "用户自定义名称"
        target.status = "inactive"
        target.resource_version = 2
        db.commit()

    ensure_default_message_templates(template_session_factory)
    with template_session_factory() as db:
        assert db.scalar(select(func.count(MessageTemplate.id))) == 7
        assert db.scalar(select(func.count(MessageTemplateVersion.id))) == 7
        target = db.get(MessageTemplate, DEFAULT_MESSAGE_TEMPLATES[0].template_id)
        assert target is not None
        assert target.name == "用户自定义名称"
        assert target.status == "inactive"
        assert target.resource_version == 2


def test_active_template_names_are_case_insensitively_unique(
    template_session_factory: sessionmaker[Session],
) -> None:
    with template_session_factory() as db:
        db.add(_custom_template("Candidate Notice"))
        db.commit()
        db.add(_custom_template("candidate notice"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(_custom_template("CANDIDATE NOTICE", status="inactive"))
        db.commit()
        assert db.scalar(select(func.count(MessageTemplate.id))) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"template_type": "unknown"},
        {"status": "deleted"},
        {"name": "   "},
        {"current_version_number": 0},
        {"resource_version": 0},
    ],
)
def test_template_constraints_reject_invalid_values(
    template_session_factory: sessionmaker[Session],
    changes: dict[str, object],
) -> None:
    template = _custom_template("约束测试")
    for field, value in changes.items():
        setattr(template, field, value)
    with template_session_factory() as db:
        db.add(template)
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "subject,body",
    [
        ("", "正文"),
        ("标题", ""),
        ("标" * 101, "正文"),
        ("标题", "正" * 5001),
    ],
)
def test_template_version_length_constraints(
    template_session_factory: sessionmaker[Session],
    subject: str,
    body: str,
) -> None:
    template = _custom_template("长度测试")
    template.versions[0].subject = subject
    template.versions[0].body = body
    with template_session_factory() as db:
        db.add(template)
        with pytest.raises(IntegrityError):
            db.commit()


def test_template_versions_cannot_be_updated_deleted_or_duplicated(
    template_session_factory: sessionmaker[Session],
) -> None:
    with template_session_factory() as db:
        template = _custom_template("不可变测试")
        db.add(template)
        db.commit()
        version_id = template.current_version.id
        template_id = template.id

        template.current_version.body = "覆盖历史正文"
        with pytest.raises(ValueError, match="历史版本不可修改"):
            db.commit()
        db.rollback()

        version = db.get(MessageTemplateVersion, version_id)
        assert version is not None
        db.delete(version)
        with pytest.raises(ValueError, match="历史版本不可删除"):
            db.commit()
        db.rollback()

        template = db.get(MessageTemplate, template_id)
        assert template is not None
        template.versions.append(
            MessageTemplateVersion(
                version_number=1,
                idempotency_key=uuid.uuid4(),
                subject="重复版本",
                body="重复版本正文",
                variables=[],
                created_by_username="tester",
                created_by_display_name="测试人员",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        template = db.get(MessageTemplate, template_id)
        assert template is not None
        db.delete(template)
        with pytest.raises(IntegrityError):
            db.commit()
