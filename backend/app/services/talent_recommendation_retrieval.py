from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import SessionLocal
from app.models import (
    Candidate,
    CandidateProfile,
    JobApplication,
    ResumeEmbeddingChunk,
    TalentRecommendationResult,
    TalentRecommendationRun,
)
from app.services.audit import record_audit
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingConfigurationError,
    EmbeddingRequestTimeout,
    EmbeddingResponseValidationError,
    EmbeddingUpstreamError,
    get_embedding_client,
)
from app.services.knowledge_index import index_candidate_profile
from app.services.talent_recommendation import (
    _append_event,
    _find_event,
    get_run_for_update,
)

SessionFactory = sessionmaker[Session]
IndexProfile = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class CandidateResumeChoice:
    candidate_id: uuid.UUID
    candidate_code: str
    candidate_name: str | None
    document_id: uuid.UUID
    document_sha256: str
    document_updated_at: datetime
    profile_id: uuid.UUID
    profile_version: int
    group_ids: tuple[uuid.UUID, ...]
    embedding_model: str
    embedding_version: str
    embedding_dimension: int


@dataclass(frozen=True)
class MatchedChunk:
    chunk_type: str
    chunk_index: int
    quote: str
    source_segment_keys: tuple[str, ...]
    similarity_score: float


@dataclass(frozen=True)
class VectorSearchMatch:
    profile_id: uuid.UUID
    similarity_score: float
    chunks: tuple[MatchedChunk, ...]


class TalentRecommendationRetrievalError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_retrieval_query(criteria_snapshot: dict[str, object]) -> str:
    lines = ["职位人才检索标准"]
    hard_requirements = criteria_snapshot.get("hard_requirements")
    if isinstance(hard_requirements, list):
        for item in hard_requirements:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            expected = str(item.get("expected_value") or "").strip()
            description = str(item.get("description") or "").strip()
            text = "；".join(value for value in (title, expected, description) if value)
            if text:
                lines.append(f"必备条件：{text}")

    scoring_dimensions = criteria_snapshot.get("scoring_dimensions")
    if isinstance(scoring_dimensions, list):
        for item in scoring_dimensions:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            weight = item.get("weight_percent")
            text = "；".join(value for value in (name, description) if value)
            if text:
                suffix = f"；权重 {weight}%" if isinstance(weight, int) else ""
                lines.append(f"评估维度：{text}{suffix}")

    if len(lines) == 1:
        raise TalentRecommendationRetrievalError(
            "criteria_snapshot_empty",
            "已确认筛选标准没有可用于向量检索的内容",
        )
    return "\n".join(lines)[:8_000]


def _load_candidate_choices(run: TalentRecommendationRun) -> list[CandidateResumeChoice]:
    if len(run.candidate_snapshots) != run.scope_candidate_count:
        raise TalentRecommendationRetrievalError(
            "candidate_scope_snapshot_missing",
            "推荐运行缺少完整的候选人输入快照，请重新创建任务",
        )
    return [
        CandidateResumeChoice(
            candidate_id=item.candidate_id,
            candidate_code=item.candidate_code_snapshot,
            candidate_name=item.candidate_name_snapshot,
            document_id=item.document_id,
            document_sha256=item.document_sha256_snapshot,
            document_updated_at=item.document_updated_at_snapshot,
            profile_id=item.candidate_profile_id,
            profile_version=item.profile_version_snapshot,
            group_ids=tuple(uuid.UUID(value) for value in item.matched_group_ids),
            embedding_model=item.embedding_model_snapshot,
            embedding_version=item.embedding_version_snapshot,
            embedding_dimension=item.embedding_dimension_snapshot,
        )
        for item in run.candidate_snapshots
    ]


def _ready_profile_ids(
    db: Session,
    *,
    profile_ids: list[uuid.UUID],
    client: EmbeddingClient,
) -> set[uuid.UUID]:
    if not profile_ids:
        return set()
    return set(
        db.scalars(
            select(ResumeEmbeddingChunk.candidate_profile_id)
            .where(
                ResumeEmbeddingChunk.candidate_profile_id.in_(profile_ids),
                ResumeEmbeddingChunk.embedding_model == client.model,
                ResumeEmbeddingChunk.embedding_version == client.version,
                ResumeEmbeddingChunk.embedding_dimension == client.dimension,
                ResumeEmbeddingChunk.status == "completed",
                ResumeEmbeddingChunk.embedding.is_not(None),
            )
            .distinct()
        ).all()
    )


async def _ensure_current_indexes(
    choices: list[CandidateResumeChoice],
    *,
    task_id: str,
    session_factory: SessionFactory,
    client: EmbeddingClient,
    index_profile: IndexProfile,
) -> tuple[list[CandidateResumeChoice], int]:
    with session_factory() as db:
        ready = _ready_profile_ids(
            db,
            profile_ids=[choice.profile_id for choice in choices],
            client=client,
        )
    missing = [choice for choice in choices if choice.profile_id not in ready]
    excluded_count = 0
    for choice in missing:
        result = await index_profile(
            choice.profile_id,
            task_id=f"{task_id}:profile:{choice.profile_id}",
            force=False,
            session_factory=session_factory,
            embedding_client=client,
        )
        result_status = str(result.get("status") or "")
        if result_status in {"completed"}:
            continue
        if result_status in {"empty", "missing"}:
            excluded_count += 1
            continue
        if result_status == "failed":
            raise TalentRecommendationRetrievalError(
                str(result.get("code") or "embedding_index_failed"),
                str(result.get("message") or "候选人简历向量索引失败"),
            )
        raise TalentRecommendationRetrievalError(
            "embedding_index_not_ready",
            "候选人简历向量索引仍在处理中，请稍后重新创建推荐任务",
        )

    with session_factory() as db:
        ready = _ready_profile_ids(
            db,
            profile_ids=[choice.profile_id for choice in choices],
            client=client,
        )
    ready_choices = [choice for choice in choices if choice.profile_id in ready]
    excluded_count += len(choices) - len(ready_choices) - excluded_count
    return ready_choices, excluded_count


def search_candidate_vectors(
    db: Session,
    *,
    choices: list[CandidateResumeChoice],
    query_vector: list[float],
    client: EmbeddingClient,
    limit: int,
) -> list[VectorSearchMatch]:
    profile_ids = [choice.profile_id for choice in choices]
    if not profile_ids:
        return []
    distance = ResumeEmbeddingChunk.embedding.cosine_distance(query_vector)
    ranked = db.execute(
        select(
            ResumeEmbeddingChunk.candidate_profile_id,
            func.min(distance).label("best_distance"),
        )
        .where(
            ResumeEmbeddingChunk.candidate_profile_id.in_(profile_ids),
            ResumeEmbeddingChunk.embedding_model == client.model,
            ResumeEmbeddingChunk.embedding_version == client.version,
            ResumeEmbeddingChunk.embedding_dimension == client.dimension,
            ResumeEmbeddingChunk.status == "completed",
            ResumeEmbeddingChunk.embedding.is_not(None),
        )
        .group_by(ResumeEmbeddingChunk.candidate_profile_id)
        .order_by(func.min(distance), ResumeEmbeddingChunk.candidate_profile_id)
        .limit(limit)
    ).all()
    ranked_profile_ids = [row.candidate_profile_id for row in ranked]
    if not ranked_profile_ids:
        return []

    chunk_rows = db.execute(
        select(ResumeEmbeddingChunk, distance.label("distance"))
        .where(
            ResumeEmbeddingChunk.candidate_profile_id.in_(ranked_profile_ids),
            ResumeEmbeddingChunk.embedding_model == client.model,
            ResumeEmbeddingChunk.embedding_version == client.version,
            ResumeEmbeddingChunk.embedding_dimension == client.dimension,
            ResumeEmbeddingChunk.status == "completed",
            ResumeEmbeddingChunk.embedding.is_not(None),
        )
        .order_by(
            ResumeEmbeddingChunk.candidate_profile_id,
            distance,
            ResumeEmbeddingChunk.chunk_type,
            ResumeEmbeddingChunk.chunk_index,
        )
    ).all()
    chunks_by_profile: dict[uuid.UUID, list[MatchedChunk]] = defaultdict(list)
    for chunk, chunk_distance in chunk_rows:
        chunks = chunks_by_profile[chunk.candidate_profile_id]
        if len(chunks) >= 3:
            continue
        similarity = max(-1.0, min(1.0, 1.0 - float(chunk_distance)))
        chunks.append(
            MatchedChunk(
                chunk_type=chunk.chunk_type,
                chunk_index=chunk.chunk_index,
                quote=chunk.chunk_text[:500],
                source_segment_keys=tuple(chunk.source_segment_keys),
                similarity_score=round(similarity, 8),
            )
        )

    return [
        VectorSearchMatch(
            profile_id=row.candidate_profile_id,
            similarity_score=round(
                max(-1.0, min(1.0, 1.0 - float(row.best_distance))),
                8,
            ),
            chunks=tuple(chunks_by_profile[row.candidate_profile_id]),
        )
        for row in ranked
    ]


def _failure_details(error: Exception) -> tuple[str, str]:
    if isinstance(error, TalentRecommendationRetrievalError):
        return error.code, error.message
    if isinstance(error, EmbeddingConfigurationError):
        return "embedding_not_configured", str(error)
    if isinstance(error, EmbeddingRequestTimeout):
        return "embedding_timeout", str(error)
    if isinstance(error, EmbeddingResponseValidationError):
        return "embedding_invalid_response", str(error)
    if isinstance(error, EmbeddingUpstreamError):
        return "embedding_upstream_failed", str(error)
    return "talent_retrieval_failed", "人才向量召回失败，请稍后重新创建推荐任务"


def _mark_failed(
    run_id: uuid.UUID,
    *,
    task_id: str,
    error: Exception,
    session_factory: SessionFactory,
) -> dict[str, Any]:
    failure_code, failure_message = _failure_details(error)
    with session_factory() as db:
        run = db.get(TalentRecommendationRun, run_id)
        if run is None:
            return {"status": "missing", "run_id": str(run_id)}
        run = get_run_for_update(db, job_id=run.job_id, run_id=run.id)
        if run.celery_task_id != task_id:
            return {"status": "superseded", "run_id": str(run.id)}
        if run.status == "cancelled":
            return {"status": "cancelled", "run_id": str(run.id)}
        previous_status = run.status
        run.status = "failed"
        run.failure_code = failure_code
        run.failure_summary = failure_message[:2_000]
        run.completed_at = datetime.now(UTC)
        run.resource_version += 1
        event_key = uuid.uuid5(run.id, f"retrieval-failed:{task_id}")
        if _find_event(db, run.id, event_key) is None:
            _append_event(
                db,
                run=run,
                idempotency_key=event_key,
                event_type="failed",
                from_status=previous_status,
                to_status="failed",
                details={"failure_code": failure_code},
                actor=None,
            )
        record_audit(
            db,
            action="talent_recommendation.retrieval_failed",
            target_type="talent_recommendation_run",
            target_id=run.id,
            job_id=run.job_id,
            result="failure",
            actor_username="celery-worker",
            details={"failure_code": failure_code},
        )
        db.commit()
    return {
        "status": "failed",
        "run_id": str(run_id),
        "failure_code": failure_code,
        "failure_message": failure_message,
    }


def _resolve_candidate(db: Session, candidate_id: uuid.UUID) -> Candidate | None:
    current_id = candidate_id
    visited: set[uuid.UUID] = set()
    for _ in range(20):
        if current_id in visited:
            return None
        visited.add(current_id)
        candidate = db.get(Candidate, current_id)
        if candidate is None:
            return None
        if candidate.status == "active":
            return candidate
        if candidate.merged_into_candidate_id is None:
            return None
        current_id = candidate.merged_into_candidate_id
    return None


def _snapshot_staleness(
    db: Session,
    *,
    choice: CandidateResumeChoice,
    resolved_candidate_id: uuid.UUID,
    client: EmbeddingClient,
) -> tuple[bool, bool, bool, datetime | None]:
    current_primary_document_id = db.scalar(
        select(JobApplication.primary_document_id)
        .where(
            JobApplication.candidate_id == resolved_candidate_id,
            JobApplication.status == "active",
            JobApplication.primary_document_id.is_not(None),
        )
        .order_by(JobApplication.updated_at.desc(), JobApplication.id.desc())
        .limit(1)
    )
    document_stale = current_primary_document_id != choice.document_id
    latest_profile = db.execute(
        select(CandidateProfile.id, CandidateProfile.version_number)
        .where(CandidateProfile.document_id == choice.document_id)
        .order_by(
            CandidateProfile.version_number.desc(),
            CandidateProfile.created_at.desc(),
        )
        .limit(1)
    ).first()
    profile_stale = latest_profile is None or (
        latest_profile.id != choice.profile_id
        or latest_profile.version_number != choice.profile_version
    )
    embedding_ready = db.scalar(
        select(
            exists().where(
                ResumeEmbeddingChunk.candidate_profile_id == choice.profile_id,
                ResumeEmbeddingChunk.embedding_model == client.model,
                ResumeEmbeddingChunk.embedding_version == client.version,
                ResumeEmbeddingChunk.embedding_dimension == client.dimension,
                ResumeEmbeddingChunk.status == "completed",
                ResumeEmbeddingChunk.embedding.is_not(None),
            )
        )
    )
    embedding_stale = not bool(embedding_ready)
    stale_at = (
        datetime.now(UTC)
        if document_stale or profile_stale or embedding_stale
        else None
    )
    return document_stale, profile_stale, embedding_stale, stale_at


async def retrieve_talent_recommendations(
    run_id: uuid.UUID,
    *,
    task_id: str,
    session_factory: SessionFactory = SessionLocal,
    embedding_client: EmbeddingClient | None = None,
    index_profile: IndexProfile = index_candidate_profile,
    vector_search: Callable[..., list[VectorSearchMatch]] = search_candidate_vectors,
) -> dict[str, Any]:
    client = embedding_client or get_embedding_client()
    with session_factory() as db:
        run = db.get(TalentRecommendationRun, run_id)
        if run is None:
            return {"status": "missing", "run_id": str(run_id)}
        run = get_run_for_update(db, job_id=run.job_id, run_id=run.id)
        if run.celery_task_id != task_id:
            return {"status": "superseded", "run_id": str(run.id)}
        if run.status == "cancelled":
            return {"status": "cancelled", "run_id": str(run.id)}
        if run.status == "rescoring" and run.retrieved_count > 0:
            return {
                "status": "retrieved",
                "run_id": str(run.id),
                "retrieved_count": run.retrieved_count,
                "skipped": True,
            }
        if run.status not in {"queued", "retrieving"}:
            return {"status": run.status, "run_id": str(run.id)}
        if run.criteria_stale:
            db.rollback()
            return _mark_failed(
                run.id,
                task_id=task_id,
                error=TalentRecommendationRetrievalError(
                    "criteria_stale_before_retrieval",
                    "职位筛选标准已经变化，请创建新的推荐任务",
                ),
                session_factory=session_factory,
            )
        if run.embedding_model_snapshot != client.model:
            db.rollback()
            return _mark_failed(
                run.id,
                task_id=task_id,
                error=TalentRecommendationRetrievalError(
                    "embedding_configuration_changed",
                    "Embedding 模型配置已变化，请创建新的推荐任务",
                ),
                session_factory=session_factory,
            )
        try:
            choices = _load_candidate_choices(run)
        except TalentRecommendationRetrievalError as error:
            db.rollback()
            return _mark_failed(
                run.id,
                task_id=task_id,
                error=error,
                session_factory=session_factory,
            )
        if any(
            choice.embedding_model != client.model
            or choice.embedding_version != client.version
            or choice.embedding_dimension != client.dimension
            for choice in choices
        ):
            db.rollback()
            return _mark_failed(
                run.id,
                task_id=task_id,
                error=TalentRecommendationRetrievalError(
                    "embedding_configuration_changed",
                    "Embedding 配置与推荐运行快照不一致，请创建新的推荐任务",
                ),
                session_factory=session_factory,
            )
        excluded_count = run.excluded_count
        query_text = build_retrieval_query(run.criteria_snapshot)
        query_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest()
        if run.status == "queued":
            run.status = "retrieving"
            run.started_at = datetime.now(UTC)
            run.resource_version += 1
            event_key = uuid.uuid5(run.id, f"retrieval-started:{task_id}")
            if _find_event(db, run.id, event_key) is None:
                _append_event(
                    db,
                    run=run,
                    idempotency_key=event_key,
                    event_type="retrieval_started",
                    from_status="queued",
                    to_status="retrieving",
                    details={
                        "query_text_sha256": query_hash,
                        "query_text_summary": query_text[:1_000],
                    },
                    actor=None,
                )
            record_audit(
                db,
                action="talent_recommendation.retrieval_started",
                target_type="talent_recommendation_run",
                target_id=run.id,
                job_id=run.job_id,
                result="success",
                actor_username="celery-worker",
                details={"query_text_sha256": query_hash},
            )
        db.commit()

    try:
        vectors = await client.embed([query_text])
        if len(vectors) != 1 or len(vectors[0]) != client.dimension:
            raise EmbeddingResponseValidationError("职位查询向量维度不正确")
        query_vector = vectors[0]
        choices, index_excluded = await _ensure_current_indexes(
            choices,
            task_id=task_id,
            session_factory=session_factory,
            client=client,
            index_profile=index_profile,
        )
        excluded_count += index_excluded
        with session_factory() as db:
            matches = vector_search(
                db,
                choices=choices,
                query_vector=query_vector,
                client=client,
                limit=50,
            )
    except Exception as error:
        return _mark_failed(
            run_id,
            task_id=task_id,
            error=error,
            session_factory=session_factory,
        )

    choice_by_profile = {choice.profile_id: choice for choice in choices}
    with session_factory() as db:
        run = db.get(TalentRecommendationRun, run_id)
        if run is None:
            return {"status": "missing", "run_id": str(run_id)}
        run = get_run_for_update(db, job_id=run.job_id, run_id=run.id)
        if run.celery_task_id != task_id:
            return {"status": "superseded", "run_id": str(run.id)}
        if run.status == "cancelled":
            return {"status": "cancelled", "run_id": str(run.id)}
        if run.criteria_stale:
            db.rollback()
            return _mark_failed(
                run.id,
                task_id=task_id,
                error=TalentRecommendationRetrievalError(
                    "criteria_stale_during_retrieval",
                    "职位筛选标准在召回期间发生变化，请创建新的推荐任务",
                ),
                session_factory=session_factory,
            )
        if run.results:
            return {
                "status": "retrieved",
                "run_id": str(run.id),
                "retrieved_count": run.retrieved_count,
                "skipped": True,
            }

        resolved_matches: dict[
            uuid.UUID,
            tuple[VectorSearchMatch, CandidateResumeChoice, Candidate],
        ] = {}
        valid_match_count = 0
        for match in matches:
            choice = choice_by_profile.get(match.profile_id)
            if choice is None:
                continue
            resolved = _resolve_candidate(db, choice.candidate_id)
            if resolved is None:
                excluded_count += 1
                continue
            already_applied = db.scalar(
                select(
                    exists().where(
                        JobApplication.candidate_id == resolved.id,
                        JobApplication.job_id == run.job_id,
                        JobApplication.status == "active",
                    )
                )
            )
            if already_applied:
                excluded_count += 1
                continue
            valid_match_count += 1
            current = resolved_matches.get(resolved.id)
            if current is None or match.similarity_score > current[0].similarity_score:
                resolved_matches[resolved.id] = (match, choice, resolved)
        excluded_count += valid_match_count - len(resolved_matches)

        ranked_matches = sorted(
            resolved_matches.values(),
            key=lambda item: (-item[0].similarity_score, str(item[2].id)),
        )[: run.recall_limit]
        for rank, (match, choice, resolved) in enumerate(ranked_matches, start=1):
            merged = resolved.id != choice.candidate_id
            original_candidate = db.get(Candidate, choice.candidate_id)
            candidate_merged_at = None
            if merged:
                candidate_merged_at = (
                    original_candidate.merged_at
                    if original_candidate is not None and original_candidate.merged_at is not None
                    else datetime.now(UTC)
                )
            document_stale, profile_stale, embedding_stale, stale_at = (
                _snapshot_staleness(
                    db,
                    choice=choice,
                    resolved_candidate_id=resolved.id,
                    client=client,
                )
            )
            db.add(
                TalentRecommendationResult(
                    run_id=run.id,
                    candidate_id=choice.candidate_id,
                    resolved_candidate_id=resolved.id,
                    candidate_code_snapshot=choice.candidate_code,
                    candidate_name_snapshot=choice.candidate_name,
                    candidate_merged_at=candidate_merged_at,
                    document_id=choice.document_id,
                    document_sha256_snapshot=choice.document_sha256,
                    document_updated_at_snapshot=choice.document_updated_at,
                    candidate_profile_id=choice.profile_id,
                    profile_version_snapshot=choice.profile_version,
                    embedding_model_snapshot=client.model,
                    embedding_version_snapshot=client.version,
                    embedding_dimension_snapshot=client.dimension,
                    vector_rank=rank,
                    similarity_score=match.similarity_score,
                    matched_group_ids=[str(group_id) for group_id in choice.group_ids],
                    matched_chunks=[
                        {
                            "chunk_type": chunk.chunk_type,
                            "chunk_index": chunk.chunk_index,
                            "quote": chunk.quote,
                            "source_segment_keys": list(chunk.source_segment_keys),
                            "similarity_score": chunk.similarity_score,
                        }
                        for chunk in match.chunks
                    ],
                    status="retrieved",
                    ai_dimension_scores=[],
                    ai_evidence=[],
                    document_stale=document_stale,
                    profile_stale=profile_stale,
                    embedding_stale=embedding_stale,
                    stale_at=stale_at,
                )
            )

        previous_status = run.status
        run.retrieved_count = len(ranked_matches)
        run.excluded_count = excluded_count
        run.failure_code = None
        run.failure_summary = None
        run.status = "rescoring" if ranked_matches else "completed"
        run.completed_at = None if ranked_matches else datetime.now(UTC)
        run.resource_version += 1
        event_key = uuid.uuid5(run.id, f"retrieval-completed:{task_id}")
        if _find_event(db, run.id, event_key) is None:
            _append_event(
                db,
                run=run,
                idempotency_key=event_key,
                event_type="retrieval_completed",
                from_status=previous_status,
                to_status=run.status,
                details={
                    "retrieved_count": run.retrieved_count,
                    "excluded_count": run.excluded_count,
                    "embedding_model": client.model,
                    "embedding_version": client.version,
                },
                actor=None,
            )
        record_audit(
            db,
            action="talent_recommendation.retrieval_completed",
            target_type="talent_recommendation_run",
            target_id=run.id,
            job_id=run.job_id,
            result="success",
            actor_username="celery-worker",
            details={
                "retrieved_count": run.retrieved_count,
                "excluded_count": run.excluded_count,
            },
        )
        db.commit()
        return {
            "status": run.status,
            "run_id": str(run.id),
            "retrieved_count": run.retrieved_count,
            "excluded_count": run.excluded_count,
        }
