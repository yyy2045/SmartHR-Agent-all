import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.database import get_db
from app.models import (
    HardRequirement,
    Job,
    JobCriteriaVersion,
    Role,
    ScoringDimension,
    User,
    UserRole,
)
from app.schemas.job import (
    CriteriaDraftUpdate,
    CriteriaVersionCreate,
    CriteriaVersionResponse,
    JDAIDraft,
    JobCreate,
    JobDetailResponse,
    JobResponse,
    JobUpdate,
)
from app.services.ai_client import (
    AIConfigurationError,
    AIRequestTimeout,
    AIResponseValidationError,
    AIUpstreamError,
    OpenAICompatibleClient,
    get_ai_client,
)
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job, job_scope_clause

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
AIClient = Annotated[OpenAICompatibleClient, Depends(get_ai_client)]


def get_owned_job(db: Session, job_id: uuid.UUID, owner_id: uuid.UUID) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_id == owner_id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    return job


def get_job_detail(db: Session, job_id: uuid.UUID, owner_id: uuid.UUID) -> Job:
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.owner_id == owner_id)
        .options(
            selectinload(Job.criteria_versions).selectinload(
                JobCriteriaVersion.hard_requirements
            ),
            selectinload(Job.criteria_versions).selectinload(
                JobCriteriaVersion.scoring_dimensions
            ),
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    return job


def get_visible_job_detail(db: Session, job_id: uuid.UUID, user: User) -> Job:
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, job_scope_clause(user))
        .options(
            selectinload(Job.criteria_versions).selectinload(
                JobCriteriaVersion.hard_requirements
            ),
            selectinload(Job.criteria_versions).selectinload(
                JobCriteriaVersion.scoring_dimensions
            ),
        )
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    return job


def get_owned_version(
    db: Session,
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> JobCriteriaVersion:
    version = db.scalar(
        select(JobCriteriaVersion)
        .join(Job)
        .where(
            JobCriteriaVersion.id == version_id,
            JobCriteriaVersion.job_id == job_id,
            Job.owner_id == owner_id,
        )
        .options(
            selectinload(JobCriteriaVersion.hard_requirements),
            selectinload(JobCriteriaVersion.scoring_dimensions),
        )
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="筛选标准版本不存在")
    return version


def get_visible_version(
    db: Session,
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User,
) -> JobCriteriaVersion:
    get_visible_job(db, job_id, user)
    version = db.scalar(
        select(JobCriteriaVersion)
        .where(
            JobCriteriaVersion.id == version_id,
            JobCriteriaVersion.job_id == job_id,
        )
        .options(
            selectinload(JobCriteriaVersion.hard_requirements),
            selectinload(JobCriteriaVersion.scoring_dimensions),
        )
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="筛选标准版本不存在")
    return version


def get_active_user_with_role(
    db: Session,
    user_id: uuid.UUID,
    role_key: str,
    *,
    detail: str,
) -> User:
    user = db.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.id == user_id, User.is_active.is_(True), Role.key == role_key)
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
    return user


def resolve_recruiter_id(
    db: Session,
    current_user: User,
    recruiter_id: uuid.UUID | None,
) -> uuid.UUID:
    selected_id = recruiter_id
    if selected_id is None and current_user.has_role("recruiter"):
        selected_id = current_user.id
    if selected_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="管理员创建职位时必须指定招聘专员",
        )
    if not current_user.has_role("administrator") and selected_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="招聘专员不能把职位分配给其他招聘专员",
        )
    get_active_user_with_role(
        db,
        selected_id,
        "recruiter",
        detail="招聘专员不存在、已停用或角色不匹配",
    )
    return selected_id


def validate_hiring_manager_id(
    db: Session,
    hiring_manager_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if hiring_manager_id is not None:
        get_active_user_with_role(
            db,
            hiring_manager_id,
            "hiring_manager",
            detail="用人经理不存在、已停用或角色不匹配",
        )
    return hiring_manager_id


def ensure_job_active(job: Job) -> None:
    if job.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档职位不能修改")


@router.get("", response_model=list[JobResponse])
def list_jobs(
    current_user: CurrentUser,
    db: DbSession,
    include_archived: Annotated[bool, Query()] = False,
) -> list[Job]:
    query = select(Job).where(job_scope_clause(current_user))
    if not include_archived:
        query = query.where(Job.status == "active")
    return list(db.scalars(query.order_by(Job.updated_at.desc(), Job.created_at.desc())))


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, current_user: CurrentUser, db: DbSession) -> Job:
    if not current_user.has_role("administrator", "recruiter"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前角色不能创建职位",
        )
    data = payload.model_dump(exclude={"recruiter_id", "hiring_manager_id"})
    owner_id = resolve_recruiter_id(db, current_user, payload.recruiter_id)
    hiring_manager_id = validate_hiring_manager_id(db, payload.hiring_manager_id)
    job = Job(
        owner_id=owner_id,
        hiring_manager_id=hiring_manager_id,
        **data,
    )
    db.add(job)
    db.flush()
    record_audit(
        db,
        action="job.created",
        target_type="job",
        target_id=job.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={
            "recruiter_id": str(owner_id),
            "hiring_manager_id": str(hiring_manager_id) if hiring_manager_id else None,
        },
    )
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=JobDetailResponse)
def get_job(job_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Job:
    return get_visible_job_detail(db, job_id, current_user)


@router.patch("/{job_id}", response_model=JobResponse)
def update_job(
    job_id: uuid.UUID,
    payload: JobUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> Job:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    data = payload.model_dump(
        exclude_unset=True,
        exclude={"recruiter_id", "hiring_manager_id"},
    )
    for field, value in data.items():
        setattr(job, field, value)
    if "recruiter_id" in payload.model_fields_set:
        if payload.recruiter_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="职位必须指定招聘专员",
            )
        job.owner_id = resolve_recruiter_id(db, current_user, payload.recruiter_id)
    if "hiring_manager_id" in payload.model_fields_set:
        job.hiring_manager_id = validate_hiring_manager_id(db, payload.hiring_manager_id)
    record_audit(
        db,
        action="job.updated",
        target_type="job",
        target_id=job.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={
            "updated_fields": sorted(payload.model_fields_set),
            "recruiter_id": str(job.owner_id),
            "hiring_manager_id": (
                str(job.hiring_manager_id) if job.hiring_manager_id else None
            ),
        },
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/archive", response_model=JobResponse)
def archive_job(job_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> Job:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    if job.status != "archived":
        job.status = "archived"
        job.archived_at = datetime.now(UTC)
        db.commit()
        db.refresh(job)
    return job


@router.post("/{job_id}/criteria/ai-draft", response_model=JDAIDraft)
async def generate_ai_criteria_draft(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    ai_client: AIClient,
) -> JDAIDraft:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    try:
        return await ai_client.structure_jd(
            title=job.title,
            department=job.department,
            jd=job.original_jd,
        )
    except AIConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except AIRequestTimeout as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(error),
        ) from error
    except (AIResponseValidationError, AIUpstreamError) as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@router.get("/{job_id}/criteria/versions", response_model=list[CriteriaVersionResponse])
def list_criteria_versions(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[JobCriteriaVersion]:
    get_visible_job(db, job_id, current_user)
    return list(
        db.scalars(
            select(JobCriteriaVersion)
            .where(JobCriteriaVersion.job_id == job_id)
            .options(
                selectinload(JobCriteriaVersion.hard_requirements),
                selectinload(JobCriteriaVersion.scoring_dimensions),
            )
            .order_by(JobCriteriaVersion.version_number.desc())
        )
    )


@router.post(
    "/{job_id}/criteria/versions",
    response_model=CriteriaVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_criteria_version(
    job_id: uuid.UUID,
    payload: CriteriaVersionCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> JobCriteriaVersion:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)

    source = None
    if payload.source_version_id is not None:
        source = get_visible_version(db, job_id, payload.source_version_id, current_user)
        if source.status != "confirmed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="只能从已确认标准创建新版本",
            )

    latest_version = db.scalar(
        select(func.max(JobCriteriaVersion.version_number)).where(
            JobCriteriaVersion.job_id == job_id
        )
    )
    version = JobCriteriaVersion(
        job_id=job_id,
        version_number=(latest_version or 0) + 1,
        pass_threshold=source.pass_threshold if source else 60,
        source_version_id=source.id if source else None,
    )
    if source:
        version.hard_requirements = [
            HardRequirement(
                requirement_type=item.requirement_type,
                title=item.title,
                description=item.description,
                expected_value=item.expected_value,
                auto_reject=item.auto_reject,
                sort_order=item.sort_order,
            )
            for item in source.hard_requirements
        ]
        version.scoring_dimensions = [
            ScoringDimension(
                name=item.name,
                description=item.description,
                weight_percent=item.weight_percent,
                sort_order=item.sort_order,
            )
            for item in source.scoring_dimensions
        ]

    db.add(version)
    db.commit()
    return get_visible_version(db, job_id, version.id, current_user)


@router.get(
    "/{job_id}/criteria/versions/{version_id}",
    response_model=CriteriaVersionResponse,
)
def get_criteria_version(
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> JobCriteriaVersion:
    return get_visible_version(db, job_id, version_id, current_user)


@router.put(
    "/{job_id}/criteria/versions/{version_id}",
    response_model=CriteriaVersionResponse,
)
def update_criteria_draft(
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: CriteriaDraftUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> JobCriteriaVersion:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    version = get_visible_version(db, job_id, version_id, current_user)
    if version.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已确认标准不可修改，请创建新版本",
        )

    version.pass_threshold = payload.pass_threshold
    version.hard_requirements = [
        HardRequirement(**item.model_dump()) for item in payload.hard_requirements
    ]
    version.scoring_dimensions = [
        ScoringDimension(**item.model_dump()) for item in payload.scoring_dimensions
    ]
    db.commit()
    return get_visible_version(db, job_id, version_id, current_user)


@router.post(
    "/{job_id}/criteria/versions/{version_id}/confirm",
    response_model=CriteriaVersionResponse,
)
def confirm_criteria_version(
    job_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> JobCriteriaVersion:
    job = get_visible_job(db, job_id, current_user)
    ensure_job_writable(job, current_user)
    ensure_job_active(job)
    version = get_visible_version(db, job_id, version_id, current_user)
    if version.status == "confirmed":
        return version
    if not version.scoring_dimensions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="至少需要一个评分维度",
        )
    total_weight = sum(item.weight_percent for item in version.scoring_dimensions)
    if total_weight != 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"评分维度权重总和必须为 100%，当前为 {total_weight}%",
        )

    version.status = "confirmed"
    version.confirmed_by_id = current_user.id
    version.confirmed_at = datetime.now(UTC)
    record_audit(
        db,
        action="criteria.confirmed",
        target_type="job_criteria_version",
        target_id=version.id,
        job_id=job.id,
        result="success",
        actor=current_user,
        details={
            "version_number": version.version_number,
            "pass_threshold": version.pass_threshold,
        },
    )
    db.commit()
    return get_visible_version(db, job_id, version_id, current_user)
