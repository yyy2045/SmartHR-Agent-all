from __future__ import annotations

import hashlib
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AiCallLog,
    AiEvaluationDataset,
    AiEvaluationErrorCase,
    AiEvaluationResult,
    AiEvaluationRun,
    AiEvaluationSample,
    AiTask,
    AiTaskEvent,
    ApplicationResumeDocument,
    Candidate,
    CandidateProcess,
    CandidateProcessEvent,
    CandidateProfile,
    DimensionScore,
    EvidenceCitation,
    HardRequirement,
    Job,
    JobApplication,
    JobCriteriaVersion,
    RecruiterDecision,
    RecruitmentKnowledgeBase,
    RecruitmentKnowledgeChunk,
    RecruitmentKnowledgeDocument,
    RecruitmentKnowledgeDocumentVersion,
    ResumeDocument,
    ResumeTextSegment,
    Role,
    ScoringDimension,
    ScreeningBatch,
    ScreeningResult,
    User,
    UserRole,
)
from app.models.user import ROLE_LABELS
from app.services.prompt_template_defaults import ensure_default_prompt_templates
from app.services.security import hash_password

DEMO_PASSWORD = "Demo@123456"
DEMO_NAMESPACE = uuid.UUID("4f7986f4-7b8e-49f8-86af-f63e71a4f3db")
DEMO_JOB_TITLE = "DEMO-AI应用工程师"
DEMO_BATCH_NAME = "DEMO-候选人演示批次"
DEMO_KNOWLEDGE_BASE_NAME = "DEMO-招聘知识库"
DEMO_EVALUATION_DATASET_CODE = "demo-resume-analysis"


@dataclass(frozen=True)
class DemoSeedSummary:
    users: int
    jobs: int
    candidates: int
    applications: int
    ai_calls: int
    ai_tasks: int
    knowledge_documents: int
    evaluation_samples: int


@dataclass(frozen=True)
class DemoCandidateSeed:
    name: str
    phone: str
    email: str
    stage: str
    ai_group: str
    score: Decimal
    decision: str | None
    resume_text: str
    strengths: tuple[str, ...]
    gaps: tuple[str, ...]
    skills: tuple[str, ...]


DEMO_CANDIDATES = (
    DemoCandidateSeed(
        name="林知远",
        phone="13800010001",
        email="lin.zhiyuan.demo@example.com",
        stage="shortlisted",
        ai_group="passed",
        score=Decimal("88.50"),
        decision="shortlisted",
        resume_text=(
            "林知远，5年 Python/FastAPI 后端开发经验，主导过 Celery 异步任务、"
            "PostgreSQL 性能优化和 RAG 知识库接入。熟悉 Docker、Redis、向量检索，"
            "曾把 AI 简历初筛延迟从分钟级优化到秒级。"
        ),
        strengths=("后端工程经验扎实", "有 AI 工程化落地经验", "熟悉异步任务与向量检索"),
        gaps=("需要进一步确认团队协作和复杂业务抽象能力",),
        skills=("Python", "FastAPI", "Celery", "PostgreSQL", "RAG"),
    ),
    DemoCandidateSeed(
        name="周予安",
        phone="13800010002",
        email="zhou.yuan.demo@example.com",
        stage="to_interview",
        ai_group="passed",
        score=Decimal("82.00"),
        decision="shortlisted",
        resume_text=(
            "周予安，4年全栈开发经验，参与招聘 SaaS 项目，负责 React 前端、"
            "FastAPI 接口和 Prompt 模板管理。对可解释 AI、日志追踪和结构化输出有实践。"
        ),
        strengths=("前后端协作能力强", "理解 PromptOps 和可追溯日志", "产品意识较好"),
        gaps=("深度后端性能优化经验需要面试确认",),
        skills=("React", "TypeScript", "FastAPI", "PromptOps"),
    ),
    DemoCandidateSeed(
        name="陈沐",
        phone="13800010003",
        email="chen.mu.demo@example.com",
        stage="pending",
        ai_group="low_match",
        score=Decimal("64.00"),
        decision="pending",
        resume_text=(
            "陈沐，2年 Java 后端经验，熟悉 Spring Boot、MySQL 和基础 Redis。"
            "近期自学 LLM 应用开发，完成过简单的知识库问答 Demo。"
        ),
        strengths=("基础后端能力可迁移", "有学习 AI 应用的主动性"),
        gaps=("Python/FastAPI 生产经验不足", "RAG 与异步任务经验偏浅"),
        skills=("Java", "Spring Boot", "MySQL", "Redis"),
    ),
    DemoCandidateSeed(
        name="吴晚晴",
        phone="13800010004",
        email="wu.wanqing.demo@example.com",
        stage="rejected",
        ai_group="auto_rejected",
        score=Decimal("41.50"),
        decision="rejected",
        resume_text=(
            "吴晚晴，1年前端开发经验，主要负责活动页和后台表单。未体现后端服务、"
            "异步任务、数据库建模或 AI 工程化项目经验。"
        ),
        strengths=("前端基础可用",),
        gaps=("后端经验不足", "未体现 AI 工程化能力", "不满足最低 3 年服务端经验"),
        skills=("Vue", "JavaScript", "CSS"),
    ),
)


def stable_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, key)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_roles(db: Session) -> dict[str, Role]:
    roles = {role.key: role for role in db.scalars(select(Role)).all()}
    for key, display_name in ROLE_LABELS.items():
        if key not in roles:
            role = Role(key=key, display_name=display_name)
            db.add(role)
            roles[key] = role
    db.flush()
    return roles


def _ensure_user(
    db: Session,
    *,
    username: str,
    display_name: str,
    role_keys: tuple[str, ...],
    roles: dict[str, Role],
) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(
            id=stable_uuid(f"user:{username}"),
            username=username,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name=display_name,
            must_change_password=False,
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        user.display_name = display_name
        user.is_active = True
        user.must_change_password = False

    existing_role_keys = set(user.role_keys)
    for key in role_keys:
        if key not in existing_role_keys:
            user.role_assignments.append(UserRole(role=roles[key]))
    return user


def _ensure_demo_users(db: Session) -> dict[str, User]:
    roles = _ensure_roles(db)
    return {
        "admin": _ensure_user(
            db,
            username="demo-admin",
            display_name="演示管理员",
            role_keys=("administrator",),
            roles=roles,
        ),
        "recruiter": _ensure_user(
            db,
            username="demo-recruiter",
            display_name="演示招聘专员",
            role_keys=("recruiter",),
            roles=roles,
        ),
        "manager": _ensure_user(
            db,
            username="demo-manager",
            display_name="演示用人经理",
            role_keys=("hiring_manager",),
            roles=roles,
        ),
        "approver": _ensure_user(
            db,
            username="demo-approver",
            display_name="演示审批人",
            role_keys=("approver",),
            roles=roles,
        ),
    }


def _ensure_job(
    db: Session, users: dict[str, User], now: datetime
) -> tuple[Job, JobCriteriaVersion]:
    job = db.scalar(select(Job).where(Job.title == DEMO_JOB_TITLE))
    if job is None:
        job = Job(
            id=stable_uuid("job:ai-application-engineer"),
            owner_id=users["recruiter"].id,
            hiring_manager_id=users["manager"].id,
            title=DEMO_JOB_TITLE,
            department="AI平台组",
            original_jd=(
                "负责企业招聘场景中的 AI Agent 工程化落地，包括 FastAPI 后端、"
                "Celery 异步任务、Prompt 版本管理、RAG 检索、pgvector 向量索引和"
                "可观测性建设。要求 3 年以上服务端经验，熟悉 Python 和数据库建模。"
            ),
            status="active",
        )
        db.add(job)
        db.flush()
    else:
        job.owner_id = users["recruiter"].id
        job.hiring_manager_id = users["manager"].id
        job.status = "active"

    criteria = db.scalar(
        select(JobCriteriaVersion).where(
            JobCriteriaVersion.job_id == job.id,
            JobCriteriaVersion.version_number == 1,
        )
    )
    if criteria is None:
        criteria = JobCriteriaVersion(
            id=stable_uuid("criteria:ai-application-engineer:v1"),
            job_id=job.id,
            version_number=1,
            status="confirmed",
            pass_threshold=70,
            confirmed_by_id=users["recruiter"].id,
            confirmed_at=now,
        )
        criteria.hard_requirements.extend(
            [
                HardRequirement(
                    requirement_type="min_experience_years",
                    title="服务端开发经验",
                    description="要求至少 3 年服务端工程经验。",
                    expected_value="3",
                    auto_reject=True,
                    sort_order=0,
                ),
                HardRequirement(
                    requirement_type="other",
                    title="AI 工程化理解",
                    description="理解 Prompt、RAG、异步任务和可观测性至少一项。",
                    expected_value="有相关实践或清晰理解",
                    auto_reject=False,
                    sort_order=1,
                ),
            ]
        )
        criteria.scoring_dimensions.extend(
            [
                ScoringDimension(
                    name="后端工程能力",
                    description="服务端架构、数据库建模、接口设计和工程质量。",
                    weight_percent=40,
                    sort_order=0,
                ),
                ScoringDimension(
                    name="AI 工程化能力",
                    description="LLM 接入、PromptOps、RAG、评测和可观测性。",
                    weight_percent=40,
                    sort_order=1,
                ),
                ScoringDimension(
                    name="业务理解与协作",
                    description="能否把 AI 能力放进真实招聘流程中协作落地。",
                    weight_percent=20,
                    sort_order=2,
                ),
            ]
        )
        db.add(criteria)
        db.flush()
    return job, criteria


def _ensure_batch(db: Session, job: Job, criteria: JobCriteriaVersion) -> ScreeningBatch:
    batch = db.scalar(
        select(ScreeningBatch).where(
            ScreeningBatch.job_id == job.id,
            ScreeningBatch.name == DEMO_BATCH_NAME,
        )
    )
    if batch is None:
        batch = ScreeningBatch(
            id=stable_uuid("batch:demo-candidates"),
            job_id=job.id,
            criteria_version_id=criteria.id,
            name=DEMO_BATCH_NAME,
            ai_input_mode="raw",
            status="completed",
        )
        db.add(batch)
        db.flush()
    else:
        batch.criteria_version_id = criteria.id
        batch.ai_input_mode = "raw"
        batch.status = "completed"
    return batch


def _ensure_candidate_graph(
    db: Session,
    *,
    seed: DemoCandidateSeed,
    index: int,
    users: dict[str, User],
    job: Job,
    criteria: JobCriteriaVersion,
    batch: ScreeningBatch,
    now: datetime,
) -> None:
    candidate = db.scalar(select(Candidate).where(Candidate.email == seed.email))
    if candidate is None:
        candidate = Candidate(
            id=stable_uuid(f"candidate:{seed.email}"),
            full_name=seed.name,
            phone=seed.phone,
            email=seed.email,
            full_name_normalized=seed.name.lower(),
            phone_normalized=seed.phone,
            email_normalized=seed.email.lower(),
            experience_fingerprint=sha256_text(seed.resume_text)[:32],
            status="active",
        )
        db.add(candidate)
        db.flush()
    else:
        candidate.full_name = seed.name
        candidate.phone = seed.phone
        candidate.email = seed.email
        candidate.status = "active"

    application = db.scalar(
        select(JobApplication).where(
            JobApplication.candidate_id == candidate.id,
            JobApplication.job_id == job.id,
            JobApplication.status == "active",
        )
    )
    if application is None:
        application = JobApplication(
            id=stable_uuid(f"application:{job.id}:{seed.email}"),
            candidate_id=candidate.id,
            job_id=job.id,
            status="active",
            source_type="resume_upload",
        )
        db.add(application)
        db.flush()

    document = db.scalar(
        select(ResumeDocument).where(
            ResumeDocument.sha256 == sha256_text(f"demo-resume:{seed.email}")
        )
    )
    if document is None:
        document = ResumeDocument(
            id=stable_uuid(f"resume:{seed.email}"),
            batch_id=batch.id,
            candidate_id=candidate.id,
            application_id=application.id,
            original_filename=f"DEMO-{seed.name}-简历.txt",
            file_extension=".txt",
            content_type="text/plain",
            detected_type="txt",
            size_bytes=len(seed.resume_text.encode("utf-8")),
            sha256=sha256_text(f"demo-resume:{seed.email}"),
            storage_key=f"demo/resumes/{seed.email}.txt",
            extraction_method="demo_seed",
            segment_count=1,
            text_character_count=len(seed.resume_text),
            status="completed",
            parsed_at=now,
        )
        db.add(document)
        db.flush()
    else:
        document.batch_id = batch.id
        document.candidate_id = candidate.id
        document.application_id = application.id
        document.status = "completed"

    link = db.get(
        ApplicationResumeDocument, {"application_id": application.id, "document_id": document.id}
    )
    if link is None:
        db.add(ApplicationResumeDocument(application_id=application.id, document_id=document.id))
        db.flush()
    application.primary_document_id = document.id

    segment = db.scalar(
        select(ResumeTextSegment).where(
            ResumeTextSegment.document_id == document.id,
            ResumeTextSegment.segment_key == "S1",
        )
    )
    if segment is None:
        segment = ResumeTextSegment(
            id=stable_uuid(f"segment:{seed.email}:S1"),
            document_id=document.id,
            segment_key="S1",
            source_type="docx_paragraph",
            source_index=0,
            paragraph_index=0,
            raw_text=seed.resume_text,
            normalized_text=seed.resume_text,
            sort_order=0,
        )
        db.add(segment)
        db.flush()

    profile = db.scalar(
        select(CandidateProfile).where(
            CandidateProfile.document_id == document.id,
            CandidateProfile.version_number == 1,
        )
    )
    if profile is None:
        profile = CandidateProfile(
            id=stable_uuid(f"profile:{seed.email}:v1"),
            document_id=document.id,
            version_number=1,
            source="ai",
            model_name="demo-seed-model",
            prompt_version="demo-resume-analysis-v1",
            education=[{"school": "演示大学", "degree": "本科", "major": "计算机科学"}],
            work_experiences=[
                {"company": "演示科技", "title": "后端工程师", "summary": seed.resume_text}
            ],
            projects=[{"name": "AI 招聘平台", "description": seed.resume_text}],
            skills=[{"name": skill, "level": "熟悉"} for skill in seed.skills],
        )
        db.add(profile)
        db.flush()

    result = db.scalar(
        select(ScreeningResult).where(
            ScreeningResult.application_id == application.id,
            ScreeningResult.criteria_version_id == criteria.id,
            ScreeningResult.analysis_version == 1,
        )
    )
    if result is None:
        result = ScreeningResult(
            id=stable_uuid(f"screening-result:{seed.email}:v1"),
            document_id=document.id,
            application_id=application.id,
            candidate_profile_id=profile.id,
            criteria_version_id=criteria.id,
            analysis_version=1,
            status="completed",
            ai_group=seed.ai_group,
            total_score=seed.score,
            pass_threshold=criteria.pass_threshold,
            hard_requirement_results=[
                {
                    "title": "服务端开发经验",
                    "status": "passed" if seed.score >= 70 else "failed",
                    "evidence": seed.resume_text[:80],
                }
            ],
            strengths=list(seed.strengths),
            gaps=list(seed.gaps),
            missing_items=[] if seed.score >= 70 else ["缺少足够的 AI 工程化生产证据"],
            interview_questions=[
                "请介绍一次你把 AI 能力接入真实业务流程的经验。",
                "如果 AI 返回格式不稳定，你会如何设计兜底？",
            ],
            model_name="demo-seed-model",
            prompt_version="demo-resume-analysis-v1",
            started_at=now - timedelta(minutes=10 - index),
            completed_at=now - timedelta(minutes=9 - index),
        )
        db.add(result)
        db.flush()

        for dimension_index, (dimension, score) in enumerate(
            zip(
                criteria.scoring_dimensions,
                (int(seed.score), max(40, int(seed.score) - 5), 76),
                strict=False,
            )
        ):
            weighted = Decimal(score * dimension.weight_percent) / Decimal(100)
            dimension_score = DimensionScore(
                screening_result_id=result.id,
                scoring_dimension_id=dimension.id,
                dimension_name=dimension.name,
                score=score,
                weight_percent=dimension.weight_percent,
                weighted_score=weighted,
                rationale=f"演示数据：{seed.name} 在「{dimension.name}」维度得分 {score}。",
                missing_items=[],
                sort_order=dimension_index,
            )
            db.add(dimension_score)
            db.flush()
            db.add(
                EvidenceCitation(
                    screening_result_id=result.id,
                    dimension_score_id=dimension_score.id,
                    segment_id=segment.id,
                    subject_type="dimension",
                    subject_key=dimension.name,
                    segment_key="S1",
                    quote=seed.resume_text[:80],
                    source_type=segment.source_type,
                    paragraph_index=0,
                    sort_order=dimension_index,
                )
            )
        if seed.decision is not None:
            db.add(
                RecruiterDecision(
                    screening_result_id=result.id,
                    operator_id=users["recruiter"].id,
                    sequence_number=1,
                    previous_decision="unprocessed",
                    decision=seed.decision,
                    reason="演示数据：用于展示人工最终决策不会被 AI 自动替代。",
                )
            )

    process = db.scalar(
        select(CandidateProcess).where(CandidateProcess.application_id == application.id)
    )
    if process is None:
        process = CandidateProcess(
            id=stable_uuid(f"process:{seed.email}"),
            application_id=application.id,
            current_stage=seed.stage,
            stage_entered_at=now - timedelta(days=4 - index),
            updated_by_id=users["recruiter"].id,
        )
        process.events.append(
            CandidateProcessEvent(
                sequence_number=1,
                from_stage="unprocessed",
                to_stage=seed.stage,
                reason="演示数据：初始化候选人流程阶段。",
                operator_id=users["recruiter"].id,
            )
        )
        db.add(process)
    else:
        process.current_stage = seed.stage
        process.updated_by_id = users["recruiter"].id


def _ensure_ai_observability(
    db: Session, users: dict[str, User], job: Job, batch: ScreeningBatch, now: datetime
) -> None:
    task_specs = (
        (
            "demo-ai-task-resume-analysis",
            "简历 AI 初筛演示任务",
            "resume_analysis",
            "succeeded",
            None,
        ),
        (
            "demo-ai-task-candidate-qa",
            "候选人问答 Agent 演示任务",
            "candidate_qa",
            "succeeded",
            None,
        ),
        (
            "demo-ai-task-timeout",
            "AI 服务超时降级演示任务",
            "interview_report",
            "failed",
            "timeout",
        ),
    )
    for stable_key, task_name, scenario, status, failure_code in task_specs:
        task = db.get(AiTask, stable_uuid(f"ai-task:{stable_key}"))
        if task is None:
            completed = now - timedelta(minutes=3) if status in {"succeeded", "failed"} else None
            task = AiTask(
                id=stable_uuid(f"ai-task:{stable_key}"),
                celery_task_id=stable_key,
                task_name=task_name,
                scenario=scenario,
                status=status,
                attempt_count=1,
                max_retries=2,
                created_by_id=users["recruiter"].id,
                resource_type="job",
                resource_id=job.id,
                job_id=job.id,
                batch_id=batch.id,
                failure_code=failure_code,
                failure_message="演示数据：上游响应超时，业务已切换人工降级。"
                if failure_code
                else None,
                duration_ms=1420 if status == "succeeded" else 120000,
                started_at=now - timedelta(minutes=5),
                completed_at=completed,
            )
            task.events.append(
                AiTaskEvent(
                    event_type="queued",
                    status_after="queued",
                    message="演示数据：任务进入队列。",
                )
            )
            task.events.append(
                AiTaskEvent(
                    event_type="succeeded" if status == "succeeded" else "failed",
                    status_after=status,
                    message="演示数据：任务完成。"
                    if status == "succeeded"
                    else "演示数据：任务失败并允许人工降级。",
                )
            )
            db.add(task)
            db.flush()

        call = db.scalar(
            select(AiCallLog).where(
                AiCallLog.scenario == scenario,
                AiCallLog.resource_id == job.id,
                AiCallLog.model_name == "demo-seed-model",
            )
        )
        if call is None:
            db.add(
                AiCallLog(
                    id=stable_uuid(f"ai-call:{stable_key}"),
                    task_id=task.id,
                    scenario=scenario,
                    status="failed" if failure_code else "succeeded",
                    model_name="demo-seed-model",
                    prompt_version=f"demo-{scenario}-v1",
                    retry_count=1 if failure_code else 0,
                    duration_ms=task.duration_ms,
                    input_tokens=1800,
                    output_tokens=640 if not failure_code else 0,
                    total_tokens=2440 if not failure_code else 1800,
                    invoked_by_id=users["recruiter"].id,
                    resource_type="job",
                    resource_id=job.id,
                    job_id=job.id,
                    batch_id=batch.id,
                    failure_code=failure_code,
                    failure_message=task.failure_message,
                )
            )


def _ensure_recruitment_knowledge(
    db: Session, users: dict[str, User], job: Job, now: datetime
) -> None:
    base = db.scalar(
        select(RecruitmentKnowledgeBase).where(
            RecruitmentKnowledgeBase.name == DEMO_KNOWLEDGE_BASE_NAME
        )
    )
    if base is None:
        base = RecruitmentKnowledgeBase(
            id=stable_uuid("rkb:demo"),
            name=DEMO_KNOWLEDGE_BASE_NAME,
            description="演示数据：用于展示 RAG 如何为招聘 AI 结果提供企业规范引用。",
            status="active",
            created_by_id=users["admin"].id,
            created_by_username=users["admin"].username,
            created_by_display_name=users["admin"].display_name,
        )
        db.add(base)
        db.flush()

    docs = (
        (
            "DEMO-AI岗位能力模型",
            "job_standard",
            ["AI工程化", "岗位标准"],
            "AI 应用工程师应具备后端工程、异步任务、PromptOps、RAG、评测与可观测性能力。",
        ),
        (
            "DEMO-面试评分标准",
            "interview",
            ["面试", "评分"],
            "面试评价应区分事实证据、风险判断和最终人工决策，AI 只能辅助总结，不能自动录用或淘汰。",
        ),
    )
    for index, (title, category, tags, raw_text) in enumerate(docs):
        document = db.scalar(
            select(RecruitmentKnowledgeDocument).where(
                RecruitmentKnowledgeDocument.knowledge_base_id == base.id,
                RecruitmentKnowledgeDocument.title == title,
            )
        )
        if document is None:
            document = RecruitmentKnowledgeDocument(
                id=stable_uuid(f"rkd:{title}"),
                knowledge_base_id=base.id,
                title=title,
                summary=raw_text,
                category=category,
                tags=tags,
                visibility_scope="all_internal",
                related_job_id=job.id if index == 0 else None,
                status="active",
                current_version_number=1,
                created_by_id=users["admin"].id,
                created_by_username=users["admin"].username,
                created_by_display_name=users["admin"].display_name,
            )
            db.add(document)
            db.flush()

        version = db.scalar(
            select(RecruitmentKnowledgeDocumentVersion).where(
                RecruitmentKnowledgeDocumentVersion.document_id == document.id,
                RecruitmentKnowledgeDocumentVersion.version_number == 1,
            )
        )
        if version is None:
            version = RecruitmentKnowledgeDocumentVersion(
                id=stable_uuid(f"rkdv:{title}:v1"),
                document_id=document.id,
                version_number=1,
                status="published",
                idempotency_key=stable_uuid(f"rkdv-idempotency:{title}:v1"),
                source_type="manual",
                content_hash=sha256_text(raw_text),
                change_note="演示数据初始化",
                raw_text=raw_text,
                parser_name="demo_seed",
                parser_version="v1",
                chunk_count=1,
                created_by_id=users["admin"].id,
                created_by_username=users["admin"].username,
                created_by_display_name=users["admin"].display_name,
                published_by_id=users["admin"].id,
                published_by_username=users["admin"].username,
                published_by_display_name=users["admin"].display_name,
                published_at=now,
            )
            db.add(version)
            db.flush()
            document.current_version_number = 1

        chunk = db.scalar(
            select(RecruitmentKnowledgeChunk).where(
                RecruitmentKnowledgeChunk.document_version_id == version.id,
                RecruitmentKnowledgeChunk.chunk_index == 0,
                RecruitmentKnowledgeChunk.embedding_model == "demo-embedding",
                RecruitmentKnowledgeChunk.embedding_version == "v1",
            )
        )
        if chunk is None:
            db.add(
                RecruitmentKnowledgeChunk(
                    id=stable_uuid(f"rkc:{title}:0"),
                    knowledge_base_id=base.id,
                    document_id=document.id,
                    document_version_id=version.id,
                    chunk_index=0,
                    chunk_text=raw_text,
                    heading_path=[title],
                    source_locator=f"{title}#0",
                    content_hash=sha256_text(raw_text),
                    embedding_model="demo-embedding",
                    embedding_dimension=3,
                    embedding_version="v1",
                    embedding=[1.0, 0.0, 0.0] if index == 0 else [0.0, 1.0, 0.0],
                    status="completed",
                    embedded_at=now,
                )
            )


def _ensure_ai_evaluation(db: Session, users: dict[str, User], now: datetime) -> None:
    dataset = db.scalar(
        select(AiEvaluationDataset).where(AiEvaluationDataset.code == DEMO_EVALUATION_DATASET_CODE)
    )
    if dataset is None:
        dataset = AiEvaluationDataset(
            id=stable_uuid("ai-eval-dataset:demo-resume-analysis"),
            code=DEMO_EVALUATION_DATASET_CODE,
            name="DEMO-简历评分评测集",
            scenario="resume_analysis",
            description="演示数据：固定小样本，用于展示 AI 评测与错误案例沉淀。",
            version_number=1,
            status="active",
            created_by_id=users["admin"].id,
        )
        db.add(dataset)
        db.flush()

    samples = (
        ("DEMO-CASE-01", "高匹配候选人应推荐", "passed", "easy"),
        ("DEMO-CASE-02", "经验不足候选人应保留观察", "low_match", "medium"),
        ("DEMO-CASE-03", "硬性条件不足应淘汰", "auto_rejected", "hard"),
    )
    sample_objects: list[AiEvaluationSample] = []
    for case_key, title, recommendation, difficulty in samples:
        sample = db.scalar(
            select(AiEvaluationSample).where(
                AiEvaluationSample.dataset_id == dataset.id,
                AiEvaluationSample.case_key == case_key,
            )
        )
        if sample is None:
            sample = AiEvaluationSample(
                id=stable_uuid(f"ai-eval-sample:{case_key}"),
                dataset_id=dataset.id,
                case_key=case_key,
                title=title,
                scenario="resume_analysis",
                difficulty=difficulty,
                input_payload={"job": DEMO_JOB_TITLE, "resume": title},
                expected_output={"ai_group": recommendation},
                expected_recommendation=recommendation,
                expected_evidence_keywords=["经验", "AI", "后端"],
                tags=["demo"],
            )
            db.add(sample)
            db.flush()
        sample_objects.append(sample)

    run = db.get(AiEvaluationRun, stable_uuid("ai-eval-run:demo"))
    if run is None:
        run = AiEvaluationRun(
            id=stable_uuid("ai-eval-run:demo"),
            dataset_id=dataset.id,
            name="DEMO-离线评测运行",
            scenario="resume_analysis",
            status="failed",
            model_name="demo-seed-model",
            prompt_version="demo-resume-analysis-v1",
            run_config={"mode": "demo_seed", "forced_error_cases": ["DEMO-CASE-03"]},
            metrics_summary={"pass_rate": 0.67, "error_counts": {"evidence_missing": 1}},
            total_samples=3,
            completed_samples=3,
            passed_samples=2,
            failed_samples=1,
            average_score=0.67,
            duration_ms=980,
            created_by_id=users["admin"].id,
            started_at=now - timedelta(minutes=20),
            completed_at=now - timedelta(minutes=19),
        )
        db.add(run)
        db.flush()
        for index, sample in enumerate(sample_objects):
            failed = sample.case_key == "DEMO-CASE-03"
            result = AiEvaluationResult(
                id=stable_uuid(f"ai-eval-result:{sample.case_key}"),
                run_id=run.id,
                sample_id=sample.id,
                status="failed" if failed else "passed",
                score=0.2 if failed else 1.0,
                actual_output={
                    "ai_group": "low_match" if failed else sample.expected_recommendation
                },
                expected_snapshot=sample.expected_output,
                error_types=["evidence_missing"] if failed else [],
                evidence_coverage_score=0.3 if failed else 1.0,
                format_valid=True,
                recommendation_matched=not failed,
                duration_ms=300 + index * 10,
                input_tokens=900,
                output_tokens=280,
                total_tokens=1180,
            )
            db.add(result)
            db.flush()
            if failed:
                db.add(
                    AiEvaluationErrorCase(
                        id=stable_uuid(f"ai-eval-error:{sample.case_key}:evidence_missing"),
                        result_id=result.id,
                        dataset_id=dataset.id,
                        run_id=run.id,
                        sample_id=sample.id,
                        error_type="evidence_missing",
                        severity="medium",
                        status="open",
                        title="DEMO-证据引用不足",
                        description="演示数据：模型给出了风险判断，但没有给出足够可追溯证据。",
                        expected_behavior="应引用简历中的明确经历或缺失信息。",
                        actual_behavior="只给出概括性结论。",
                        created_by_id=users["admin"].id,
                    )
                )


def seed_demo_data(db: Session) -> DemoSeedSummary:
    now = datetime.now(UTC)
    users = _ensure_demo_users(db)
    ensure_default_prompt_templates(lambda: nullcontext(db))
    job, criteria = _ensure_job(db, users, now)
    batch = _ensure_batch(db, job, criteria)
    for index, candidate_seed in enumerate(DEMO_CANDIDATES):
        _ensure_candidate_graph(
            db,
            seed=candidate_seed,
            index=index,
            users=users,
            job=job,
            criteria=criteria,
            batch=batch,
            now=now,
        )
    _ensure_ai_observability(db, users, job, batch, now)
    _ensure_recruitment_knowledge(db, users, job, now)
    _ensure_ai_evaluation(db, users, now)
    db.commit()
    return DemoSeedSummary(
        users=db.scalar(select(func.count(User.id)).where(User.username.like("demo-%"))) or 0,
        jobs=db.scalar(select(func.count(Job.id)).where(Job.title.like("DEMO-%"))) or 0,
        candidates=db.scalar(
            select(func.count(Candidate.id)).where(Candidate.email.like("%.demo@example.com"))
        )
        or 0,
        applications=(
            db.scalar(
                select(func.count(JobApplication.id))
                .join(Candidate, Candidate.id == JobApplication.candidate_id)
                .where(Candidate.email.like("%.demo@example.com"))
            )
            or 0
        ),
        ai_calls=db.scalar(
            select(func.count(AiCallLog.id)).where(AiCallLog.model_name == "demo-seed-model")
        )
        or 0,
        ai_tasks=db.scalar(
            select(func.count(AiTask.id)).where(AiTask.celery_task_id.like("demo-ai-task-%"))
        )
        or 0,
        knowledge_documents=(
            db.scalar(
                select(func.count(RecruitmentKnowledgeDocument.id))
                .join(RecruitmentKnowledgeBase)
                .where(RecruitmentKnowledgeBase.name == DEMO_KNOWLEDGE_BASE_NAME)
            )
            or 0
        ),
        evaluation_samples=(
            db.scalar(
                select(func.count(AiEvaluationSample.id))
                .join(AiEvaluationDataset)
                .where(AiEvaluationDataset.code == DEMO_EVALUATION_DATASET_CODE)
            )
            or 0
        ),
    )


def main() -> None:
    with SessionLocal() as db:
        summary = seed_demo_data(db)
    print(
        "Demo seed completed: "
        f"users={summary.users}, jobs={summary.jobs}, candidates={summary.candidates}, "
        f"applications={summary.applications}, ai_tasks={summary.ai_tasks}, "
        f"ai_calls={summary.ai_calls}, knowledge_documents={summary.knowledge_documents}, "
        f"evaluation_samples={summary.evaluation_samples}"
    )
    print(f"Demo login: demo-admin / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
