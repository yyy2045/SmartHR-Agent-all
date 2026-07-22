from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_jobs_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    original_jd: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    criteria_versions: Mapped[list[JobCriteriaVersion]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobCriteriaVersion.version_number",
    )


class JobCriteriaVersion(Base):
    __tablename__ = "job_criteria_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "version_number", name="uq_job_criteria_version_number"),
        CheckConstraint("status IN ('draft', 'confirmed')", name="ck_job_criteria_status"),
        CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 100",
            name="ck_job_criteria_pass_threshold",
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
    pass_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_criteria_versions.id", ondelete="SET NULL")
    )
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    job: Mapped[Job] = relationship(back_populates="criteria_versions")
    hard_requirements: Mapped[list[HardRequirement]] = relationship(
        back_populates="criteria_version",
        cascade="all, delete-orphan",
        order_by="HardRequirement.sort_order",
    )
    scoring_dimensions: Mapped[list[ScoringDimension]] = relationship(
        back_populates="criteria_version",
        cascade="all, delete-orphan",
        order_by="ScoringDimension.sort_order",
    )


class HardRequirement(Base):
    __tablename__ = "hard_requirements"
    __table_args__ = (
        CheckConstraint(
            "requirement_type IN ('min_experience_years', 'min_education', "
            "'required_certification', 'language_level', 'other')",
            name="ck_hard_requirement_type",
        ),
        CheckConstraint(
            "NOT auto_reject OR requirement_type IN ('min_experience_years', "
            "'min_education', 'required_certification', 'language_level')",
            name="ck_hard_requirement_auto_reject_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    criteria_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_criteria_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_value: Mapped[str] = mapped_column(String(200), nullable=False)
    auto_reject: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    criteria_version: Mapped[JobCriteriaVersion] = relationship(
        back_populates="hard_requirements"
    )


class ScoringDimension(Base):
    __tablename__ = "scoring_dimensions"
    __table_args__ = (
        CheckConstraint(
            "weight_percent >= 0 AND weight_percent <= 100",
            name="ck_scoring_dimension_weight",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    criteria_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job_criteria_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    weight_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    criteria_version: Mapped[JobCriteriaVersion] = relationship(
        back_populates="scoring_dimensions"
    )
