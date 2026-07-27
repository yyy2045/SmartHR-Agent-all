from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import AuthenticatedUser
from app.config import settings
from app.database import get_db
from app.models import User
from app.redis_client import get_session_store
from app.schemas.auth import ChangePasswordRequest, LoginRequest, UserResponse
from app.services.audit import record_audit
from app.services.security import hash_password, verify_password
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
        record_audit(
            db,
            action="auth.login",
            target_type="session",
            result="failure",
            actor=user,
            actor_username=username,
            details={"reason": "invalid_credentials"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    existing_token = request.cookies.get(settings.app_session_cookie)
    if existing_token:
        session_store.delete(existing_token)

    try:
        token = session_store.create(user.id, user.session_version)
    except Exception:
        record_audit(
            db,
            action="auth.login",
            target_type="session",
            result="failure",
            actor=user,
            details={"reason": "session_unavailable"},
        )
        db.commit()
        raise
    record_audit(
        db,
        action="auth.login",
        target_type="session",
        result="success",
        actor=user,
    )
    try:
        db.commit()
    except Exception:
        session_store.delete(token)
        raise
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
    db: Annotated[Session, Depends(get_db)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    token = request.cookies.get(settings.app_session_cookie)
    user_id = session_store.get_user_id(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if token:
        session_store.delete(token)
    record_audit(
        db,
        action="auth.logout",
        target_type="session",
        result="success",
        actor=user,
        details={"had_session": token is not None},
    )
    db.commit()
    response.delete_cookie(
        key=settings.app_session_cookie,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: AuthenticatedUser) -> User:
    return current_user


@router.post("/password", response_model=UserResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> User:
    if not verify_password(
        payload.current_password.get_secret_value(), current_user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码错误",
        )

    current_user.password_hash = hash_password(payload.new_password.get_secret_value())
    current_user.must_change_password = False
    current_user.session_version += 1
    record_audit(
        db,
        action="auth.password_changed",
        target_type="user",
        target_id=current_user.id,
        result="success",
        actor=current_user,
    )
    db.flush()

    new_token = session_store.create(current_user.id, current_user.session_version)
    try:
        db.commit()
    except Exception:
        session_store.delete(new_token)
        raise

    old_token = request.cookies.get(settings.app_session_cookie)
    if old_token:
        session_store.delete(old_token)
    response.set_cookie(
        key=settings.app_session_cookie,
        value=new_token,
        max_age=settings.app_session_expire_minutes * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return current_user
