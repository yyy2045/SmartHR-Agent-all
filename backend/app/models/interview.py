from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.candidate import JobApplication
    from app.models.job import Job
    from app.models.resume import ResumeDocument
    from app.models.user import User


class InterviewPlanVersion(Base):
    __tablename__ = "interview_plan_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "version_number", name="uq_interview_plan_version_number"),
        CheckConstraint(
            "status IN ('draft', 'confirmed')",
            name="ck_interview_plan_versions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interview_plan_versions.id", ondelete="SET NULL")
    )
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    job: Mapped[Job] = relationship(back_populates="interview_plan_versions")
    rounds: Mapped[list[InterviewRound]] = relationship(
        back_populates="plan_version",
        cascade="all, delete-orphan",
        order_by="InterviewRound.sort_order",
    )
    candidate_schedules: Mapped[list[CandidateInterviewSchedule]] = relationship(
        back_populates="plan_version",
    )


class InterviewRound(Base):
    __tablename__ = "interview_rounds"
    __table_args__ = (
        UniqueConstraint("plan_version_id", "sort_order", name="uq_interview_round_sort_order"),
        CheckConstraint(
            "round_type IN ('phone', 'technical', 'business', 'hr', 'final', 'other')",
            name="ck_interview_rounds_type",
        ),
        CheckConstraint(
            "duration_minutes >= 15 AND duration_minutes <= 480",
            name="ck_interview_rounds_duration",
        ),
        CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 100",
            name="ck_interview_rounds_pass_threshold",
        ),
        CheckConstraint("sort_order >= 0", name="ck_interview_rounds_sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plan_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_plan_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    round_type: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    pass_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    focus: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    plan_version: Mapped[InterviewPlanVersion] = relationship(back_populates="rounds")
    questions: Mapped[list[InterviewQuestion]] = relationship(
        back_populates="round",
        cascade="all, delete-orphan",
        order_by="InterviewQuestion.sort_order",
    )
    scoring_dimensions: Mapped[list[InterviewScoreDimension]] = relationship(
        back_populates="round",
        cascade="all, delete-orphan",
        order_by="InterviewScoreDimension.sort_order",
    )
    scheduled_rounds: Mapped[list[CandidateInterviewRound]] = relationship(
        back_populates="plan_round",
    )


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"
    __table_args__ = (
        UniqueConstraint("round_id", "sort_order", name="uq_interview_question_sort_order"),
        CheckConstraint("sort_order >= 0", name="ck_interview_questions_sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_rounds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    evaluation_guide: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    round: Mapped[InterviewRound] = relationship(back_populates="questions")
    evaluation_responses: Mapped[list[InterviewQuestionResponse]] = relationship(
        back_populates="question"
    )


class InterviewScoreDimension(Base):
    __tablename__ = "interview_score_dimensions"
    __table_args__ = (
        UniqueConstraint(
            "round_id",
            "sort_order",
            name="uq_interview_score_dimension_sort_order",
        ),
        CheckConstraint(
            "weight_percent >= 0 AND weight_percent <= 100",
            name="ck_interview_score_dimensions_weight",
        ),
        CheckConstraint("sort_order >= 0", name="ck_interview_score_dimensions_sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_rounds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    weight_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    round: Mapped[InterviewRound] = relationship(back_populates="scoring_dimensions")
    anchors: Mapped[list[InterviewScoreAnchor]] = relationship(
        back_populates="dimension",
        cascade="all, delete-orphan",
        order_by="InterviewScoreAnchor.score_value",
    )
    evaluation_ratings: Mapped[list[InterviewDimensionRating]] = relationship(
        back_populates="dimension"
    )


class InterviewScoreAnchor(Base):
    __tablename__ = "interview_score_anchors"
    __table_args__ = (
        UniqueConstraint("dimension_id", "score_value", name="uq_interview_score_anchor_value"),
        CheckConstraint(
            "score_value >= 1 AND score_value <= 5",
            name="ck_interview_score_anchors_value",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dimension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_score_dimensions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score_value: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    dimension: Mapped[InterviewScoreDimension] = relationship(back_populates="anchors")


class CandidateInterviewSchedule(Base):
    __tablename__ = "candidate_interview_schedules"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            name="uq_candidate_interview_schedule_application",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'partially_cancelled', 'cancelled')",
            name="ck_candidate_interview_schedules_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_plan_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="scheduled", index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    application: Mapped[JobApplication] = relationship(back_populates="interview_schedule")
    plan_version: Mapped[InterviewPlanVersion] = relationship(
        back_populates="candidate_schedules"
    )
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    rounds: Mapped[list[CandidateInterviewRound]] = relationship(
        back_populates="schedule",
        cascade="all, delete-orphan",
        order_by="CandidateInterviewRound.sort_order",
    )

    @property
    def candidate_code(self) -> str:
        return self.application.candidate.candidate_code

    @property
    def document_id(self) -> uuid.UUID:
        return self.document.id

    @property
    def document(self) -> ResumeDocument:
        if self.application.primary_document is not None:
            return self.application.primary_document
        linked_documents = [link.document for link in self.application.document_links]
        documents = linked_documents or self.application.documents
        if not documents:
            raise RuntimeError("候选人面试安排缺少关联简历")
        return max(documents, key=lambda item: item.created_at)

    @property
    def plan_version_number(self) -> int:
        return self.plan_version.version_number


class CandidateInterviewRound(Base):
    __tablename__ = "candidate_interview_rounds"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id", "plan_round_id", name="uq_candidate_interview_round_plan_round"
        ),
        UniqueConstraint(
            "schedule_id", "sort_order", name="uq_candidate_interview_round_sort_order"
        ),
        CheckConstraint(
            "interview_method IN ('onsite', 'online', 'phone')",
            name="ck_candidate_interview_rounds_method",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'rescheduled', 'cancelled')",
            name="ck_candidate_interview_rounds_status",
        ),
        CheckConstraint("sort_order >= 0", name="ck_candidate_interview_rounds_sort_order"),
        CheckConstraint(
            "reschedule_count >= 0", name="ck_candidate_interview_rounds_reschedule_count"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_interview_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_round_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_rounds.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interview_method: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500))
    meeting_url: Mapped[str | None] = mapped_column(String(2_000))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled", index=True
    )
    reschedule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_change_reason: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    schedule: Mapped[CandidateInterviewSchedule] = relationship(back_populates="rounds")
    plan_round: Mapped[InterviewRound] = relationship(back_populates="scheduled_rounds")
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])
    evaluation: Mapped[InterviewEvaluation | None] = relationship(
        back_populates="candidate_round",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def name(self) -> str:
        return self.plan_round.name

    @property
    def round_type(self) -> str:
        return self.plan_round.round_type

    @property
    def duration_minutes(self) -> int:
        return self.plan_round.duration_minutes


class InterviewEvaluation(Base):
    __tablename__ = "interview_evaluations"
    __table_args__ = (
        UniqueConstraint("candidate_round_id", name="uq_interview_evaluation_round"),
        CheckConstraint(
            "status IN ('draft', 'submitted')",
            name="ck_interview_evaluations_status",
        ),
        CheckConstraint(
            "overall_recommendation IS NULL OR "
            "overall_recommendation IN "
            "('strongly_recommend', 'recommend', 'reserve', 'not_recommend')",
            name="ck_interview_evaluations_recommendation",
        ),
        CheckConstraint(
            "total_score IS NULL OR (total_score >= 0 AND total_score <= 100)",
            name="ck_interview_evaluations_total_score",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_round_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_interview_rounds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    overall_recommendation: Mapped[str | None] = mapped_column(String(30))
    overall_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    total_score: Mapped[float | None] = mapped_column(Numeric(5, 2))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    candidate_round: Mapped[CandidateInterviewRound] = relationship(
        back_populates="evaluation"
    )
    submitted_by: Mapped[User | None] = relationship(foreign_keys=[submitted_by_id])
    question_responses: Mapped[list[InterviewQuestionResponse]] = relationship(
        back_populates="evaluation",
        cascade="all, delete-orphan",
    )
    dimension_ratings: Mapped[list[InterviewDimensionRating]] = relationship(
        back_populates="evaluation",
        cascade="all, delete-orphan",
    )


class InterviewQuestionResponse(Base):
    __tablename__ = "interview_question_responses"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id", "question_id", name="uq_interview_question_response"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_evaluations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    answer_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")

    evaluation: Mapped[InterviewEvaluation] = relationship(
        back_populates="question_responses"
    )
    question: Mapped[InterviewQuestion] = relationship(
        back_populates="evaluation_responses"
    )


class InterviewDimensionRating(Base):
    __tablename__ = "interview_dimension_ratings"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id", "dimension_id", name="uq_interview_dimension_rating"
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 1 AND score <= 5)",
            name="ck_interview_dimension_ratings_score",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_evaluations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dimension_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_score_dimensions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    score: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")

    evaluation: Mapped[InterviewEvaluation] = relationship(
        back_populates="dimension_ratings"
    )
    dimension: Mapped[InterviewScoreDimension] = relationship(
        back_populates="evaluation_ratings"
    )
