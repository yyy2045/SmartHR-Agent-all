import logging

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.services.security import hash_password

logger = logging.getLogger(__name__)


def ensure_initial_recruiter() -> None:
    username = settings.initial_recruiter_username.strip().lower()
    if not username:
        raise RuntimeError("INITIAL_RECRUITER_USERNAME 不能为空")
    if settings.is_production and settings.initial_recruiter_password == "change-me-before-use":
        raise RuntimeError("生产环境必须配置安全的 INITIAL_RECRUITER_PASSWORD")

    with SessionLocal() as db:
        existing_user = db.scalar(select(User).where(User.username == username))
        if existing_user is not None:
            return

        db.add(
            User(
                username=username,
                password_hash=hash_password(settings.initial_recruiter_password),
                display_name=settings.initial_recruiter_display_name.strip() or "招聘专员",
            )
        )
        db.commit()
        logger.info("已初始化招聘专员账号：%s", username)
