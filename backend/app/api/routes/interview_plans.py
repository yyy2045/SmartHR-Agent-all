import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.api.routes.jobs import ensure_job_active
from app.database import get_db
from app.models import (
    InterviewPlanVersion,
    InterviewQuestion,
    InterviewRound,
    InterviewScoreAnchor,
    InterviewScoreDimension,
    User,
)
from app.schemas.interview_plan import (
    InterviewPlanDraftUpdate,
    InterviewPlanVersionCreate,
    InterviewPlanVersionResponse,
)
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def plan_load_options():
    return (
        selectinload(InterviewPlanVersion.rounds).selectinload(InterviewRound.questions),
        selectinload(InterviewPlanVersion.rounds)
        .selectinload(InterviewRound.scoring_dimensions)
        .selectinload(InterviewScoreDimension.anchors),
    )


def get_owned_plan_version(
    db: Session,
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User,
) -> InterviewPlanVersion:
    get_visible_job(db, job_id, user)
    version = db.scalar(
        select(InterviewPlanVersion)
        .where(
            InterviewPlanVersion.id == version_id,
            InterviewPlanVersion.job_id == job_id,
        )
        .options(*plan_load_options())
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="面试方案版本不存在")
    return version


def clone_round(source: InterviewRound) -> InterviewRound:
    return InterviewRound(
        name=source.name,
        round_type=source.round_type,
        duration_minutes=source.duration_minutes,
        pass_threshold=source.pass_threshold,
        focus=source.focus,
        sort_order=source.sort_order,
        questions=[
            InterviewQuestion(
                question_text=item.question_text,
                evaluation_guide=item.evaluation_guide,
                sort_order=item.sort_order,
            )
            for item in source.questions
        ],
        scoring_dimensions=[
            InterviewScoreDimension(
                name=item.name,
                description=item.description,
                weight_percent=item.weight_percent,
                sort_order=item.sort_order,
                anchors=[
                    InterviewScoreAnchor(
                        score_value=anchor.score_value,
                        description=anchor.description,
                    )
                    for anchor in item.anchors
                ],
            )
            for item in source.scoring_dimensions
        ],
    )


def validate_confirmable(version: InterviewPlanVersion) -> None:
    if not version.rounds:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="至少需要一个面试轮次",
        )
    for round_item in version.rounds:
        if not round_item.name.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="面试轮次名称不能为空",
            )
        if not round_item.questions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{round_item.name}至少需要一个面试问题",
            )
        if any(not item.question_text.strip() for item in round_item.questions):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{round_item.name}的面试问题不能为空",
            )
        if not round_item.scoring_dimensions:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{round_item.name}至少需要一个评分维度",
            )
        if any(not item.name.strip() for item in round_item.scoring_dimensions):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{round_item.name}的评分维度名称不能为空",
            )
        total_weight = sum(item.weight_percent for item in round_item.scoring_dimensions)
        if total_weight != 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{round_item.name}评分维度权重总和必须为 100%，当前为 {total_weight}%",
            )
        for dimension in round_item.scoring_dimensions:
            scores = sorted(anchor.score_value for anchor in dimension.anchors)
            if scores != [1, 2, 3, 4, 5]:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"{round_item.name}的{dimension.name}必须完整配置 1～5 分评分锚点",
                )


@router.get(
    "/{job_id}/interview-plans/versions",
    response_model=list[InterviewPlanVersionResponse],
)
def list_interview_plan_versions(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[InterviewPlanVersion]:
    get_visible_job(db, job_id, current_user)
    return list(
        db.scalars(
            select(InterviewPlanVersion)
            .where(InterviewPlanVersion.job_id == job_id)
            .options(*plan_load_options())
            .order_by(InterviewPlanVersion.version_number.desc())
        )
    )


@router.post(
    "/{job_id}/interview-plans/versions",
    response_model=InterviewPlanVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_interview_plan_version(
    job_id: uuid.UUID,
    payload: InterviewPlanVersionCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewPlanVersion:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    source = None
    if payload.source_version_id is not None:
        source = get_owned_plan_version(
            db,
            job_id,
            payload.source_version_id,
            current_user,
        )
        if source.status != "confirmed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="只能从已确认面试方案创建新版本",
            )

    latest_version = db.scalar(
        select(func.max(InterviewPlanVersion.version_number)).where(
            InterviewPlanVersion.job_id == job_id
        )
    )
    version = InterviewPlanVersion(
        job_id=job_id,
        version_number=(latest_version or 0) + 1,
        source_version_id=source.id if source else None,
        rounds=[clone_round(item) for item in source.rounds] if source else [],
    )
    db.add(version)
    db.flush()
    record_audit(
        db,
        action="interview_plan.created",
        target_type="interview_plan_version",
        target_id=version.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={
            "version_number": version.version_number,
            "source_version_id": str(source.id) if source else None,
        },
    )
    db.commit()
    return get_owned_plan_version(db, job_id, version.id, current_user)


@router.get(
    "/{job_id}/interview-plans/versions/{version_id}",
    response_model=InterviewPlanVersionResponse,
)
def get_interview_plan_version(
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewPlanVersion:
    return get_owned_plan_version(db, job_id, version_id, current_user)


@router.put(
    "/{job_id}/interview-plans/versions/{version_id}",
    response_model=InterviewPlanVersionResponse,
)
def update_interview_plan_draft(
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: InterviewPlanDraftUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewPlanVersion:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    version = get_owned_plan_version(db, job_id, version_id, current_user)
    if version.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已确认面试方案不可修改，请创建新版本",
        )

    replacement_rounds = [
        InterviewRound(
            name=round_item.name,
            round_type=round_item.round_type,
            duration_minutes=round_item.duration_minutes,
            pass_threshold=round_item.pass_threshold,
            focus=round_item.focus,
            sort_order=round_item.sort_order,
            questions=[
                InterviewQuestion(**question.model_dump()) for question in round_item.questions
            ],
            scoring_dimensions=[
                InterviewScoreDimension(
                    name=dimension.name,
                    description=dimension.description,
                    weight_percent=dimension.weight_percent,
                    sort_order=dimension.sort_order,
                    anchors=[
                        InterviewScoreAnchor(**anchor.model_dump())
                        for anchor in dimension.anchors
                    ],
                )
                for dimension in round_item.scoring_dimensions
            ],
        )
        for round_item in payload.rounds
    ]
    version.rounds.clear()
    db.flush()
    version.rounds = replacement_rounds
    record_audit(
        db,
        action="interview_plan.updated",
        target_type="interview_plan_version",
        target_id=version.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={
            "version_number": version.version_number,
            "round_count": len(version.rounds),
        },
    )
    db.commit()
    return get_owned_plan_version(db, job_id, version_id, current_user)


@router.post(
    "/{job_id}/interview-plans/versions/{version_id}/confirm",
    response_model=InterviewPlanVersionResponse,
)
def confirm_interview_plan_version(
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> InterviewPlanVersion:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    version = get_owned_plan_version(db, job_id, version_id, current_user)
    if version.status == "confirmed":
        return version
    validate_confirmable(version)

    question_count = sum(len(item.questions) for item in version.rounds)
    dimension_count = sum(len(item.scoring_dimensions) for item in version.rounds)
    version.status = "confirmed"
    version.confirmed_by_id = current_user.id
    version.confirmed_at = datetime.now(UTC)
    record_audit(
        db,
        action="interview_plan.confirmed",
        target_type="interview_plan_version",
        target_id=version.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={
            "version_number": version.version_number,
            "round_count": len(version.rounds),
            "question_count": question_count,
            "dimension_count": dimension_count,
        },
    )
    db.commit()
    return get_owned_plan_version(db, job_id, version_id, current_user)
