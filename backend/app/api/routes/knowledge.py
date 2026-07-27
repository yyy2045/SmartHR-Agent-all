import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.config import settings
from app.database import get_db
from app.models import CandidateProfile, ResumeDocument, ResumeEmbeddingChunk
from app.schemas.knowledge import (
    KnowledgeIndexStatusResponse,
    KnowledgeIndexTaskResponse,
)
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job
from app.workers.dispatcher import enqueue_knowledge_index

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _shared_document(
    db: Session,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    *,
    writable: bool = False,
) -> ResumeDocument:
    document = db.scalar(
        select(ResumeDocument)
        .where(ResumeDocument.id == document_id)
        .options(selectinload(ResumeDocument.batch))
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历文件不存在")
    if current_user.has_role("administrator", "recruiter"):
        return document
    job = get_visible_job(db, document.batch.job_id, current_user)
    if writable:
        ensure_job_writable(job, current_user)
    return document


def _latest_profile(db: Session, document_id: uuid.UUID) -> CandidateProfile:
    profile = db.scalar(
        select(CandidateProfile)
        .where(CandidateProfile.document_id == document_id)
        .order_by(CandidateProfile.version_number.desc())
        .limit(1)
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="简历尚未生成候选人结构化资料",
        )
    return profile


def _aggregate_status(chunks: list[ResumeEmbeddingChunk]) -> str:
    if not chunks:
        return "not_indexed"
    statuses = {chunk.status for chunk in chunks}
    if "processing" in statuses:
        return "processing"
    if "pending" in statuses:
        return "pending"
    if statuses == {"completed"}:
        return "completed"
    if statuses == {"failed"}:
        return "failed"
    return "partial_failure"


@router.get(
    "/documents/{document_id}/index",
    response_model=KnowledgeIndexStatusResponse,
)
def get_document_index_status(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> KnowledgeIndexStatusResponse:
    _shared_document(db, document_id, current_user)
    profile = _latest_profile(db, document_id)
    chunks = list(
        db.scalars(
            select(ResumeEmbeddingChunk)
            .where(
                ResumeEmbeddingChunk.candidate_profile_id == profile.id,
                ResumeEmbeddingChunk.embedding_model == settings.embedding_model,
                ResumeEmbeddingChunk.embedding_version == settings.embedding_version,
            )
            .order_by(
                ResumeEmbeddingChunk.chunk_type,
                ResumeEmbeddingChunk.chunk_index,
            )
        )
    )
    return KnowledgeIndexStatusResponse(
        document_id=document_id,
        candidate_profile_id=profile.id,
        profile_version=profile.version_number,
        status=_aggregate_status(chunks),
        embedding_enabled=settings.embedding_enabled,
        embedding_model=settings.embedding_model,
        embedding_dimension=settings.embedding_dimension,
        embedding_version=settings.embedding_version,
        chunk_count=len(chunks),
        completed_count=sum(chunk.status == "completed" for chunk in chunks),
        failed_count=sum(chunk.status == "failed" for chunk in chunks),
        chunks=chunks,
    )


@router.post(
    "/documents/{document_id}/index/rebuild",
    response_model=KnowledgeIndexTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def rebuild_document_index(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> KnowledgeIndexTaskResponse:
    document = _shared_document(db, document_id, current_user, writable=True)
    profile = _latest_profile(db, document_id)
    if not settings.embedding_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Embedding 功能尚未启用",
        )
    try:
        task_id = enqueue_knowledge_index(profile.id, force=True)
    except Exception as error:
        record_audit(
            db,
            action="knowledge.index_rebuild_requested",
            target_type="candidate_profile",
            target_id=profile.id,
            job_id=document.batch.job_id,
            batch_id=document.batch_id,
            result="failure",
            actor=current_user,
            details={"reason": "enqueue_failed"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="知识库索引任务创建失败，请稍后重试",
        ) from error
    record_audit(
        db,
        action="knowledge.index_rebuild_requested",
        target_type="candidate_profile",
        target_id=profile.id,
        job_id=document.batch.job_id,
        batch_id=document.batch_id,
        result="success",
        actor=current_user,
        details={
            "profile_version": profile.version_number,
            "embedding_model": settings.embedding_model,
            "embedding_version": settings.embedding_version,
        },
    )
    db.commit()
    return KnowledgeIndexTaskResponse(
        status="queued",
        document_id=document.id,
        candidate_profile_id=profile.id,
        profile_version=profile.version_number,
        task_id=task_id,
    )
