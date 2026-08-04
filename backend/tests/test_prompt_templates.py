import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AiCallLog, PromptTemplate, PromptTemplateVersion, Role, User, UserRole
from app.services.security import hash_password


@pytest.fixture
def prompt_session_factory() -> Generator[sessionmaker[Session], None, None]:
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


def _user(db: Session) -> User:
    role = Role(key="administrator", display_name="企业管理员")
    user = User(
        username="admin",
        password_hash=hash_password("correct-password"),
        display_name="管理员",
        role_assignments=[UserRole(role=role)],
    )
    db.add(user)
    db.flush()
    return user


def _template(user: User) -> PromptTemplate:
    return PromptTemplate(
        scenario="resume_analysis",
        name="简历评分 Prompt",
        description="用于根据职位标准分析简历",
        current_version_number=1,
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
    )


def _version(
    template: PromptTemplate,
    user: User,
    *,
    version_number: int = 1,
    status: str = "published",
) -> PromptTemplateVersion:
    return PromptTemplateVersion(
        template=template,
        version_number=version_number,
        status=status,
        idempotency_key=uuid.uuid4(),
        change_note="初始化简历评分 Prompt",
        system_prompt="你是企业招聘的人岗匹配助手。",
        user_prompt_template="职位标准：{{criteria}}\n简历：{{resume}}",
        variables=["criteria", "resume"],
        output_schema={"type": "object", "required": ["summary"]},
        model_parameters={"temperature": 0},
        created_by_id=user.id,
        created_by_username=user.username,
        created_by_display_name=user.display_name,
        published_by_id=user.id if status == "published" else None,
        published_by_username=user.username if status == "published" else None,
        published_by_display_name=user.display_name if status == "published" else None,
        published_at=datetime.now(UTC) if status == "published" else None,
    )


def test_prompt_template_version_tracks_schema_and_ai_call_binding(
    prompt_session_factory: sessionmaker[Session],
) -> None:
    with prompt_session_factory() as db:
        user = _user(db)
        template = _template(user)
        version = _version(template, user)
        call = AiCallLog(
            scenario="resume_analysis",
            status="succeeded",
            model_name="qwen-plus",
            prompt_version="resume-match-v2",
            prompt_template_version=version,
            total_tokens=120,
        )
        db.add_all([template, version, call])
        db.commit()

        stored = db.scalars(select(PromptTemplate).where(PromptTemplate.id == template.id)).one()
        assert stored.current_version is not None
        assert stored.current_version.output_schema == {"type": "object", "required": ["summary"]}
        assert stored.current_version.variables == ["criteria", "resume"]
        assert stored.current_version.ai_call_logs[0].total_tokens == 120


@pytest.mark.parametrize(
    "template_changes",
    [
        {"scenario": "unknown"},
        {"status": "deleted"},
        {"name": "   "},
        {"description": "x" * 1001},
        {"current_version_number": 0},
        {"resource_version": 0},
    ],
)
def test_prompt_template_constraints_reject_invalid_values(
    prompt_session_factory: sessionmaker[Session],
    template_changes: dict[str, object],
) -> None:
    with prompt_session_factory() as db:
        user = _user(db)
        template = _template(user)
        for key, value in template_changes.items():
            setattr(template, key, value)
        db.add(template)
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "version_changes",
    [
        {"version_number": 0},
        {"status": "active"},
        {"change_note": ""},
        {"system_prompt": "   "},
        {"user_prompt_template": ""},
        {"status": "draft", "published_at": datetime.now(UTC)},
    ],
)
def test_prompt_template_version_constraints_reject_invalid_values(
    prompt_session_factory: sessionmaker[Session],
    version_changes: dict[str, object],
) -> None:
    with prompt_session_factory() as db:
        user = _user(db)
        template = _template(user)
        version = _version(template, user, status="draft")
        for key, value in version_changes.items():
            setattr(version, key, value)
        db.add_all([template, version])
        with pytest.raises(IntegrityError):
            db.commit()


def test_prompt_template_version_number_and_idempotency_are_unique_per_template(
    prompt_session_factory: sessionmaker[Session],
) -> None:
    with prompt_session_factory() as db:
        user = _user(db)
        template = _template(user)
        version = _version(template, user, version_number=1)
        duplicate = _version(template, user, version_number=1)
        db.add_all([template, version, duplicate])
        with pytest.raises(IntegrityError):
            db.commit()


def test_prompt_template_versions_are_immutable(
    prompt_session_factory: sessionmaker[Session],
) -> None:
    with prompt_session_factory() as db:
        user = _user(db)
        template = _template(user)
        version = _version(template, user)
        db.add_all([template, version])
        db.commit()

        version.status = "retired"
        db.commit()

        version.change_note = "尝试覆盖历史版本"
        with pytest.raises(ValueError, match="正文不可修改"):
            db.commit()
        db.rollback()

        db.delete(version)
        with pytest.raises(ValueError, match="不可删除"):
            db.commit()
