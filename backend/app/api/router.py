from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.batches import router as batches_router
from app.api.routes.candidate_processes import router as candidate_processes_router
from app.api.routes.candidate_versions import router as candidate_versions_router
from app.api.routes.health import router as health_router
from app.api.routes.interview_plans import router as interview_plans_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.screening_results import router as screening_results_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(
    interview_plans_router,
    prefix="/jobs",
    tags=["interview-plans"],
)
api_router.include_router(batches_router, prefix="/jobs", tags=["batches"])
api_router.include_router(
    candidate_versions_router,
    prefix="/jobs",
    tags=["candidate-versions"],
)
api_router.include_router(
    candidate_processes_router,
    prefix="/jobs",
    tags=["candidate-processes"],
)
api_router.include_router(
    screening_results_router,
    prefix="/jobs",
    tags=["screening-results"],
)
