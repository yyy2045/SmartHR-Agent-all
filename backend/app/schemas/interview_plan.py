import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

InterviewPlanStatus = Literal["draft", "confirmed"]
InterviewRoundType = Literal["phone", "technical", "business", "hr", "final", "other"]


class InterviewScoreAnchorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score_value: int = Field(ge=1, le=5)
    description: str = Field(min_length=1, max_length=1_000)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("评分锚点说明不能为空")
        return value


class InterviewScoreDimensionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2_000)
    weight_percent: int = Field(ge=0, le=100)
    sort_order: int = Field(default=0, ge=0, le=1_000)
    anchors: list[InterviewScoreAnchorInput] = Field(default_factory=list, max_length=5)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_anchor_scores(self) -> Self:
        scores = [item.score_value for item in self.anchors]
        if len(scores) != len(set(scores)):
            raise ValueError("同一评分维度的锚点分值不能重复")
        return self


class InterviewQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_text: str = Field(default="", max_length=5_000)
    evaluation_guide: str = Field(default="", max_length=5_000)
    sort_order: int = Field(default=0, ge=0, le=1_000)

    @field_validator("question_text")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        return value.strip()

    @field_validator("evaluation_guide")
    @classmethod
    def normalize_guide(cls, value: str) -> str:
        return value.strip()


class InterviewRoundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=100)
    round_type: InterviewRoundType
    duration_minutes: int = Field(default=60, ge=15, le=480)
    pass_threshold: int = Field(default=60, ge=0, le=100)
    focus: str = Field(default="", max_length=5_000)
    sort_order: int = Field(default=0, ge=0, le=1_000)
    questions: list[InterviewQuestionInput] = Field(default_factory=list, max_length=50)
    scoring_dimensions: list[InterviewScoreDimensionInput] = Field(
        default_factory=list,
        max_length=20,
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("focus")
    @classmethod
    def normalize_focus(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_round_items(self) -> Self:
        question_texts = [
            item.question_text.casefold() for item in self.questions if item.question_text
        ]
        if len(question_texts) != len(set(question_texts)):
            raise ValueError("同一轮次的面试问题不能重复")
        dimension_names = [
            item.name.casefold() for item in self.scoring_dimensions if item.name
        ]
        if len(dimension_names) != len(set(dimension_names)):
            raise ValueError("同一轮次的评分维度名称不能重复")
        return self


class InterviewPlanVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version_id: uuid.UUID | None = None


class InterviewPlanDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rounds: list[InterviewRoundInput] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_rounds(self) -> Self:
        names = [item.name.casefold() for item in self.rounds if item.name]
        if len(names) != len(set(names)):
            raise ValueError("面试轮次名称不能重复")
        sort_orders = [item.sort_order for item in self.rounds]
        if len(sort_orders) != len(set(sort_orders)):
            raise ValueError("面试轮次顺序不能重复")
        return self


class InterviewScoreAnchorResponse(InterviewScoreAnchorInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class InterviewScoreDimensionResponse(InterviewScoreDimensionInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    anchors: list[InterviewScoreAnchorResponse]


class InterviewQuestionResponse(InterviewQuestionInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID


class InterviewRoundResponse(InterviewRoundInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    questions: list[InterviewQuestionResponse]
    scoring_dimensions: list[InterviewScoreDimensionResponse]


class InterviewPlanVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    version_number: int
    status: InterviewPlanStatus
    source_version_id: uuid.UUID | None
    confirmed_by_id: uuid.UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    rounds: list[InterviewRoundResponse]
