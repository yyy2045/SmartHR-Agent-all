from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.batches import router as batches_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
api_router.include_router(batches_router, prefix="/jobs", tags=["batches"])
