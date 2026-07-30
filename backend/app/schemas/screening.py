import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RequirementStatus = Literal["passed", "failed", "unknown"]
AIGroup = Literal["passed", "low_match", "auto_rejected"]
AnalysisStatus = Literal["processing", "completed", "failed"]
ManualDecision = Literal["unprocessed", "shortlisted", "pending", "rejected"]
DecisionAction = Literal["shortlisted", "pending", "rejected"]


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_key: str = Field(pattern=r"^SEG-\d{4}$")
    quote: str = Field(
        min_length=1,
        max_length=1_000,
        description="从对应 segment_key 文本中逐字复制的连续原文，不得概括或改写",
    )

    @field_validator("quote")
    @classmethod
    def normalize_quote(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("证据引用不能为空")
        return value


class EducationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution: str = Field(default="", max_length=300)
    degree: str = Field(default="", max_length=100)
    field_of_study: str = Field(default="", max_length=200)
    start_date: str = Field(default="", max_length=50)
    end_date: str = Field(default="", max_length=50)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)


class WorkExperienceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str = Field(default="", max_length=300)
    title: str = Field(default="", max_length=200)
    start_date: str = Field(default="", max_length=50)
    end_date: str = Field(default="", max_length=50)
    summary: str = Field(default="", max_length=2_000)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)


class ProjectItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=300)
    role: str = Field(default="", max_length=200)
    summary: str = Field(default="", max_length=2_000)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)


class SkillItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    level: str = Field(default="", max_length=100)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)


class CertificationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=300)
    issuer: str = Field(default="", max_length=300)
    obtained_at: str = Field(default="", max_length=50)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)


class LanguageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str = Field(min_length=1, max_length=100)
    level: str = Field(default="", max_length=100)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)


class CandidateProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    education: list[EducationItem] = Field(default_factory=list, max_length=100)
    work_experiences: list[WorkExperienceItem] = Field(default_factory=list, max_length=100)
    projects: list[ProjectItem] = Field(default_factory=list, max_length=100)
    skills: list[SkillItem] = Field(default_factory=list, max_length=200)
    certifications: list[CertificationItem] = Field(default_factory=list, max_length=100)
    languages: list[LanguageItem] = Field(default_factory=list, max_length=100)


class CandidateProfileCorrectionRequest(CandidateProfileDraft):
    source_profile_id: uuid.UUID
    criteria_version_id: uuid.UUID


class ReanalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria_version_id: uuid.UUID
    candidate_profile_id: uuid.UUID | None = None


class BatchReanalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria_version_id: uuid.UUID


class HardRequirementJudgmentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: uuid.UUID
    status: RequirementStatus
    rationale: str = Field(min_length=1, max_length=2_000)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_evidence_for_definite_judgment(self) -> Self:
        if self.status != "unknown" and not self.evidence:
            raise ValueError("明确的硬性条件判断必须包含证据")
        return self


class DimensionScoreDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_id: uuid.UUID
    score: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=2_000)
    missing_items: list[str] = Field(default_factory=list, max_length=50)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=20)

    @field_validator("missing_items")
    @classmethod
    def normalize_missing_items(cls, values: list[str]) -> list[str]:
        return [item.strip() for item in values if item.strip()]

    @model_validator(mode="after")
    def require_evidence_or_missing_item(self) -> Self:
        if not self.evidence and not self.missing_items:
            raise ValueError("维度评分必须包含证据或明确的信息缺失项")
        return self


class ResumeAnalysisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_profile: CandidateProfileDraft
    hard_requirements: list[HardRequirementJudgmentDraft] = Field(
        default_factory=list, max_length=100
    )
    dimension_scores: list[DimensionScoreDraft] = Field(min_length=1, max_length=100)
    strengths: list[str] = Field(default_factory=list, max_length=50)
    gaps: list[str] = Field(default_factory=list, max_length=50)
    missing_items: list[str] = Field(default_factory=list, max_length=50)
    interview_questions: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("strengths", "gaps", "missing_items", "interview_questions")
    @classmethod
    def normalize_text_lists(cls, values: list[str]) -> list[str]:
        return [item.strip() for item in values if item.strip()]

    @model_validator(mode="after")
    def validate_unique_subjects(self) -> Self:
        requirement_ids = [item.requirement_id for item in self.hard_requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("硬性条件判断不能重复")
        dimension_ids = [item.dimension_id for item in self.dimension_scores]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("评分维度不能重复")
        return self


class CandidateProfileResponse(CandidateProfileDraft):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    source: Literal["ai", "manual"]
    source_profile_id: uuid.UUID | None
    model_name: str
    prompt_version: str
    created_at: datetime


class ReanalysisTaskResponse(BaseModel):
    status: Literal["queued", "enqueue_failed", "skipped"]
    document_id: uuid.UUID
    criteria_version_id: uuid.UUID
    analysis_version: int
    candidate_profile_id: uuid.UUID | None
    task_id: str | None = None
    message: str | None = None


class CandidateProfileCorrectionResponse(BaseModel):
    profile: CandidateProfileResponse
    reanalysis: ReanalysisTaskResponse


class BatchReanalysisResponse(BaseModel):
    status: Literal["queued", "partial_failure", "enqueue_failed"]
    batch_id: uuid.UUID
    criteria_version_id: uuid.UUID
    analysis_version: int
    queued_count: int
    failed_count: int
    skipped_count: int
    tasks: list[ReanalysisTaskResponse]


class HardRequirementJudgmentResponse(BaseModel):
    requirement_id: uuid.UUID
    requirement_type: str
    title: str
    expected_value: str
    auto_reject: bool
    status: RequirementStatus
    rationale: str
    evidence_segment_keys: list[str]


class EvidenceCitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_type: Literal["profile", "hard_requirement", "dimension"]
    subject_key: str
    segment_key: str
    quote: str
    source_type: str
    page_number: int | None
    paragraph_index: int | None
    sort_order: int


class DimensionScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scoring_dimension_id: uuid.UUID | None
    dimension_name: str
    score: int
    weight_percent: int
    weighted_score: float
    rationale: str
    missing_items: list[str]
    sort_order: int
    evidence: list[EvidenceCitationResponse] = Field(default_factory=list)


class RecruiterDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: DecisionAction
    reason: str | None = Field(default=None, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RecruiterDecisionResponse(BaseModel):
    id: uuid.UUID
    screening_result_id: uuid.UUID
    sequence_number: int
    previous_decision: ManualDecision
    decision: DecisionAction
    reason: str | None
    is_auto_rejection_override: bool
    operator_id: uuid.UUID
    operator_display_name: str
    created_at: datetime


class ScreeningResultSummaryResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    batch_id: uuid.UUID | None
    batch_name: str
    document_id: uuid.UUID
    candidate_code: str
    criteria_version_id: uuid.UUID
    criteria_version_number: int
    analysis_version: int
    status: AnalysisStatus
    ai_group: AIGroup | None
    total_score: float | None
    pass_threshold: int
    current_decision: ManualDecision
    latest_decision_at: datetime | None
    created_at: datetime


class OriginalEvidenceResponse(BaseModel):
    citation_id: uuid.UUID
    segment_key: str
    quote: str
    original_text: str
    source_type: str
    page_number: int | None
    paragraph_index: int | None


class CandidateComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_ids: list[uuid.UUID] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_unique_results(self) -> Self:
        if len(self.result_ids) != len(set(self.result_ids)):
            raise ValueError("对比候选人不能重复")
        return self


class ScreeningResultResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    document_id: uuid.UUID
    candidate_code: str
    criteria_version_id: uuid.UUID
    criteria_version_number: int
    analysis_version: int
    status: AnalysisStatus
    ai_group: AIGroup | None
    total_score: float | None
    pass_threshold: int
    hard_requirements: list[HardRequirementJudgmentResponse]
    strengths: list[str]
    gaps: list[str]
    missing_items: list[str]
    interview_questions: list[str]
    model_name: str
    prompt_version: str
    failure_code: str | None
    failure_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    candidate_profile: CandidateProfileResponse | None
    dimension_scores: list[DimensionScoreResponse]
    evidence: list[EvidenceCitationResponse]
    current_decision: ManualDecision = "unprocessed"
    decision_history: list[RecruiterDecisionResponse] = Field(default_factory=list)


class CandidateComparisonResponse(BaseModel):
    job_id: uuid.UUID
    criteria_version_id: uuid.UUID
    criteria_version_number: int
    analysis_version: int
    candidates: list[ScreeningResultResponse]


class AnalysisQueueResponse(BaseModel):
    status: Literal["queued"]
    task_id: str
