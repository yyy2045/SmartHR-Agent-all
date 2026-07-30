from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.schemas.message import CommunicationPreviewRequest, CommunicationPreviewResponse
from app.services.message_preview import MessagePreviewError, preview_communication

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/preview", response_model=CommunicationPreviewResponse)
def preview_communication_message(
    payload: CommunicationPreviewRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CommunicationPreviewResponse:
    try:
        return preview_communication(db, payload=payload, actor=current_user)
    except MessagePreviewError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
