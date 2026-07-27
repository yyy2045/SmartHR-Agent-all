import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.api.routes.batches import screening_result_response
from app.database import get_db
from app.models import (
    CandidateProfile,
    DimensionScore,
    Job,
    JobCriteriaVersion,
    RecruiterDecision,
    ResumeDocument,
    ResumeTextSegment,
    ScreeningBatch,
    ScreeningResult,
    User,
)
from app.schemas.screening import (
    BatchReanalysisRequest,
    BatchReanalysisResponse,
    CandidateProfileCorrectionRequest,
    CandidateProfileCorrectionResponse,
    CandidateProfileDraft,
    CandidateProfileResponse,
    ReanalysisRequest,
    ReanalysisTaskResponse,
    ScreeningResultResponse,
)
from app.services.audit import record_audit
from app.services.authorization import ensure_job_writable, get_visible_job
from app.services.model_payload import (
    ModelPayloadSecurityError,
    validate_candidate_profile_payload,
)
from app.services.resume_analysis import AnalysisContractError, validate_profile_evidence
from app.workers.dispatcher import enqueue_resume_analysis

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def _owned_document(
    db: Session,
    *,
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
) -> ResumeDocument:
    get_visible_job(db, job_id, user)
    document = db.scalar(
        select(ResumeDocument)
        .join(ScreeningBatch)
        .where(
            ResumeDocument.id == document_id,
            ResumeDocument.batch_id == batch_id,
            ScreeningBatch.job_id == job_id,
        )
        .options(
            selectinload(ResumeDocument.batch),
            selectinload(ResumeDocument.text_segments).selectinload(
                ResumeTextSegment.redactions
            ),
            selectinload(ResumeDocument.candidate_profiles),
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历文件不存在")
    return document


def _owned_batch(
    db: Session,
    *,
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    user: User,
) -> ScreeningBatch:
    get_visible_job(db, job_id, user)
    batch = db.scalar(
        select(ScreeningBatch)
        .where(
            ScreeningBatch.id == batch_id,
            ScreeningBatch.job_id == job_id,
        )
        .options(
            selectinload(ScreeningBatch.documents).selectinload(
                ResumeDocument.candidate_profiles
            )
        )
    )
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历批次不存在")
    return batch


def _ensure_active_job(
    db: Session,
    *,
    job_id: uuid.UUID,
    user: User,
) -> Job:
    job = get_visible_job(db, job_id, user)
    ensure_job_writable(job, user)
    if job.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档职位不能重跑分析")
    return job


def _confirmed_criteria(
    db: Session,
    *,
    job_id: uuid.UUID,
    criteria_version_id: uuid.UUID,
    user: User,
) -> JobCriteriaVersion:
    get_visible_job(db, job_id, user)
    criteria = db.scalar(
        select(JobCriteriaVersion)
        .where(
            JobCriteriaVersion.id == criteria_version_id,
            JobCriteriaVersion.job_id == job_id,
        )
    )
    if criteria is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="职位标准版本不存在",
        )
    if criteria.status != "confirmed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只能使用已确认的职位标准重新分析",
        )
    return criteria


def _latest_profile(db: Session, document_id: uuid.UUID) -> CandidateProfile | None:
    return db.scalar(
        select(CandidateProfile)
        .where(CandidateProfile.document_id == document_id)
        .order_by(CandidateProfile.version_number.desc())
        .limit(1)
    )


def _next_analysis_version(
    db: Session,
    *,
    document_ids: list[uuid.UUID],
    criteria_version_id: uuid.UUID,
) -> int:
    latest = db.scalar(
        select(func.max(ScreeningResult.analysis_version)).where(
            ScreeningResult.document_id.in_(document_ids),
            ScreeningResult.criteria_version_id == criteria_version_id,
        )
    )
    return (latest or 0) + 1


def _queue_reanalysis(
    *,
    document_id: uuid.UUID,
    criteria_version_id: uuid.UUID,
    candidate_profile_id: uuid.UUID | None,
    analysis_version: int,
) -> ReanalysisTaskResponse:
    try:
        task_id = enqueue_resume_analysis(
            document_id,
            criteria_version_id=criteria_version_id,
            candidate_profile_id=candidate_profile_id,
            analysis_version=analysis_version,
        )
    except Exception:
        return ReanalysisTaskResponse(
            status="enqueue_failed",
            document_id=document_id,
            criteria_version_id=criteria_version_id,
            candidate_profile_id=candidate_profile_id,
            analysis_version=analysis_version,
            message="AI 分析任务创建失败，请稍后重试",
        )
    return ReanalysisTaskResponse(
        status="queued",
        document_id=document_id,
        criteria_version_id=criteria_version_id,
        candidate_profile_id=candidate_profile_id,
        analysis_version=analysis_version,
        task_id=task_id,
    )


def _profile_payload(payload: CandidateProfileCorrectionRequest) -> dict[str, object]:
    return payload.model_dump(
        mode="json",
        exclude={"source_profile_id", "criteria_version_id"},
    )


def _same_profile_content(
    source: CandidateProfile,
    profile_payload: dict[str, object],
) -> bool:
    return all(
        getattr(source, field) == profile_payload[field]
        for field in (
            "education",
            "work_experiences",
            "projects",
            "skills",
            "certifications",
            "languages",
        )
    )


def _result_options() -> tuple[object, ...]:
    return (
        selectinload(ScreeningResult.document),
        selectinload(ScreeningResult.candidate_profile),
        selectinload(ScreeningResult.criteria_version),
        selectinload(ScreeningResult.dimension_scores).selectinload(
            DimensionScore.evidence_citations
        ),
        selectinload(ScreeningResult.evidence_citations),
        selectinload(ScreeningResult.recruiter_decisions).selectinload(
            RecruiterDecision.operator
        ),
    )


@router.get(
    "/{job_id}/batches/{batch_id}/documents/{document_id}/profiles",
    response_model=list[CandidateProfileResponse],
)
def list_candidate_profiles(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[CandidateProfile]:
    _owned_document(
        db,
        job_id=job_id,
        batch_id=batch_id,
        document_id=document_id,
        user=current_user,
    )
    return list(
        db.scalars(
            select(CandidateProfile)
            .where(CandidateProfile.document_id == document_id)
            .order_by(CandidateProfile.version_number.desc())
        )
    )


@router.get(
    "/{job_id}/batches/{batch_id}/documents/{document_id}/analysis-history",
    response_model=list[ScreeningResultResponse],
)
def list_candidate_analysis_history(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[ScreeningResultResponse]:
    document = _owned_document(
        db,
        job_id=job_id,
        batch_id=batch_id,
        document_id=document_id,
        user=current_user,
    )
    results = list(
        db.scalars(
            select(ScreeningResult)
            .where(ScreeningResult.document_id == document_id)
            .options(*_result_options())
            .order_by(ScreeningResult.created_at.desc(), ScreeningResult.id.desc())
        )
        .unique()
        .all()
    )
    return [screening_result_response(item, document.candidate_code) for item in results]


@router.post(
    "/{job_id}/batches/{batch_id}/documents/{document_id}/profile-corrections",
    response_model=CandidateProfileCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def correct_candidate_profile(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: CandidateProfileCorrectionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> CandidateProfileCorrectionResponse:
    _ensure_active_job(db, job_id=job_id, user=current_user)
    document = _owned_document(
        db,
        job_id=job_id,
        batch_id=batch_id,
        document_id=document_id,
        user=current_user,
    )
    if document.status != "completed" or document.redacted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="简历尚未完成解析和脱敏，不能修正结构化资料",
        )
    criteria = _confirmed_criteria(
        db,
        job_id=job_id,
        criteria_version_id=payload.criteria_version_id,
        user=current_user,
    )
    source = db.get(CandidateProfile, payload.source_profile_id)
    latest = _latest_profile(db, document.id)
    if source is None or source.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人资料版本不存在")
    if latest is None or latest.id != source.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="候选人资料已产生新版本，请刷新后再修正",
        )

    profile_payload = _profile_payload(payload)
    if _same_profile_content(source, profile_payload):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="修正内容未发生变化")
    profile_draft = CandidateProfileDraft.model_validate(profile_payload)
    try:
        if document.batch.ai_input_mode == "redacted":
            validate_candidate_profile_payload(document, profile_payload)
        validate_profile_evidence(document, profile_draft)
    except (ModelPayloadSecurityError, AnalysisContractError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error

    profile = CandidateProfile(
        document_id=document.id,
        version_number=source.version_number + 1,
        source="manual",
        source_profile_id=source.id,
        model_name="manual-correction",
        prompt_version="profile-correction-v1",
        **profile_payload,
    )
    db.add(profile)
    db.commit()

    analysis_version = _next_analysis_version(
        db,
        document_ids=[document.id],
        criteria_version_id=criteria.id,
    )
    reanalysis = _queue_reanalysis(
        document_id=document.id,
        criteria_version_id=criteria.id,
        candidate_profile_id=profile.id,
        analysis_version=analysis_version,
    )
    record_audit(
        db,
        action="candidate.profile_corrected",
        target_type="candidate_profile",
        target_id=profile.id,
        job_id=job_id,
        batch_id=batch_id,
        result="success",
        actor=current_user,
        details={
            "source_profile_id": str(source.id),
            "version_number": profile.version_number,
        },
    )
    record_audit(
        db,
        action="screening.reanalysis_requested",
        target_type="resume_document",
        target_id=document.id,
        job_id=job_id,
        batch_id=batch_id,
        result="success" if reanalysis.status == "queued" else "failure",
        actor=current_user,
        details={
            "scope": "candidate_after_correction",
            "criteria_version_id": str(criteria.id),
            "analysis_version": analysis_version,
        },
    )
    db.commit()
    return CandidateProfileCorrectionResponse(profile=profile, reanalysis=reanalysis)


@router.post(
    "/{job_id}/batches/{batch_id}/documents/{document_id}/reanalysis",
    response_model=ReanalysisTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reanalyze_candidate(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: ReanalysisRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> ReanalysisTaskResponse:
    _ensure_active_job(db, job_id=job_id, user=current_user)
    document = _owned_document(
        db,
        job_id=job_id,
        batch_id=batch_id,
        document_id=document_id,
        user=current_user,
    )
    if document.status != "completed" or document.redacted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="简历尚未完成解析和脱敏，不能重新分析",
        )
    criteria = _confirmed_criteria(
        db,
        job_id=job_id,
        criteria_version_id=payload.criteria_version_id,
        user=current_user,
    )
    profile = (
        db.get(CandidateProfile, payload.candidate_profile_id)
        if payload.candidate_profile_id is not None
        else _latest_profile(db, document.id)
    )
    if profile is not None and profile.document_id != document.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人资料版本不存在")
    analysis_version = _next_analysis_version(
        db,
        document_ids=[document.id],
        criteria_version_id=criteria.id,
    )
    task = _queue_reanalysis(
        document_id=document.id,
        criteria_version_id=criteria.id,
        candidate_profile_id=profile.id if profile is not None else None,
        analysis_version=analysis_version,
    )
    record_audit(
        db,
        action="screening.reanalysis_requested",
        target_type="resume_document",
        target_id=document.id,
        job_id=job_id,
        batch_id=batch_id,
        result="success" if task.status == "queued" else "failure",
        actor=current_user,
        details={
            "scope": "candidate",
            "criteria_version_id": str(criteria.id),
            "analysis_version": analysis_version,
            "candidate_profile_id": str(profile.id) if profile is not None else None,
        },
    )
    db.commit()
    if task.status == "enqueue_failed":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=task.message,
        )
    return task


@router.post(
    "/{job_id}/batches/{batch_id}/reanalysis",
    response_model=BatchReanalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reanalyze_batch(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: BatchReanalysisRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> BatchReanalysisResponse:
    _ensure_active_job(db, job_id=job_id, user=current_user)
    batch = _owned_batch(
        db,
        job_id=job_id,
        batch_id=batch_id,
        user=current_user,
    )
    criteria = _confirmed_criteria(
        db,
        job_id=job_id,
        criteria_version_id=payload.criteria_version_id,
        user=current_user,
    )
    ready_documents = [
        document
        for document in batch.documents
        if document.status == "completed" and document.redacted_at is not None
    ]
    if not ready_documents:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="批次中没有已完成解析和脱敏的候选人",
        )
    analysis_version = _next_analysis_version(
        db,
        document_ids=[document.id for document in ready_documents],
        criteria_version_id=criteria.id,
    )
    tasks: list[ReanalysisTaskResponse] = []
    for document in batch.documents:
        if document not in ready_documents:
            tasks.append(
                ReanalysisTaskResponse(
                    status="skipped",
                    document_id=document.id,
                    criteria_version_id=criteria.id,
                    candidate_profile_id=None,
                    analysis_version=analysis_version,
                    message="简历尚未完成解析和脱敏，已跳过",
                )
            )
            continue
        profile = max(
            document.candidate_profiles,
            key=lambda item: item.version_number,
            default=None,
        )
        tasks.append(
            _queue_reanalysis(
                document_id=document.id,
                criteria_version_id=criteria.id,
                candidate_profile_id=profile.id if profile is not None else None,
                analysis_version=analysis_version,
            )
        )

    queued_count = sum(item.status == "queued" for item in tasks)
    failed_count = sum(item.status == "enqueue_failed" for item in tasks)
    skipped_count = sum(item.status == "skipped" for item in tasks)
    if queued_count == 0:
        response_status = "enqueue_failed"
    elif failed_count or skipped_count:
        response_status = "partial_failure"
    else:
        response_status = "queued"
    record_audit(
        db,
        action="screening.reanalysis_requested",
        target_type="screening_batch",
        target_id=batch.id,
        job_id=job_id,
        batch_id=batch.id,
        result="success" if queued_count else "failure",
        actor=current_user,
        details={
            "scope": "batch",
            "criteria_version_id": str(criteria.id),
            "analysis_version": analysis_version,
            "queued_count": queued_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
        },
    )
    db.commit()
    return BatchReanalysisResponse(
        status=response_status,
        batch_id=batch.id,
        criteria_version_id=criteria.id,
        analysis_version=analysis_version,
        queued_count=queued_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        tasks=tasks,
    )
