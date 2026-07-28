from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.batches import router as batches_router
from app.api.routes.candidate_processes import router as candidate_processes_router
from app.api.routes.candidate_versions import router as candidate_versions_router
from app.api.routes.candidates import router as candidates_router
from app.api.routes.health import router as health_router
from app.api.routes.interview_evaluations import router as interview_evaluations_router
from app.api.routes.interview_plans import router as interview_plans_router
from app.api.routes.interview_reports import router as interview_reports_router
from app.api.routes.interview_schedules import router as interview_schedules_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.offer_portal import router as offer_portal_router
from app.api.routes.offers import router as offers_router
from app.api.routes.onboardings import router as onboardings_router
from app.api.routes.recruitment_requests import router as recruitment_requests_router
from app.api.routes.screening_results import router as screening_results_router
from app.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(candidates_router, prefix="/candidates", tags=["candidates"])
api_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(offers_router, tags=["offers"])
api_router.include_router(onboardings_router, tags=["onboardings"])
api_router.include_router(
    offer_portal_router,
    prefix="/portal/offers",
    tags=["offer-portal"],
)
api_router.include_router(
    recruitment_requests_router,
    prefix="/recruitment-requests",
    tags=["recruitment-requests"],
)
api_router.include_router(
    interview_evaluations_router,
    prefix="/jobs",
    tags=["interview-evaluations"],
)
api_router.include_router(
    interview_reports_router,
    prefix="/jobs",
    tags=["interview-reports"],
)
api_router.include_router(
    interview_plans_router,
    prefix="/jobs",
    tags=["interview-plans"],
)
api_router.include_router(
    interview_schedules_router,
    prefix="/jobs",
    tags=["interview-schedules"],
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
