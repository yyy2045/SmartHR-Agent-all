import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas.recruitment_knowledge import (
    RecruitmentKnowledgeBaseListResponse,
    RecruitmentKnowledgeBaseResponse,
    RecruitmentKnowledgeDocumentResponse,
    RecruitmentKnowledgeDocumentVersionCreateRequest,
    RecruitmentKnowledgeDocumentVersionCreateResponse,
    RecruitmentKnowledgeRetrievalRequest,
    RecruitmentKnowledgeRetrievalResponse,
    RecruitmentKnowledgeVersionResponse,
)
from app.services.embedding_client import EmbeddingClientError
from app.services.recruitment_knowledge import (
    RecruitmentKnowledgeError,
    create_manual_knowledge_version,
    ensure_default_knowledge_base,
    list_knowledge_bases,
    parse_and_store_knowledge_upload,
    retrieve_recruitment_knowledge,
)
from app.workers.dispatcher import enqueue_recruitment_knowledge_index

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _ensure_knowledge_maintainer(user: User) -> None:
    if not user.has_role("administrator", "recruiter"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员或招聘专员权限",
        )


def _error_status(error: RecruitmentKnowledgeError) -> int:
    if error.code in {"knowledge_base_not_found"}:
        return status.HTTP_404_NOT_FOUND
    if error.code in {"knowledge_base_inactive", "document_archived"}:
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_ENTITY


def _enqueue_if_enabled(version_id: uuid.UUID) -> str | None:
    if not settings.embedding_enabled:
        return None
    try:
        return enqueue_recruitment_knowledge_index(version_id)
    except Exception:
        return None


def _create_response(
    document,
    version,
    *,
    chunk_count: int,
    index_task_id: str | None,
) -> RecruitmentKnowledgeDocumentVersionCreateResponse:
    return RecruitmentKnowledgeDocumentVersionCreateResponse(
        document=RecruitmentKnowledgeDocumentResponse.model_validate(document),
        version=RecruitmentKnowledgeVersionResponse.model_validate(version),
        chunk_count=chunk_count,
        embedding_enabled=settings.embedding_enabled,
        index_task_id=index_task_id,
    )


@router.post("/retrieve", response_model=RecruitmentKnowledgeRetrievalResponse)
async def retrieve_recruitment_knowledge_context(
    payload: RecruitmentKnowledgeRetrievalRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentKnowledgeRetrievalResponse:
    if not settings.embedding_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Embedding 功能尚未启用，无法执行知识库检索",
        )
    try:
        return await retrieve_recruitment_knowledge(db, payload, actor=current_user)
    except EmbeddingClientError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.get("/bases", response_model=RecruitmentKnowledgeBaseListResponse)
def list_recruitment_knowledge_bases(
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentKnowledgeBaseListResponse:
    _ensure_knowledge_maintainer(current_user)
    if not list_knowledge_bases(db):
        ensure_default_knowledge_base(db, current_user)
        db.commit()
    return RecruitmentKnowledgeBaseListResponse(
        items=[
            RecruitmentKnowledgeBaseResponse.model_validate(item)
            for item in list_knowledge_bases(db)
        ]
    )


@router.post(
    "/documents/manual",
    response_model=RecruitmentKnowledgeDocumentVersionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_recruitment_knowledge_document(
    payload: RecruitmentKnowledgeDocumentVersionCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentKnowledgeDocumentVersionCreateResponse:
    _ensure_knowledge_maintainer(current_user)
    try:
        document, version, chunks = create_manual_knowledge_version(
            db,
            payload,
            actor=current_user,
        )
        db.commit()
        index_task_id = _enqueue_if_enabled(version.id)
    except RecruitmentKnowledgeError as error:
        db.rollback()
        raise HTTPException(status_code=_error_status(error), detail=error.message) from error
    return _create_response(
        document,
        version,
        chunk_count=len(chunks),
        index_task_id=index_task_id,
    )


@router.post(
    "/documents/upload",
    response_model=RecruitmentKnowledgeDocumentVersionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_recruitment_knowledge_document(
    current_user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[uuid.UUID, Form()],
    title: Annotated[str, Form()],
    category: Annotated[str, Form()],
    change_note: Annotated[str, Form()],
    summary: Annotated[str | None, Form()] = None,
    knowledge_base_id: Annotated[uuid.UUID | None, Form()] = None,
    tags: Annotated[list[str] | None, Form()] = None,
    visibility_scope: Annotated[str, Form()] = "all_internal",
    related_job_id: Annotated[uuid.UUID | None, Form()] = None,
) -> RecruitmentKnowledgeDocumentVersionCreateResponse:
    _ensure_knowledge_maintainer(current_user)
    try:
        parsed = await parse_and_store_knowledge_upload(
            file,
            storage_root=settings.file_storage_root,
            max_size_mb=settings.max_knowledge_file_size_mb,
        )
        payload = RecruitmentKnowledgeDocumentVersionCreateRequest(
            knowledge_base_id=knowledge_base_id,
            title=title,
            summary=summary,
            category=category,
            tags=tags or [],
            visibility_scope=visibility_scope,
            related_job_id=related_job_id,
            change_note=change_note,
            raw_text=parsed.raw_text,
            idempotency_key=idempotency_key,
        )
        document, version, chunks = create_manual_knowledge_version(
            db,
            payload,
            actor=current_user,
            source_type="upload",
            source_filename=parsed.source_filename,
            storage_key=parsed.storage_key,
            mime_type=parsed.mime_type,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            content_hash=parsed.content_hash,
        )
        db.commit()
        index_task_id = _enqueue_if_enabled(version.id)
    except RecruitmentKnowledgeError as error:
        db.rollback()
        raise HTTPException(status_code=_error_status(error), detail=error.message) from error
    return _create_response(
        document,
        version,
        chunk_count=len(chunks),
        index_task_id=index_task_id,
    )
