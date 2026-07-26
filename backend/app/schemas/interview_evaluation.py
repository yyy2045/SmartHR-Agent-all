import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InterviewEvaluationStatus = Literal["draft", "submitted"]
OverallRecommendation = Literal[
    "strongly_recommend",
    "recommend",
    "reserve",
    "not_recommend",
]


def _strip_text(value: str) -> str:
    return value.strip()


class InterviewQuestionResponseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    answer_summary: str = Field(default="", max_length=10_000)
    evidence: str = Field(default="", max_length=10_000)

    _normalize_answer = field_validator("answer_summary", mode="after")(_strip_text)
    _normalize_evidence = field_validator("evidence", mode="after")(_strip_text)


class InterviewDimensionRatingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_id: uuid.UUID
    score: int | None = Field(default=None, ge=1, le=5)
    evidence: str = Field(default="", max_length=10_000)

    _normalize_evidence = field_validator("evidence", mode="after")(_strip_text)


class InterviewEvaluationDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_recommendation: OverallRecommendation | None = None
    overall_comment: str = Field(default="", max_length=10_000)
    question_responses: list[InterviewQuestionResponseInput] = Field(
        default_factory=list,
        max_length=100,
    )
    dimension_ratings: list[InterviewDimensionRatingInput] = Field(
        default_factory=list,
        max_length=50,
    )

    _normalize_comment = field_validator("overall_comment", mode="after")(_strip_text)

    @model_validator(mode="after")
    def validate_unique_items(self) -> Self:
        question_ids = [item.question_id for item in self.question_responses]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("面试问题不能重复")
        dimension_ids = [item.dimension_id for item in self.dimension_ratings]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("评分维度不能重复")
        return self


class InterviewQuestionResponseRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    answer_summary: str
    evidence: str


class InterviewDimensionRatingRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dimension_id: uuid.UUID
    score: int | None
    evidence: str


class InterviewEvaluationRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: InterviewEvaluationStatus
    overall_recommendation: OverallRecommendation | None
    overall_comment: str
    total_score: float | None
    passed: bool | None
    submitted_by_id: uuid.UUID | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    question_responses: list[InterviewQuestionResponseRecord]
    dimension_ratings: list[InterviewDimensionRatingRecord]


class InterviewScoreAnchorContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score_value: int
    description: str


class InterviewQuestionContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_text: str
    evaluation_guide: str
    sort_order: int


class InterviewDimensionContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    weight_percent: int
    sort_order: int
    anchors: list[InterviewScoreAnchorContext]


class InterviewEvaluationContextResponse(BaseModel):
    round_id: uuid.UUID
    plan_round_id: uuid.UUID
    round_name: str
    round_type: str
    round_status: str
    pass_threshold: int
    scheduled_start_at: datetime
    questions: list[InterviewQuestionContext]
    dimensions: list[InterviewDimensionContext]
    evaluation: InterviewEvaluationRecord | None
