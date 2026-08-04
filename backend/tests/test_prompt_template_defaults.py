from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import PromptTemplate
from app.services.prompt_template_defaults import (
    DEFAULT_PROMPT_TEMPLATES,
    ensure_default_prompt_templates,
)


@pytest.fixture
def prompt_default_session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_ensure_default_prompt_templates_creates_published_versions_idempotently(
    prompt_default_session_factory: sessionmaker[Session],
) -> None:
    ensure_default_prompt_templates(prompt_default_session_factory)
    ensure_default_prompt_templates(prompt_default_session_factory)

    with prompt_default_session_factory() as db:
        templates = list(
            db.scalars(
                select(PromptTemplate)
                .options(selectinload(PromptTemplate.versions))
                .order_by(PromptTemplate.scenario)
            )
        )

    assert len(templates) == len(DEFAULT_PROMPT_TEMPLATES)
    assert {template.scenario for template in templates} == {
        seed.scenario for seed in DEFAULT_PROMPT_TEMPLATES
    }
    for template in templates:
        assert template.status == "active"
        assert template.current_version_number == 1
        assert len(template.versions) == 1
        assert template.versions[0].status == "published"
        assert "{{schema_instruction}}" in template.versions[0].system_prompt


def test_ensure_default_prompt_templates_does_not_override_existing_scenario(
    prompt_default_session_factory: sessionmaker[Session],
) -> None:
    with prompt_default_session_factory() as db:
        db.add(
            PromptTemplate(
                scenario="jd_generation",
                name="Custom JD prompt",
                status="active",
                current_version_number=None,
                created_by_username="admin",
                created_by_display_name="Admin",
            )
        )
        db.commit()

    ensure_default_prompt_templates(prompt_default_session_factory)

    with prompt_default_session_factory() as db:
        jd_templates = list(
            db.scalars(select(PromptTemplate).where(PromptTemplate.scenario == "jd_generation"))
        )
        templates = list(db.scalars(select(PromptTemplate)))

    assert len(jd_templates) == 1
    assert jd_templates[0].name == "Custom JD prompt"
    assert len(templates) == len(DEFAULT_PROMPT_TEMPLATES)
