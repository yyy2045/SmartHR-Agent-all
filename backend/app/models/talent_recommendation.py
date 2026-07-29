from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.job import Job, JobCriteriaVersion
    from app.models.resume import CandidateProfile, ResumeDocument
    from app.models.talent_pool import TalentPoolGroup
    from app.models.user import User


TALENT_RECOMMENDATION_RUN_STATUSES = (
    "queued",
    "retrieving",
    "rescoring",
    "completed",
    "partial",
    "failed",
    "cancelled",
)
TALENT_RECOMMENDATION_RUN_STATUS_SQL = ", ".join(
    f"'{status}'" for status in TALENT_RECOMMENDATION_RUN_STATUSES
)
TALENT_RECOMMENDATION_TERMINAL_STATUSES = (
    "completed",
    "partial",
    "failed",
    "cancelled",
)
TALENT_RECOMMENDATION_TERMINAL_STATUS_SQL = ", ".join(
    f"'{status}'" for status in TALENT_RECOMMENDATION_TERMINAL_STATUSES
)

TALENT_RECOMMENDATION_RESULT_STATUSES = (
    "retrieved",
    "rescoring",
    "completed",
    "failed",
    "excluded",
)
TALENT_RECOMMENDATION_RESULT_STATUS_SQL = ", ".join(
    f"'{status}'" for status in TALENT_RECOMMENDATION_RESULT_STATUSES
)

TALENT_RECOMMENDATION_EVENT_TYPES = (
    "created",
    "retrieval_started",
    "retrieval_completed",
    "rescoring_started",
    "completed",
    "partial",
    "failed",
    "cancel_requested",
    "cancelled",
    "retry_requested",
    "stale_marked",
)
TALENT_RECOMMENDATION_EVENT_TYPE_SQL = ", ".join(
    f"'{event_type}'" for event_type in TALENT_RECOMMENDATION_EVENT_TYPES
)


class TalentRecommendationRun(Base):
    __tablename__ = "talent_recommendation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    criteria_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_criteria_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_username_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_display_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued", index=True
    )
    ai_input_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="raw", server_default="raw"
    )
    recall_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )
    rescore_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default="20"
    )
    criteria_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    embedding_model_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    ai_model_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    scope_candidate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    retrieved_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rescored_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    excluded_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    criteria_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    criteria_stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_summary: Mapped[str | None] = mapped_column(Text)
    resource_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({TALENT_RECOMMENDATION_RUN_STATUS_SQL})",
            name="ck_talent_recommendation_runs_status",
        ),
        CheckConstraint(
            "ai_input_mode IN ('raw', 'redacted')",
            name="ck_talent_recommendation_runs_ai_input_mode",
        ),
        CheckConstraint(
            "recall_limit = 50 AND rescore_limit = 20",
            name="ck_talent_recommendation_runs_limits",
        ),
        CheckConstraint(
            "scope_candidate_count >= 0 AND retrieved_count >= 0 "
            "AND rescored_count >= 0 AND completed_count >= 0 "
            "AND failed_count >= 0 AND excluded_count >= 0",
            name="ck_talent_recommendation_runs_counts_nonnegative",
        ),
        CheckConstraint(
            "retrieved_count <= recall_limit AND rescored_count <= rescore_limit "
            "AND rescored_count <= retrieved_count "
            "AND completed_count + failed_count <= rescored_count",
            name="ck_talent_recommendation_runs_count_bounds",
        ),
        CheckConstraint(
            "resource_version >= 1",
            name="ck_talent_recommendation_runs_resource_version",
        ),
        CheckConstraint(
            "(criteria_stale = false AND criteria_stale_at IS NULL) OR "
            "(criteria_stale = true AND criteria_stale_at IS NOT NULL)",
            name="ck_talent_recommendation_runs_criteria_stale",
        ),
        CheckConstraint(
            f"(status IN ({TALENT_RECOMMENDATION_TERMINAL_STATUS_SQL}) "
            "AND completed_at IS NOT NULL) OR "
            f"(status NOT IN ({TALENT_RECOMMENDATION_TERMINAL_STATUS_SQL}) "
            "AND completed_at IS NULL)",
            name="ck_talent_recommendation_runs_completed_at",
        ),
        UniqueConstraint(
            "job_id",
            "idempotency_key",
            name="uq_talent_recommendation_runs_job_idempotency",
        ),
        Index(
            "ix_talent_recommendation_runs_job_created",
            "job_id",
            "created_at",
        ),
    )

    job: Mapped[Job] = relationship(foreign_keys=[job_id])
    criteria_version: Mapped[JobCriteriaVersion] = relationship(foreign_keys=[criteria_version_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    group_snapshots: Mapped[list[TalentRecommendationRunGroup]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="TalentRecommendationRunGroup.group_name_snapshot",
    )
    candidate_snapshots: Mapped[list[TalentRecommendationRunCandidate]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="TalentRecommendationRunCandidate.candidate_code_snapshot",
    )
    results: Mapped[list[TalentRecommendationResult]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="TalentRecommendationResult.vector_rank",
    )
    events: Mapped[list[TalentRecommendationRunEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="TalentRecommendationRunEvent.sequence_number",
    )


class TalentRecommendationRunGroup(Base):
    __tablename__ = "talent_recommendation_run_groups"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("talent_recommendation_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("talent_pool_groups.id", ondelete="RESTRICT"), primary_key=True
    )
    group_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    group_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(group_name_snapshot)) > 0",
            name="ck_talent_recommendation_run_groups_name_not_blank",
        ),
        CheckConstraint(
            "group_version_snapshot >= 1",
            name="ck_talent_recommendation_run_groups_version",
        ),
    )

    run: Mapped[TalentRecommendationRun] = relationship(back_populates="group_snapshots")
    group: Mapped[TalentPoolGroup] = relationship(foreign_keys=[group_id])


class TalentRecommendationRunCandidate(Base):
    __tablename__ = "talent_recommendation_run_candidates"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("talent_recommendation_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    candidate_code_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_name_snapshot: Mapped[str | None] = mapped_column(String(200))
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    document_sha256_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    document_updated_at_snapshot: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    candidate_profile_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    profile_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_group_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(candidate_code_snapshot)) > 0",
            name="ck_talent_recommendation_run_candidates_code",
        ),
        CheckConstraint(
            "length(document_sha256_snapshot) = 64",
            name="ck_talent_recommendation_run_candidates_sha256",
        ),
        CheckConstraint(
            "profile_version_snapshot >= 1 AND embedding_dimension_snapshot >= 1",
            name="ck_talent_recommendation_run_candidates_versions",
        ),
        ForeignKeyConstraint(
            ["candidate_profile_id", "document_id", "profile_version_snapshot"],
            [
                "candidate_profiles.id",
                "candidate_profiles.document_id",
                "candidate_profiles.version_number",
            ],
            name="fk_talent_recommendation_run_candidates_profile_snapshot",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "run_id",
            "document_id",
            name="uq_talent_recommendation_run_candidates_document",
        ),
    )

    run: Mapped[TalentRecommendationRun] = relationship(back_populates="candidate_snapshots")
    candidate: Mapped[Candidate] = relationship(foreign_keys=[candidate_id])
    document: Mapped[ResumeDocument] = relationship(foreign_keys=[document_id])
    candidate_profile: Mapped[CandidateProfile] = relationship(
        foreign_keys=[candidate_profile_id]
    )


class TalentRecommendationResult(Base):
    __tablename__ = "talent_recommendation_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("talent_recommendation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    resolved_candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    candidate_code_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_name_snapshot: Mapped[str | None] = mapped_column(String(200))
    candidate_merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_sha256_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    document_updated_at_snapshot: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    candidate_profile_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    profile_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_model_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_version_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Numeric(9, 8), nullable=False)
    matched_group_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    matched_chunks: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ai_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    ai_group: Mapped[str | None] = mapped_column(String(30))
    ai_dimension_scores: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    ai_evidence: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    ai_model_snapshot: Mapped[str | None] = mapped_column(String(200))
    prompt_version_snapshot: Mapped[str | None] = mapped_column(String(100))
    processing_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    exclusion_code: Mapped[str | None] = mapped_column(String(80))
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    document_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    profile_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    embedding_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({TALENT_RECOMMENDATION_RESULT_STATUS_SQL})",
            name="ck_talent_recommendation_results_status",
        ),
        CheckConstraint(
            "length(trim(candidate_code_snapshot)) > 0",
            name="ck_talent_recommendation_results_candidate_code",
        ),
        CheckConstraint(
            "length(document_sha256_snapshot) = 64",
            name="ck_talent_recommendation_results_document_sha256",
        ),
        CheckConstraint(
            "profile_version_snapshot >= 1 AND embedding_dimension_snapshot >= 1",
            name="ck_talent_recommendation_results_versions",
        ),
        CheckConstraint(
            "vector_rank >= 1 AND vector_rank <= 50",
            name="ck_talent_recommendation_results_vector_rank",
        ),
        CheckConstraint(
            "similarity_score >= -1 AND similarity_score <= 1",
            name="ck_talent_recommendation_results_similarity",
        ),
        CheckConstraint(
            "processing_attempt_count >= 0",
            name="ck_talent_recommendation_results_attempt_count",
        ),
        ForeignKeyConstraint(
            ["candidate_profile_id", "document_id", "profile_version_snapshot"],
            [
                "candidate_profiles.id",
                "candidate_profiles.document_id",
                "candidate_profiles.version_number",
            ],
            name="fk_talent_recommendation_results_profile_snapshot",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "ai_score IS NULL OR (ai_score >= 0 AND ai_score <= 100)",
            name="ck_talent_recommendation_results_ai_score",
        ),
        CheckConstraint(
            "ai_group IS NULL OR ai_group IN ('passed', 'low_match', 'auto_rejected')",
            name="ck_talent_recommendation_results_ai_group",
        ),
        CheckConstraint(
            "(status = 'completed' AND ai_score IS NOT NULL AND ai_group IS NOT NULL "
            "AND failure_code IS NULL AND exclusion_code IS NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status = 'failed' AND failure_code IS NOT NULL "
            "AND length(trim(failure_code)) > 0 "
            "AND exclusion_code IS NULL AND completed_at IS NOT NULL) OR "
            "(status = 'excluded' AND exclusion_code IS NOT NULL "
            "AND length(trim(exclusion_code)) > 0 "
            "AND failure_code IS NULL AND completed_at IS NOT NULL) OR "
            "(status IN ('retrieved', 'rescoring') AND failure_code IS NULL "
            "AND exclusion_code IS NULL AND completed_at IS NULL)",
            name="ck_talent_recommendation_results_terminal_contract",
        ),
        CheckConstraint(
            "(resolved_candidate_id = candidate_id AND candidate_merged_at IS NULL) OR "
            "(resolved_candidate_id <> candidate_id AND candidate_merged_at IS NOT NULL)",
            name="ck_talent_recommendation_results_candidate_resolution",
        ),
        CheckConstraint(
            "(document_stale = false AND profile_stale = false "
            "AND embedding_stale = false AND stale_at IS NULL) OR "
            "((document_stale = true OR profile_stale = true OR embedding_stale = true) "
            "AND stale_at IS NOT NULL)",
            name="ck_talent_recommendation_results_stale",
        ),
        UniqueConstraint(
            "run_id",
            "candidate_id",
            name="uq_talent_recommendation_results_run_candidate",
        ),
        UniqueConstraint(
            "run_id",
            "vector_rank",
            name="uq_talent_recommendation_results_run_rank",
        ),
        Index(
            "ix_talent_recommendation_results_run_status",
            "run_id",
            "status",
        ),
    )

    run: Mapped[TalentRecommendationRun] = relationship(back_populates="results")
    candidate: Mapped[Candidate] = relationship(foreign_keys=[candidate_id])
    resolved_candidate: Mapped[Candidate] = relationship(foreign_keys=[resolved_candidate_id])
    document: Mapped[ResumeDocument] = relationship(foreign_keys=[document_id])
    candidate_profile: Mapped[CandidateProfile] = relationship(foreign_keys=[candidate_profile_id])


class TalentRecommendationRunEvent(Base):
    __tablename__ = "talent_recommendation_run_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("talent_recommendation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor_username_snapshot: Mapped[str | None] = mapped_column(String(64))
    actor_display_name_snapshot: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({TALENT_RECOMMENDATION_EVENT_TYPE_SQL})",
            name="ck_talent_recommendation_run_events_type",
        ),
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({TALENT_RECOMMENDATION_RUN_STATUS_SQL})",
            name="ck_talent_recommendation_run_events_from_status",
        ),
        CheckConstraint(
            f"to_status IS NULL OR to_status IN ({TALENT_RECOMMENDATION_RUN_STATUS_SQL})",
            name="ck_talent_recommendation_run_events_to_status",
        ),
        CheckConstraint(
            "sequence_number >= 1",
            name="ck_talent_recommendation_run_events_sequence",
        ),
        UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_talent_recommendation_run_events_sequence",
        ),
        UniqueConstraint(
            "run_id",
            "idempotency_key",
            name="uq_talent_recommendation_run_events_idempotency",
        ),
    )

    run: Mapped[TalentRecommendationRun] = relationship(back_populates="events")
    actor_user: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])


_RUN_IMMUTABLE_FIELDS = (
    "job_id",
    "criteria_version_id",
    "created_by_username_snapshot",
    "created_by_display_name_snapshot",
    "idempotency_key",
    "ai_input_mode",
    "recall_limit",
    "rescore_limit",
    "criteria_snapshot",
    "embedding_model_snapshot",
    "ai_model_snapshot",
    "prompt_version_snapshot",
)

_RESULT_IMMUTABLE_SNAPSHOT_FIELDS = (
    "run_id",
    "candidate_id",
    "candidate_code_snapshot",
    "candidate_name_snapshot",
    "document_id",
    "document_sha256_snapshot",
    "document_updated_at_snapshot",
    "candidate_profile_id",
    "profile_version_snapshot",
    "embedding_model_snapshot",
    "embedding_version_snapshot",
    "embedding_dimension_snapshot",
    "vector_rank",
    "similarity_score",
    "matched_group_ids",
    "matched_chunks",
)

_RESULT_COMPLETED_FIELDS = (
    "status",
    "ai_score",
    "ai_group",
    "ai_dimension_scores",
    "ai_evidence",
    "ai_model_snapshot",
    "prompt_version_snapshot",
    "completed_at",
)


def _changed_fields(target: object, field_names: tuple[str, ...]) -> list[str]:
    state = inspect(target)
    return [
        field_name for field_name in field_names if state.attrs[field_name].history.has_changes()
    ]


@event.listens_for(TalentRecommendationRun, "before_update")
def _protect_run_snapshot(
    _mapper: object,
    _connection: object,
    target: TalentRecommendationRun,
) -> None:
    changed = _changed_fields(target, _RUN_IMMUTABLE_FIELDS)
    if changed:
        raise ValueError(f"推荐运行输入快照不可修改：{', '.join(changed)}")


@event.listens_for(TalentRecommendationRunGroup, "before_update")
def _protect_group_snapshot(
    _mapper: object,
    _connection: object,
    target: TalentRecommendationRunGroup,
) -> None:
    raise ValueError("推荐运行的人才组快照不可修改")


@event.listens_for(TalentRecommendationRunCandidate, "before_update")
def _protect_candidate_snapshot(
    _mapper: object,
    _connection: object,
    target: TalentRecommendationRunCandidate,
) -> None:
    raise ValueError("推荐运行的候选人输入快照不可修改")


@event.listens_for(TalentRecommendationResult, "before_update")
def _protect_result_snapshot(
    _mapper: object,
    _connection: object,
    target: TalentRecommendationResult,
) -> None:
    changed = _changed_fields(target, _RESULT_IMMUTABLE_SNAPSHOT_FIELDS)
    if changed:
        raise ValueError(f"推荐结果输入快照不可修改：{', '.join(changed)}")

    state = inspect(target)
    status_history = state.attrs.status.history
    was_completed = (bool(status_history.deleted) and status_history.deleted[0] == "completed") or (
        not status_history.has_changes() and target.status == "completed"
    )
    if was_completed:
        completed_changes = _changed_fields(target, _RESULT_COMPLETED_FIELDS)
        if completed_changes:
            raise ValueError(f"已完成推荐结果不可覆盖：{', '.join(completed_changes)}")


@event.listens_for(TalentRecommendationRunEvent, "before_update")
def _protect_run_event_update(
    _mapper: object,
    _connection: object,
    target: TalentRecommendationRunEvent,
) -> None:
    raise ValueError("推荐运行事件不可修改")


@event.listens_for(TalentRecommendationRunEvent, "before_delete")
def _protect_run_event_delete(
    _mapper: object,
    _connection: object,
    target: TalentRecommendationRunEvent,
) -> None:
    raise ValueError("推荐运行事件不可删除")
