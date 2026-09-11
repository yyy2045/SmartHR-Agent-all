import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.config import settings
from app.database import get_db
from app.models import RecruitmentKnowledgeDocument, User
from app.schemas.recruitment_knowledge import (
    RecruitmentKnowledgeCategory,
    RecruitmentKnowledgeChunkResponse,
    RecruitmentKnowledgeDocumentDetailResponse,
    RecruitmentKnowledgeDocumentListItem,
    RecruitmentKnowledgeDocumentListResponse,
    RecruitmentKnowledgeDocumentResponse,
    RecruitmentKnowledgeDocumentStatus,
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
    current_version_chunk_stats,
    load_recruitment_knowledge_document,
    parse_and_store_knowledge_upload,
    retrieve_recruitment_knowledge,
)
from app.services.recruitment_knowledge import (
    list_recruitment_knowledge_documents as list_knowledge_documents,
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
    if error.code == "document_not_found":
        return status.HTTP_404_NOT_FOUND
    if error.code == "document_not_visible":
        return status.HTTP_403_FORBIDDEN
    if error.code == "document_archived":
        return status.HTTP_409_CONFLICT
    return status.HTTP_422_UNPROCESSABLE_ENTITY


def _document_list_item(
    document: RecruitmentKnowledgeDocument,
    stats: dict[str, int],
) -> RecruitmentKnowledgeDocumentListItem:
    current = document.current_version
    return RecruitmentKnowledgeDocumentListItem(
        id=document.id,
        title=document.title,
        summary=document.summary,
        category=document.category,
        tags=document.tags,
        visibility_scope=document.visibility_scope,
        related_job_id=document.related_job_id,
        status=document.status,
        current_version_number=document.current_version_number,
        resource_version=document.resource_version,
        created_at=document.created_at,
        updated_at=document.updated_at,
        version_count=len(document.versions),
        current_source_type=current.source_type if current else None,
        current_source_filename=current.source_filename if current else None,
        chunk_count=stats.get("chunk_count", 0),
        chunk_completed=stats.get("completed", 0),
        chunk_failed=stats.get("failed", 0),
        chunk_pending=stats.get("pending", 0),
        chunk_processing=stats.get("processing", 0),
        embedding_enabled=settings.embedding_enabled,
    )


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


@router.get("/documents", response_model=RecruitmentKnowledgeDocumentListResponse)
def list_recruitment_knowledge_document_items(
    current_user: CurrentUser,
    db: DbSession,
    category: RecruitmentKnowledgeCategory | None = None,
    status: RecruitmentKnowledgeDocumentStatus | None = None,
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RecruitmentKnowledgeDocumentListResponse:
    total, documents = list_knowledge_documents(
        db,
        actor=current_user,
        category=category,
        status=status,
        query=q,
        limit=limit,
        offset=offset,
    )
    stats = current_version_chunk_stats(db, [document.id for document in documents])
    items = [_document_list_item(document, stats.get(document.id, {})) for document in documents]
    return RecruitmentKnowledgeDocumentListResponse(total=total, items=items)


@router.get(
    "/documents/{document_id}",
    response_model=RecruitmentKnowledgeDocumentDetailResponse,
)
def get_recruitment_knowledge_document_detail(
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> RecruitmentKnowledgeDocumentDetailResponse:
    try:
        document = load_recruitment_knowledge_document(
            db,
            document_id=document_id,
            actor=current_user,
        )
    except RecruitmentKnowledgeError as error:
        raise HTTPException(status_code=_error_status(error), detail=error.message) from error
    current = document.current_version
    chunks = list(current.chunks) if current else []
    return RecruitmentKnowledgeDocumentDetailResponse(
        id=document.id,
        title=document.title,
        summary=document.summary,
        category=document.category,
        tags=document.tags,
        visibility_scope=document.visibility_scope,
        related_job_id=document.related_job_id,
        status=document.status,
        current_version_number=document.current_version_number,
        resource_version=document.resource_version,
        created_at=document.created_at,
        updated_at=document.updated_at,
        versions=[
            RecruitmentKnowledgeVersionResponse.model_validate(version)
            for version in document.versions
        ],
        raw_text=current.raw_text if current else None,
        source_type=current.source_type if current else None,
        source_filename=current.source_filename if current else None,
        mime_type=current.mime_type if current else None,
        parser_name=current.parser_name if current else None,
        current_chunks=[
            RecruitmentKnowledgeChunkResponse.model_validate(chunk) for chunk in chunks
        ],
        embedding_enabled=settings.embedding_enabled,
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
    tags: Annotated[list[str] | None, Form()] = None,
    visibility_scope: Annotated[str, Form()] = "all_internal",
    related_job_id: Annotated[uuid.UUID | None, Form()] = None,
    force_ocr: Annotated[bool | None, Form()] = None,
    model_version: Annotated[str | None, Form()] = None,
) -> RecruitmentKnowledgeDocumentVersionCreateResponse:
    _ensure_knowledge_maintainer(current_user)
    try:
        parsed = await parse_and_store_knowledge_upload(
            file,
            storage_root=settings.file_storage_root,
            max_size_mb=settings.max_knowledge_file_size_mb,
            force_ocr=force_ocr,
            model_version=model_version,
        )
        payload = RecruitmentKnowledgeDocumentVersionCreateRequest(
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
