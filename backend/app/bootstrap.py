import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import SessionLocal
from app.models import Role, User, UserRole
from app.models.user import ROLE_LABELS
from app.services.security import hash_password

logger = logging.getLogger(__name__)


def ensure_initial_recruiter() -> None:
    username = settings.initial_recruiter_username.strip().lower()
    if not username:
        raise RuntimeError("INITIAL_RECRUITER_USERNAME 不能为空")
    if settings.is_production and settings.initial_recruiter_password == "change-me-before-use":
        raise RuntimeError("生产环境必须配置安全的 INITIAL_RECRUITER_PASSWORD")

    with SessionLocal() as db:
        roles = {role.key: role for role in db.scalars(select(Role))}
        for key, display_name in ROLE_LABELS.items():
            if key not in roles:
                role = Role(key=key, display_name=display_name)
                db.add(role)
                roles[key] = role
        db.flush()

        existing_user = db.scalar(
            select(User)
            .where(User.username == username)
            .options(selectinload(User.role_assignments).selectinload(UserRole.role))
        )
        if existing_user is None:
            existing_user = User(
                username=username,
                password_hash=hash_password(settings.initial_recruiter_password),
                display_name=settings.initial_recruiter_display_name.strip() or "招聘专员",
            )
            db.add(existing_user)
            db.flush()
            logger.info("已初始化招聘专员账号：%s", username)

        assigned_keys = set(existing_user.role_keys)
        for key in ("administrator", "recruiter"):
            if key not in assigned_keys:
                existing_user.role_assignments.append(UserRole(role=roles[key]))
        db.commit()
