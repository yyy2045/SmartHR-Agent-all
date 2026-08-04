import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import (
    AiEvaluationDataset,
    AiEvaluationErrorCase,
    AiEvaluationRun,
    User,
)
from app.schemas.ai_evaluation import (
    AiEvaluationDatasetListResponse,
    AiEvaluationDatasetResponse,
    AiEvaluationErrorCaseListResponse,
    AiEvaluationErrorCaseResponse,
    AiEvaluationErrorCaseUpdateRequest,
    AiEvaluationResultResponse,
    AiEvaluationRunCreateRequest,
    AiEvaluationRunDetailResponse,
    AiEvaluationRunListResponse,
    AiEvaluationRunResponse,
)
from app.services.ai_evaluation import (
    OfflineEvaluationOptions,
    ensure_default_resume_evaluation_dataset,
    run_offline_resume_evaluation,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]

RunStatusFilter = Literal["queued", "running", "succeeded", "failed", "cancelled"]
ErrorCaseStatusFilter = Literal["open", "resolved", "ignored"]


def _ensure_ai_evaluation_admin(user: User) -> None:
    if not user.has_role("administrator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要企业管理员权限",
        )


@router.get("/datasets", response_model=AiEvaluationDatasetListResponse)
def list_ai_evaluation_datasets(
    current_user: CurrentUser,
    db: DbSession,
) -> AiEvaluationDatasetListResponse:
    _ensure_ai_evaluation_admin(current_user)
    items = list(
        db.scalars(
            select(AiEvaluationDataset).order_by(
                AiEvaluationDataset.created_at.desc(),
                AiEvaluationDataset.id.desc(),
            )
        )
    )
    return AiEvaluationDatasetListResponse(
        items=[AiEvaluationDatasetResponse.model_validate(item) for item in items]
    )


@router.post(
    "/datasets/default-resume",
    response_model=AiEvaluationDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_default_resume_evaluation_dataset(
    current_user: CurrentUser,
    db: DbSession,
) -> AiEvaluationDatasetResponse:
    _ensure_ai_evaluation_admin(current_user)
    dataset = ensure_default_resume_evaluation_dataset(db, created_by=current_user)
    return AiEvaluationDatasetResponse.model_validate(dataset)


@router.post(
    "/runs/offline-resume",
    response_model=AiEvaluationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def run_offline_resume_evaluation_endpoint(
    payload: AiEvaluationRunCreateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> AiEvaluationRunResponse:
    _ensure_ai_evaluation_admin(current_user)
    run = run_offline_resume_evaluation(
        db,
        options=OfflineEvaluationOptions(
            model_name=payload.model_name.strip(),
            prompt_version=payload.prompt_version.strip(),
            forced_error_case_keys=frozenset(
                item.strip() for item in payload.forced_error_case_keys if item.strip()
            ),
        ),
        created_by=current_user,
    )
    return AiEvaluationRunResponse.model_validate(run)


@router.get("/runs", response_model=AiEvaluationRunListResponse)
def list_ai_evaluation_runs(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Annotated[RunStatusFilter | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AiEvaluationRunListResponse:
    _ensure_ai_evaluation_admin(current_user)
    filters = []
    if status_filter:
        filters.append(AiEvaluationRun.status == status_filter)
    total = db.scalar(select(func.count(AiEvaluationRun.id)).where(*filters)) or 0
    items = list(
        db.scalars(
            select(AiEvaluationRun)
            .where(*filters)
            .order_by(AiEvaluationRun.created_at.desc(), AiEvaluationRun.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return AiEvaluationRunListResponse(
        total=total,
        items=[AiEvaluationRunResponse.model_validate(item) for item in items],
    )


@router.get("/runs/{run_id}", response_model=AiEvaluationRunDetailResponse)
def get_ai_evaluation_run(
    run_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> AiEvaluationRunDetailResponse:
    _ensure_ai_evaluation_admin(current_user)
    run = db.scalar(
        select(AiEvaluationRun)
        .where(AiEvaluationRun.id == run_id)
        .options(selectinload(AiEvaluationRun.results))
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="评测运行不存在")
    return AiEvaluationRunDetailResponse(
        run=AiEvaluationRunResponse.model_validate(run),
        results=[AiEvaluationResultResponse.model_validate(item) for item in run.results],
    )


@router.get("/error-cases", response_model=AiEvaluationErrorCaseListResponse)
def list_ai_evaluation_error_cases(
    current_user: CurrentUser,
    db: DbSession,
    status_filter: Annotated[ErrorCaseStatusFilter | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AiEvaluationErrorCaseListResponse:
    _ensure_ai_evaluation_admin(current_user)
    filters = []
    if status_filter:
        filters.append(AiEvaluationErrorCase.status == status_filter)
    total = db.scalar(select(func.count(AiEvaluationErrorCase.id)).where(*filters)) or 0
    items = list(
        db.scalars(
            select(AiEvaluationErrorCase)
            .where(*filters)
            .order_by(
                AiEvaluationErrorCase.created_at.desc(),
                AiEvaluationErrorCase.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return AiEvaluationErrorCaseListResponse(
        total=total,
        items=[AiEvaluationErrorCaseResponse.model_validate(item) for item in items],
    )


@router.patch("/error-cases/{case_id}", response_model=AiEvaluationErrorCaseResponse)
def update_ai_evaluation_error_case(
    case_id: uuid.UUID,
    payload: AiEvaluationErrorCaseUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> AiEvaluationErrorCaseResponse:
    _ensure_ai_evaluation_admin(current_user)
    error_case = db.get(AiEvaluationErrorCase, case_id)
    if error_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="错误案例不存在")
    error_case.status = payload.status
    error_case.remediation_note = payload.remediation_note
    if payload.status == "open":
        error_case.resolved_by_id = None
        error_case.resolved_at = None
    else:
        error_case.resolved_by_id = current_user.id
        error_case.resolved_at = datetime.now(UTC)
    db.commit()
    db.refresh(error_case)
    return AiEvaluationErrorCaseResponse.model_validate(error_case)
