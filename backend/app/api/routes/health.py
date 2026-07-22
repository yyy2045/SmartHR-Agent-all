from typing import Annotated

from fastapi import APIRouter, Depends
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.redis_client import get_redis_client

router = APIRouter()


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(
    db: Annotated[Session, Depends(get_db)],
    redis_client: Annotated[Redis, Depends(get_redis_client)],
) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    redis_client.ping()
    return {"status": "ready", "database": "ok", "redis": "ok"}
