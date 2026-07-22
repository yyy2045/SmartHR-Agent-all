import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import CurrentUser
from app.config import settings
from app.database import get_db
from app.models import (
    CandidateProfile,
    DimensionScore,
    Job,
    JobCriteriaVersion,
    RecruiterDecision,
    ResumeDocument,
    ScreeningBatch,
    ScreeningResult,
)
from app.schemas.batch import (
    BatchDeletionRequest,
    BatchDeletionResponse,
    ResumeDocumentDetailResponse,
    ResumeDocumentResponse,
    ResumeTextSegmentResponse,
    ScreeningBatchResponse,
)
from app.schemas.screening import (
    AnalysisQueueResponse,
    CandidateProfileResponse,
    DimensionScoreResponse,
    EvidenceCitationResponse,
    HardRequirementJudgmentResponse,
    RecruiterDecisionResponse,
    ScreeningResultResponse,
)
from app.services.audit import record_audit
from app.services.batch_deletion import BatchDeletionError, stage_batch_files
from app.services.batch_status import refresh_batch_status
from app.services.file_storage import (
    FileValidationError,
    delete_private_file,
    resolve_private_file,
    safe_original_filename,
    store_resume_upload,
)
from app.workers.dispatcher import enqueue_resume_analysis, enqueue_resume_parsing

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def get_owned_job(db: Session, job_id: uuid.UUID, owner_id: uuid.UUID) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.owner_id == owner_id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    return job


def get_confirmed_version(
    db: Session,
    job_id: uuid.UUID,
    version_id: uuid.UUID,
) -> JobCriteriaVersion:
    version = db.scalar(
        select(JobCriteriaVersion).where(
            JobCriteriaVersion.id == version_id,
            JobCriteriaVersion.job_id == job_id,
            JobCriteriaVersion.status == "confirmed",
        )
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="筛选批次必须绑定该职位已确认的标准版本",
        )
    return version


def get_owned_batch(
    db: Session,
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> ScreeningBatch:
    batch = db.scalar(
        select(ScreeningBatch)
        .join(Job)
        .where(
            ScreeningBatch.id == batch_id,
            ScreeningBatch.job_id == job_id,
            Job.owner_id == owner_id,
        )
        .options(
            selectinload(ScreeningBatch.criteria_version),
            selectinload(ScreeningBatch.documents),
        )
    )
    if batch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="筛选批次不存在")
    return batch


def get_owned_document(
    db: Session,
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> ResumeDocument:
    document = db.scalar(
        select(ResumeDocument)
        .join(ScreeningBatch)
        .join(Job)
        .where(
            ResumeDocument.id == document_id,
            ResumeDocument.batch_id == batch_id,
            ScreeningBatch.job_id == job_id,
            Job.owner_id == owner_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历文件不存在")
    return document


def get_owned_document_detail(
    db: Session,
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> ResumeDocument:
    document = db.scalar(
        select(ResumeDocument)
        .join(ScreeningBatch)
        .join(Job)
        .where(
            ResumeDocument.id == document_id,
            ResumeDocument.batch_id == batch_id,
            ScreeningBatch.job_id == job_id,
            Job.owner_id == owner_id,
        )
        .options(selectinload(ResumeDocument.text_segments))
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历文件不存在")
    return document


def get_latest_screening_result(
    db: Session,
    document_id: uuid.UUID,
) -> ScreeningResult | None:
    return db.scalar(
        select(ScreeningResult)
        .where(ScreeningResult.document_id == document_id)
        .options(
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
        .order_by(
            case((ScreeningResult.status == "completed", 0), else_=1),
            ScreeningResult.created_at.desc(),
            ScreeningResult.analysis_version.desc(),
        )
        .limit(1)
    )


def is_duplicate_resume(
    db: Session,
    *,
    job_id: uuid.UUID,
    sha256: str,
    excluded_document_id: uuid.UUID,
) -> bool:
    existing_id = db.scalar(
        select(ResumeDocument.id)
        .join(ScreeningBatch)
        .where(
            ScreeningBatch.job_id == job_id,
            ResumeDocument.sha256 == sha256,
            ResumeDocument.storage_key.is_not(None),
            ResumeDocument.id != excluded_document_id,
        )
        .limit(1)
    )
    return existing_id is not None


def document_response(document: ResumeDocument) -> ResumeDocumentResponse:
    return ResumeDocumentResponse(
        id=document.id,
        batch_id=document.batch_id,
        original_filename=document.original_filename,
        file_extension=document.file_extension,
        content_type=document.content_type,
        detected_type=document.detected_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        has_original_file=bool(document.storage_key),
        extraction_method=document.extraction_method,
        segment_count=document.segment_count,
        text_character_count=document.text_character_count,
        candidate_code=document.candidate_code,
        redaction_count=document.redaction_count,
        status=document.status,
        failure_code=document.failure_code,
        failure_message=document.failure_message,
        attempt_count=document.attempt_count,
        processing_attempt_count=document.processing_attempt_count,
        processing_started_at=document.processing_started_at,
        parsed_at=document.parsed_at,
        redacted_at=document.redacted_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def batch_response(batch: ScreeningBatch) -> ScreeningBatchResponse:
    documents = list(batch.documents)
    return ScreeningBatchResponse(
        id=batch.id,
        job_id=batch.job_id,
        criteria_version_id=batch.criteria_version_id,
        criteria_version_number=batch.criteria_version.version_number,
        name=batch.name,
        status=batch.status,
        total_count=len(documents),
        success_count=sum(item.status == "completed" for item in documents),
        failed_count=sum(item.status == "failed" for item in documents),
        processing_count=sum(item.status in {"queued", "processing"} for item in documents),
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        documents=[document_response(item) for item in documents],
    )


def screening_result_response(
    result: ScreeningResult,
    candidate_code: str,
) -> ScreeningResultResponse:
    citations = [
        EvidenceCitationResponse.model_validate(item)
        for item in result.evidence_citations
    ]
    decision_history = [
        RecruiterDecisionResponse(
            id=item.id,
            screening_result_id=item.screening_result_id,
            sequence_number=item.sequence_number,
            previous_decision=item.previous_decision,
            decision=item.decision,
            reason=item.reason,
            is_auto_rejection_override=item.is_auto_rejection_override,
            operator_id=item.operator_id,
            operator_display_name=item.operator.display_name,
            created_at=item.created_at,
        )
        for item in result.recruiter_decisions
    ]
    return ScreeningResultResponse(
        id=result.id,
        document_id=result.document_id,
        candidate_code=candidate_code,
        criteria_version_id=result.criteria_version_id,
        criteria_version_number=result.criteria_version.version_number,
        analysis_version=result.analysis_version,
        status=result.status,
        ai_group=result.ai_group,
        total_score=float(result.total_score) if result.total_score is not None else None,
        pass_threshold=result.pass_threshold,
        hard_requirements=[
            HardRequirementJudgmentResponse.model_validate(item)
            for item in result.hard_requirement_results
        ],
        strengths=result.strengths,
        gaps=result.gaps,
        missing_items=result.missing_items,
        interview_questions=result.interview_questions,
        model_name=result.model_name,
        prompt_version=result.prompt_version,
        failure_code=result.failure_code,
        failure_message=result.failure_message,
        started_at=result.started_at,
        completed_at=result.completed_at,
        created_at=result.created_at,
        candidate_profile=(
            CandidateProfileResponse.model_validate(result.candidate_profile)
            if result.candidate_profile is not None
            else None
        ),
        dimension_scores=[
            DimensionScoreResponse(
                id=item.id,
                scoring_dimension_id=item.scoring_dimension_id,
                dimension_name=item.dimension_name,
                score=item.score,
                weight_percent=item.weight_percent,
                weighted_score=float(item.weighted_score),
                rationale=item.rationale,
                missing_items=item.missing_items,
                sort_order=item.sort_order,
                evidence=[
                    EvidenceCitationResponse.model_validate(citation)
                    for citation in item.evidence_citations
                ],
            )
            for item in result.dimension_scores
        ],
        evidence=citations,
        current_decision=(
            result.recruiter_decisions[-1].decision
            if result.recruiter_decisions
            else "unprocessed"
        ),
        decision_history=decision_history,
    )


def queue_document(db: Session, document: ResumeDocument) -> None:
    document.status = "queued"
    document.failure_code = None
    document.failure_message = None
    refresh_batch_status(document.batch)
    db.commit()
    try:
        document.task_id = enqueue_resume_parsing(document.id)
    except Exception:
        document.status = "failed"
        document.failure_code = "task_enqueue_failed"
        document.failure_message = "解析任务创建失败，请稍后重试"
        refresh_batch_status(document.batch)
    db.commit()


async def process_upload(
    db: Session,
    *,
    batch: ScreeningBatch,
    document: ResumeDocument,
    upload: UploadFile,
) -> None:
    stored = None
    try:
        stored = await store_resume_upload(
            upload,
            storage_root=settings.file_storage_root,
            job_id=batch.job_id,
            batch_id=batch.id,
            max_size_bytes=settings.max_resume_file_size_mb * 1024 * 1024,
        )
        if is_duplicate_resume(
            db,
            job_id=batch.job_id,
            sha256=stored.sha256,
            excluded_document_id=document.id,
        ):
            delete_private_file(settings.file_storage_root, stored.storage_key)
            stored = None
            raise FileValidationError("duplicate_file", "同一职位下已存在内容相同的简历")

        document.original_filename = stored.original_filename
        document.file_extension = stored.file_extension
        document.content_type = stored.content_type
        document.detected_type = stored.detected_type
        document.size_bytes = stored.size_bytes
        document.sha256 = stored.sha256
        document.storage_key = stored.storage_key
        document.status = "uploaded"
        document.failure_code = None
        document.failure_message = None
    except FileValidationError as error:
        document.status = "failed"
        document.failure_code = error.code
        document.failure_message = error.message
        document.sha256 = None
        document.storage_key = None
    except OSError:
        if stored is not None:
            delete_private_file(settings.file_storage_root, stored.storage_key)
        document.status = "failed"
        document.failure_code = "storage_error"
        document.failure_message = "文件保存失败，请稍后重试"
        document.sha256 = None
        document.storage_key = None
    finally:
        await upload.close()


@router.get("/{job_id}/batches", response_model=list[ScreeningBatchResponse])
def list_batches(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[ScreeningBatchResponse]:
    get_owned_job(db, job_id, current_user.id)
    batches = db.scalars(
        select(ScreeningBatch)
        .where(ScreeningBatch.job_id == job_id)
        .options(
            selectinload(ScreeningBatch.criteria_version),
            selectinload(ScreeningBatch.documents),
        )
        .order_by(ScreeningBatch.created_at.desc())
    ).all()
    return [batch_response(batch) for batch in batches]


@router.post(
    "/{job_id}/batches",
    response_model=ScreeningBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_batch(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    criteria_version_id: Annotated[uuid.UUID, Form()],
    files: Annotated[list[UploadFile], File()],
    name: Annotated[str, Form(max_length=200)] = "",
) -> ScreeningBatchResponse:
    if len(files) > settings.max_batch_file_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"单批最多上传 {settings.max_batch_file_count} 份简历",
        )

    job = get_owned_job(db, job_id, current_user.id)
    if job.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档职位不能上传简历")
    get_confirmed_version(db, job_id, criteria_version_id)

    batch = ScreeningBatch(
        job_id=job_id,
        criteria_version_id=criteria_version_id,
        name=name.strip() or "简历筛选批次",
    )
    db.add(batch)
    db.flush()

    for upload in files:
        document = ResumeDocument(
            batch_id=batch.id,
            original_filename=safe_original_filename(upload.filename),
            content_type=(upload.content_type or "")[:150],
            status="failed",
            failure_code="upload_pending",
            failure_message="文件尚未完成校验",
        )
        batch.documents.append(document)
        db.flush()
        await process_upload(db, batch=batch, document=document, upload=upload)
        db.flush()

    refresh_batch_status(batch)
    db.commit()
    batch = get_owned_batch(db, job_id, batch.id, current_user.id)
    for document in batch.documents:
        if document.status == "uploaded":
            queue_document(db, document)
    return batch_response(get_owned_batch(db, job_id, batch.id, current_user.id))


@router.get("/{job_id}/batches/{batch_id}", response_model=ScreeningBatchResponse)
def get_batch(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> ScreeningBatchResponse:
    return batch_response(get_owned_batch(db, job_id, batch_id, current_user.id))


@router.put(
    "/{job_id}/batches/{batch_id}/documents/{document_id}/retry",
    response_model=ResumeDocumentResponse,
)
async def retry_failed_document(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> ResumeDocumentResponse:
    batch = get_owned_batch(db, job_id, batch_id, current_user.id)
    document = get_owned_document(
        db,
        job_id,
        batch_id,
        document_id,
        current_user.id,
    )
    if document.status != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有失败文件可以重试")

    previous_storage_key = document.storage_key
    document.attempt_count += 1
    document.original_filename = safe_original_filename(file.filename)
    document.content_type = (file.content_type or "")[:150]
    await process_upload(db, batch=batch, document=document, upload=file)
    if document.status == "uploaded" and previous_storage_key != document.storage_key:
        delete_private_file(settings.file_storage_root, previous_storage_key)
    refresh_batch_status(batch)
    record_audit(
        db,
        action="resume.upload_retried",
        target_type="resume_document",
        target_id=document.id,
        job_id=job_id,
        batch_id=batch_id,
        result="success" if document.status == "uploaded" else "failure",
        actor=current_user,
        details={"attempt_count": document.attempt_count},
    )
    db.commit()
    if document.status == "uploaded":
        queue_document(db, document)
    db.refresh(document)
    return document_response(document)


@router.post(
    "/{job_id}/batches/{batch_id}/documents/{document_id}/parse-retry",
    response_model=ResumeDocumentResponse,
)
def retry_document_parsing(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> ResumeDocumentResponse:
    document = get_owned_document(
        db,
        job_id,
        batch_id,
        document_id,
        current_user.id,
    )
    if document.status != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有失败文件可以重试")
    if not document.storage_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该文件未通过上传校验，请重新选择文件",
        )
    queue_document(db, document)
    record_audit(
        db,
        action="resume.parse_retried",
        target_type="resume_document",
        target_id=document.id,
        job_id=job_id,
        batch_id=batch_id,
        result="success" if document.status == "queued" else "failure",
        actor=current_user,
        details={"task_id_created": document.task_id is not None},
    )
    db.commit()
    db.refresh(document)
    return document_response(document)


@router.get(
    "/{job_id}/batches/{batch_id}/documents/{document_id}",
    response_model=ResumeDocumentDetailResponse,
)
def get_document_detail(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> ResumeDocumentDetailResponse:
    document = get_owned_document_detail(
        db,
        job_id,
        batch_id,
        document_id,
        current_user.id,
    )
    return ResumeDocumentDetailResponse(
        **document_response(document).model_dump(),
        text_segments=[
            ResumeTextSegmentResponse.model_validate(segment)
            for segment in document.text_segments
        ],
    )


@router.get(
    "/{job_id}/batches/{batch_id}/documents/{document_id}/analysis",
    response_model=ScreeningResultResponse,
)
def get_document_analysis(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> ScreeningResultResponse:
    document = get_owned_document(
        db,
        job_id,
        batch_id,
        document_id,
        current_user.id,
    )
    result = get_latest_screening_result(db, document.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚无 AI 分析结果")
    return screening_result_response(result, document.candidate_code)


@router.post(
    "/{job_id}/batches/{batch_id}/documents/{document_id}/analysis-retry",
    response_model=AnalysisQueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_document_analysis(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> AnalysisQueueResponse:
    document = get_owned_document(
        db,
        job_id,
        batch_id,
        document_id,
        current_user.id,
    )
    if document.status != "completed" or document.redacted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="简历尚未完成解析和脱敏，不能开始 AI 分析",
        )
    processing_result = db.scalar(
        select(ScreeningResult.id).where(
            ScreeningResult.document_id == document.id,
            ScreeningResult.criteria_version_id == document.batch.criteria_version_id,
            ScreeningResult.status == "processing",
        )
    )
    if processing_result is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI 分析正在进行中")
    profile_id = db.scalar(
        select(CandidateProfile.id)
        .where(CandidateProfile.document_id == document.id)
        .order_by(CandidateProfile.version_number.desc())
        .limit(1)
    )
    latest_version = db.scalar(
        select(func.max(ScreeningResult.analysis_version)).where(
            ScreeningResult.document_id == document.id,
            ScreeningResult.criteria_version_id == document.batch.criteria_version_id,
        )
    )
    try:
        task_id = enqueue_resume_analysis(
            document.id,
            criteria_version_id=document.batch.criteria_version_id,
            candidate_profile_id=profile_id,
            analysis_version=(latest_version or 0) + 1,
        )
    except Exception as error:
        record_audit(
            db,
            action="screening.reanalysis_requested",
            target_type="resume_document",
            target_id=document.id,
            job_id=job_id,
            batch_id=batch_id,
            result="failure",
            actor=current_user,
            details={"scope": "candidate", "reason": "enqueue_failed"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI 分析任务创建失败，请稍后重试",
        ) from error
    record_audit(
        db,
        action="screening.reanalysis_requested",
        target_type="resume_document",
        target_id=document.id,
        job_id=job_id,
        batch_id=batch_id,
        result="success",
        actor=current_user,
        details={
            "scope": "candidate",
            "criteria_version_id": str(document.batch.criteria_version_id),
            "analysis_version": (latest_version or 0) + 1,
        },
    )
    db.commit()
    return AnalysisQueueResponse(status="queued", task_id=task_id)


@router.get("/{job_id}/batches/{batch_id}/documents/{document_id}/file")
def download_resume_file(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> FileResponse:
    document = get_owned_document(
        db,
        job_id,
        batch_id,
        document_id,
        current_user.id,
    )
    if not document.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原始文件不可用")
    path = resolve_private_file(settings.file_storage_root, document.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原始文件不存在")
    record_audit(
        db,
        action="resume.file_viewed",
        target_type="resume_document",
        target_id=document.id,
        job_id=job_id,
        batch_id=batch_id,
        result="success",
        actor=current_user,
    )
    db.commit()
    return FileResponse(
        path,
        media_type=document.content_type or "application/octet-stream",
        filename=document.original_filename,
    )


@router.delete(
    "/{job_id}/batches/{batch_id}",
    response_model=BatchDeletionResponse,
)
def delete_screening_batch(
    job_id: uuid.UUID,
    batch_id: uuid.UUID,
    payload: BatchDeletionRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> BatchDeletionResponse:
    batch = get_owned_batch(db, job_id, batch_id, current_user.id)
    if payload.confirmation != "永久删除":
        record_audit(
            db,
            action="batch.permanent_delete",
            target_type="screening_batch",
            target_id=batch.id,
            job_id=job_id,
            batch_id=batch.id,
            result="failure",
            actor=current_user,
            details={"reason": "confirmation_mismatch"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="请输入“永久删除”以确认该操作",
        )

    storage_keys = [
        document.storage_key
        for document in batch.documents
        if document.storage_key is not None
    ]
    try:
        staged_files = stage_batch_files(
            settings.file_storage_root,
            batch_id=batch.id,
            storage_keys=storage_keys,
        )
    except BatchDeletionError as error:
        record_audit(
            db,
            action="batch.permanent_delete",
            target_type="screening_batch",
            target_id=batch.id,
            job_id=job_id,
            batch_id=batch.id,
            result="failure",
            actor=current_user,
            details={"reason": "file_staging_failed"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error),
        ) from error

    document_count = len(batch.documents)
    file_count = len(staged_files.files)
    try:
        db.delete(batch)
        record_audit(
            db,
            action="batch.permanent_delete",
            target_type="screening_batch",
            target_id=batch.id,
            job_id=job_id,
            batch_id=batch.id,
            result="success",
            actor=current_user,
            details={
                "document_count": document_count,
                "file_count": file_count,
            },
        )
        db.commit()
    except Exception as error:
        db.rollback()
        try:
            staged_files.restore()
        except BatchDeletionError as restore_error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(restore_error),
            ) from restore_error
        record_audit(
            db,
            action="batch.permanent_delete",
            target_type="screening_batch",
            target_id=batch_id,
            job_id=job_id,
            batch_id=batch_id,
            result="failure",
            actor=current_user,
            details={"reason": "database_delete_failed"},
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="批次数据库删除失败，原始文件已恢复",
        ) from error

    try:
        staged_files.purge()
    except OSError:
        record_audit(
            db,
            action="batch.file_cleanup_pending",
            target_type="screening_batch",
            target_id=batch_id,
            job_id=job_id,
            batch_id=batch_id,
            result="failure",
            actor=current_user,
            details={"file_count": file_count},
        )
        db.commit()
        return BatchDeletionResponse(
            status="cleanup_pending",
            batch_id=batch_id,
            deleted_document_count=document_count,
            deleted_file_count=0,
            message="批次数据已删除，私有暂存文件将在服务重启时继续清理",
        )
    return BatchDeletionResponse(
        status="deleted",
        batch_id=batch_id,
        deleted_document_count=document_count,
        deleted_file_count=file_count,
    )
