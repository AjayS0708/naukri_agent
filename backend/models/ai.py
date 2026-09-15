from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AIUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)  # SUCCESS, FAIL, QUOTA_EXHAUSTED
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class JobAnalysisModel(Base):
    __tablename__ = "job_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    match_score: Mapped[int] = mapped_column(Integer)
    role_match: Mapped[bool] = mapped_column(Boolean)
    skill_match: Mapped[bool] = mapped_column(Boolean)
    experience_match: Mapped[bool] = mapped_column(Boolean)
    location_match: Mapped[bool] = mapped_column(Boolean)
    salary_match: Mapped[bool] = mapped_column(Boolean)
    job_quality: Mapped[str] = mapped_column(String(32))
    duplicate_probability: Mapped[float] = mapped_column(Float)
    suspicious: Mapped[bool] = mapped_column(Boolean)
    recommendation: Mapped[str] = mapped_column(String(32))
    short_reason: Mapped[str] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
