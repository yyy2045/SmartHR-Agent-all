from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.redis_client import get_session_store
from app.services.session_store import SessionStore


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> User:
    token = request.cookies.get(settings.app_session_cookie)
    user_id = session_store.get_user_id(token) if token else None
    user = db.get(User, user_id) if user_id else None

    if user is None or not user.is_active:
        if token:
            session_store.delete(token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Session"},
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
