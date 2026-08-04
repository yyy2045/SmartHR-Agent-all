from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import SessionLocal
from app.models import PromptTemplate, PromptTemplateVersion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DefaultPromptTemplate:
    template_id: uuid.UUID
    version_id: uuid.UUID
    idempotency_key: uuid.UUID
    scenario: str
    name: str
    description: str
    system_prompt: str
    user_prompt_template: str
    variables: tuple[str, ...]
    output_schema: dict[str, object]
    model_parameters: dict[str, object]


DEFAULT_PROMPT_TEMPLATES = (
    DefaultPromptTemplate(
        uuid.UUID("23000000-0000-0000-0000-000000000001"),
        uuid.UUID("24000000-0000-0000-0000-000000000001"),
        uuid.UUID("25000000-0000-0000-0000-000000000001"),
        "jd_generation",
        "Default JD structuring prompt",
        "Generate structured screening criteria from a job description.",
        "You are an enterprise recruiting criteria assistant. Use only the supplied JD. "
        "Do not invent facts. Return only valid JSON. {{schema_instruction}}",
        "Job title: {{title}}\nDepartment: {{department}}\nJD:\n{{jd}}",
        ("title", "department", "jd", "schema_instruction"),
        {"type": "object"},
        {"temperature": 0.1},
    ),
    DefaultPromptTemplate(
        uuid.UUID("23000000-0000-0000-0000-000000000002"),
        uuid.UUID("24000000-0000-0000-0000-000000000002"),
        uuid.UUID("25000000-0000-0000-0000-000000000002"),
        "resume_analysis",
        "Default resume scoring prompt",
        "Score one resume against confirmed job criteria with evidence citations.",
        "You are an enterprise recruiter assistant. Judge only from supplied segments and "
        "confirmed criteria. Evidence quotes must be continuous original text from the "
        "matching segment. If enterprise_knowledge.citations are supplied, use them only "
        "as policy or scoring-standard references, never as candidate evidence. Do not "
        "return total score or final decision. {{schema_instruction}}",
        "{{payload}}",
        ("payload", "schema_instruction"),
        {"type": "object"},
        {"temperature": 0},
    ),
    DefaultPromptTemplate(
        uuid.UUID("23000000-0000-0000-0000-000000000003"),
        uuid.UUID("24000000-0000-0000-0000-000000000003"),
        uuid.UUID("25000000-0000-0000-0000-000000000003"),
        "resume_analysis_repair",
        "Default resume scoring repair prompt",
        "Repair invalid resume scoring output without changing business facts.",
        "The previous output failed backend contract validation. Keep facts, statuses, "
        "scores and ids stable. Only replace invalid evidence quotes with continuous "
        "original text from the supplied segments. Validation feedback: "
        "{{validation_feedback}} {{schema_instruction}}",
        "{{payload}}",
        ("payload", "validation_feedback", "schema_instruction"),
        {"type": "object"},
        {"temperature": 0},
    ),
    DefaultPromptTemplate(
        uuid.UUID("23000000-0000-0000-0000-000000000004"),
        uuid.UUID("24000000-0000-0000-0000-000000000004"),
        uuid.UUID("25000000-0000-0000-0000-000000000004"),
        "interview_report",
        "Default interview report prompt",
        "Draft an editable interview report from screening evidence and submitted evaluations.",
        "You are an enterprise interview report assistant. Use only supplied screening "
        "results, evidence and submitted interview evaluations. Missing rounds are risk "
        "signals only and must not be treated as failed interviews. AI never makes the "
        "final hiring decision. If enterprise_knowledge.citations are supplied, use them "
        "only as policy or process references and never as candidate evidence. "
        "{{schema_instruction}}",
        "{{payload}}",
        ("payload", "schema_instruction"),
        {"type": "object"},
        {"temperature": 0.1},
    ),
    DefaultPromptTemplate(
        uuid.UUID("23000000-0000-0000-0000-000000000005"),
        uuid.UUID("24000000-0000-0000-0000-000000000005"),
        uuid.UUID("25000000-0000-0000-0000-000000000005"),
        "candidate_qa",
        "Default candidate QA Agent prompt",
        "Answer recruiter questions from candidate lifecycle context and knowledge citations.",
        "You are an enterprise recruiting candidate QA Agent. Use only supplied candidate "
        "context, lifecycle records and enterprise knowledge citations. Candidate facts "
        "must come from candidate context; knowledge citations are policy or standard "
        "references only. Never hire, reject, send Offer or change pipeline stage. "
        "Return evidence, limitations and follow-up suggestions. {{schema_instruction}}",
        "{{payload}}",
        ("payload", "question", "context", "enterprise_knowledge", "schema_instruction"),
        {"type": "object"},
        {"temperature": 0.1},
    ),
)


def ensure_default_prompt_templates(
    session_factory: sessionmaker[Session] = SessionLocal,
) -> None:
    created_count = 0
    now = datetime.now(UTC)
    with session_factory() as db:
        existing_scenarios = set(db.scalars(select(PromptTemplate.scenario)))
        for seed in DEFAULT_PROMPT_TEMPLATES:
            if seed.scenario in existing_scenarios or db.get(PromptTemplate, seed.template_id):
                continue
            try:
                with db.begin_nested():
                    template = PromptTemplate(
                        id=seed.template_id,
                        scenario=seed.scenario,
                        name=seed.name,
                        description=seed.description,
                        status="active",
                        current_version_number=1,
                        resource_version=1,
                        created_by_username="system",
                        created_by_display_name="system",
                    )
                    template.versions.append(
                        PromptTemplateVersion(
                            id=seed.version_id,
                            version_number=1,
                            status="published",
                            idempotency_key=seed.idempotency_key,
                            change_note="Initial default prompt",
                            system_prompt=seed.system_prompt,
                            user_prompt_template=seed.user_prompt_template,
                            variables=list(seed.variables),
                            output_schema=seed.output_schema,
                            model_parameters=seed.model_parameters,
                            created_by_username="system",
                            created_by_display_name="system",
                            published_by_username="system",
                            published_by_display_name="system",
                            published_at=now,
                        )
                    )
                    db.add(template)
                    db.flush()
                    existing_scenarios.add(seed.scenario)
                    created_count += 1
            except IntegrityError:
                continue
        db.commit()
    if created_count:
        logger.info("Initialized %s default Prompt templates", created_count)
