import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import AdministratorUser, CurrentUser
from app.database import get_db
from app.models import Role, User, UserRole
from app.schemas.auth import RoleKey
from app.schemas.user import (
    ManagedUserResponse,
    PasswordResetRequest,
    UserCreate,
    UserOptionResponse,
    UserUpdate,
)
from app.services.audit import record_audit
from app.services.security import hash_password

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _with_roles():
    return selectinload(User.role_assignments).selectinload(UserRole.role)


def _get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id).options(_with_roles()))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


def _get_roles(db: Session, role_keys: list[str]) -> dict[str, Role]:
    roles = {
        role.key: role
        for role in db.scalars(select(Role).where(Role.key.in_(set(role_keys))))
    }
    if set(roles) != set(role_keys):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="角色无效")
    return roles


def _active_administrator_count(db: Session) -> int:
    return db.scalar(
        select(func.count(User.id))
        .select_from(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.is_active.is_(True), Role.key == "administrator")
    ) or 0


def _ensure_not_last_administrator(
    db: Session,
    user: User,
    *,
    next_is_active: bool,
    next_role_keys: set[str],
) -> None:
    currently_active_administrator = user.is_active and user.has_role("administrator")
    remains_active_administrator = next_is_active and "administrator" in next_role_keys
    if (
        currently_active_administrator
        and not remains_active_administrator
        and _active_administrator_count(db) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="不能停用或移除最后一名有效企业管理员",
        )


@router.get("", response_model=list[ManagedUserResponse])
def list_users(_: AdministratorUser, db: DbSession) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .options(_with_roles())
            .order_by(User.is_active.desc(), User.created_at.asc())
        )
    )


@router.get("/options", response_model=list[UserOptionResponse])
def list_user_options(
    current_user: CurrentUser,
    db: DbSession,
    role: Annotated[RoleKey, Query()],
) -> list[User]:
    if not current_user.has_role("administrator", "recruiter"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色不能查看职位负责人选项",
        )
    return list(
        db.scalars(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.is_active.is_(True), Role.key == role)
            .options(_with_roles())
            .order_by(User.display_name, User.username)
        )
    )


@router.post("", response_model=ManagedUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    administrator: AdministratorUser,
    db: DbSession,
) -> User:
    if db.scalar(select(User.id).where(User.username == payload.username)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    roles = _get_roles(db, list(payload.roles))
    user = User(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=hash_password(payload.temporary_password.get_secret_value()),
        must_change_password=True,
        role_assignments=[
            UserRole(role=roles[key], assigned_by_id=administrator.id)
            for key in payload.roles
        ],
    )
    db.add(user)
    db.flush()
    record_audit(
        db,
        action="user.created",
        target_type="user",
        target_id=user.id,
        result="success",
        actor=administrator,
        details={"username": user.username, "roles": sorted(payload.roles)},
    )
    db.commit()
    return _get_user(db, user.id)


@router.patch("/{user_id}", response_model=ManagedUserResponse)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    administrator: AdministratorUser,
    db: DbSession,
) -> User:
    user = _get_user(db, user_id)
    previous_roles = set(user.role_keys)
    next_roles = set(payload.roles) if payload.roles is not None else previous_roles
    next_is_active = payload.is_active if payload.is_active is not None else user.is_active
    _ensure_not_last_administrator(
        db,
        user,
        next_is_active=next_is_active,
        next_role_keys=next_roles,
    )

    session_security_changed = False
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        session_security_changed = True
    if payload.roles is not None and next_roles != previous_roles:
        roles = _get_roles(db, list(payload.roles))
        user.role_assignments = [
            UserRole(role=roles[key], assigned_by_id=administrator.id)
            for key in payload.roles
        ]
        session_security_changed = True
    if session_security_changed:
        user.session_version += 1

    record_audit(
        db,
        action="user.updated",
        target_type="user",
        target_id=user.id,
        result="success",
        actor=administrator,
        details={
            "display_name_changed": payload.display_name is not None,
            "is_active": user.is_active,
            "roles": sorted(next_roles),
            "session_invalidated": session_security_changed,
        },
    )
    db.commit()
    return _get_user(db, user.id)


@router.post("/{user_id}/reset-password", response_model=ManagedUserResponse)
def reset_password(
    user_id: uuid.UUID,
    payload: PasswordResetRequest,
    administrator: AdministratorUser,
    db: DbSession,
) -> User:
    user = _get_user(db, user_id)
    user.password_hash = hash_password(payload.temporary_password.get_secret_value())
    user.must_change_password = True
    user.session_version += 1
    record_audit(
        db,
        action="user.password_reset",
        target_type="user",
        target_id=user.id,
        result="success",
        actor=administrator,
        details={"session_invalidated": True},
    )
    db.commit()
    return _get_user(db, user.id)
