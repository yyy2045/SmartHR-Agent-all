from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.redis_client import get_session_store
from app.services.session_store import SessionStore


def get_authenticated_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> User:
    token = request.cookies.get(settings.app_session_cookie)
    identity = session_store.get_identity(token) if token else None
    user = db.get(User, identity.user_id) if identity else None

    if (
        user is None
        or not user.is_active
        or identity is None
        or identity.session_version != user.session_version
    ):
        if token:
            session_store.delete(token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Session"},
        )

    return user


AuthenticatedUser = Annotated[User, Depends(get_authenticated_user)]


def get_current_user(user: AuthenticatedUser) -> User:
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="请先修改临时密码",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
