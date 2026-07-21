from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import CurrentUser
from app.config import settings
from app.database import get_db
from app.models import User
from app.redis_client import get_session_store
from app.schemas.auth import LoginRequest, UserResponse
from app.services.security import verify_password
from app.services.session_store import SessionStore

router = APIRouter()


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> User:
    username = payload.username.strip().lower()
    user = db.scalar(select(User).where(User.username == username))
    password = payload.password.get_secret_value()

    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    existing_token = request.cookies.get(settings.app_session_cookie)
    if existing_token:
        session_store.delete(existing_token)

    token = session_store.create(user.id)
    response.set_cookie(
        key=settings.app_session_cookie,
        value=token,
        max_age=settings.app_session_expire_minutes * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    token = request.cookies.get(settings.app_session_cookie)
    if token:
        session_store.delete(token)
    response.delete_cookie(
        key=settings.app_session_cookie,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: CurrentUser) -> User:
    return current_user
