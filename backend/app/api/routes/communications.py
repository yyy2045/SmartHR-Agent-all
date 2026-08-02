import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.schemas.message import (
    CommunicationContextType,
    CommunicationCopyAuditRequest,
    CommunicationCopyAuditResponse,
    CommunicationCorrectionCreateRequest,
    CommunicationPreviewRequest,
    CommunicationPreviewResponse,
    CommunicationRecordCreateRequest,
    CommunicationRecordDetailResponse,
    CommunicationRecordListResponse,
    CommunicationRecordResponse,
)
from app.services.communications import (
    CommunicationServiceError,
    create_communication_record,
    create_correction,
    get_communication_detail,
    list_communications,
    record_copy_audit,
)
from app.services.message_preview import MessagePreviewError, preview_communication

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _raise_service_error(error: CommunicationServiceError | MessagePreviewError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@router.get("", response_model=CommunicationRecordListResponse)
def list_candidate_communications(
    current_user: CurrentUser,
    db: DbSession,
    context_type: CommunicationContextType | None = None,
    context_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CommunicationRecordListResponse:
    try:
        return list_communications(
            db,
            actor=current_user,
            context_type=context_type,
            context_id=context_id,
            application_id=application_id,
            limit=limit,
            offset=offset,
        )
    except CommunicationServiceError as error:
        _raise_service_error(error)


@router.post("", response_model=CommunicationRecordResponse, status_code=status.HTTP_201_CREATED)
def create_candidate_communication(
    payload: CommunicationRecordCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CommunicationRecordResponse:
    try:
        return create_communication_record(db, payload=payload, actor=current_user)
    except CommunicationServiceError as error:
        _raise_service_error(error)


@router.post("/copy-audit", response_model=CommunicationCopyAuditResponse)
def audit_copied_communication(
    payload: CommunicationCopyAuditRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CommunicationCopyAuditResponse:
    try:
        return record_copy_audit(db, payload=payload, actor=current_user)
    except CommunicationServiceError as error:
        _raise_service_error(error)


@router.get("/{record_id:uuid}", response_model=CommunicationRecordDetailResponse)
def get_candidate_communication(
    record_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> CommunicationRecordDetailResponse:
    try:
        return get_communication_detail(db, record_id=record_id, actor=current_user)
    except CommunicationServiceError as error:
        _raise_service_error(error)


@router.post(
    "/{record_id:uuid}/corrections",
    response_model=CommunicationRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def correct_candidate_communication(
    record_id: uuid.UUID,
    payload: CommunicationCorrectionCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CommunicationRecordResponse:
    try:
        return create_correction(db, record_id=record_id, payload=payload, actor=current_user)
    except CommunicationServiceError as error:
        _raise_service_error(error)


@router.post("/preview", response_model=CommunicationPreviewResponse)
def preview_communication_message(
    payload: CommunicationPreviewRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CommunicationPreviewResponse:
    try:
        return preview_communication(db, payload=payload, actor=current_user)
    except MessagePreviewError as error:
        _raise_service_error(error)