from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.bootstrap import ensure_initial_recruiter
from app.config import settings
from app.database import SessionLocal
from app.services.batch_deletion import reconcile_deletion_staging
from app.services.message_template_defaults import ensure_default_message_templates


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.file_storage_root.mkdir(parents=True, exist_ok=True)
    ensure_initial_recruiter()
    ensure_default_message_templates()
    reconcile_deletion_staging(settings.file_storage_root, SessionLocal)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "running",
        "docs": "/docs",
    }
