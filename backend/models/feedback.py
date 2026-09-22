from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobFeedback(Base):
    """Stores explicit user feedback on jobs for learning."""
    __tablename__ = "job_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    
    feedback_type: Mapped[str] = mapped_column(String(32), index=True)
    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class DecisionQualityRecord(Base):
    """Stores decision quality assessments for analytics and learning."""
    __tablename__ = "decision_quality_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    
    priority: Mapped[str] = mapped_column(String(32), index=True)
    decision_score: Mapped[int] = mapped_column(Integer)
    
    # Signal scores (stored as integers 0-100 for database efficiency)
    role_relevance_score: Mapped[int] = mapped_column(Integer)
    skill_relevance_score: Mapped[int] = mapped_column(Integer)
    experience_compatibility_score: Mapped[int] = mapped_column(Integer)
    location_match_score: Mapped[int] = mapped_column(Integer)
    salary_suitability_score: Mapped[int] = mapped_column(Integer)
    job_quality_score: Mapped[int] = mapped_column(Integer)
    freshness_score: Mapped[int] = mapped_column(Integer)
    
    # Risk factors
    duplicate_probability: Mapped[int] = mapped_column(Integer)  # 0-100
    suspicious_probability: Mapped[int] = mapped_column(Integer)  # 0-100
    
    # Historical feedback influence
    feedback_adjustment: Mapped[int] = mapped_column(Integer, default=0)  # -100 to 100
    
    # Decision breakdown
    primary_reason_code: Mapped[str] = mapped_column(String(64), index=True)
    reason_codes: Mapped[str] = mapped_column(String(512))  # JSON array as string
    explanation: Mapped[str] = mapped_column(String(512))
    
    # Metadata
    hard_filter_failed: Mapped[bool] = mapped_column(Integer, default=False)
    requires_ai_analysis: Mapped[bool] = mapped_column(Integer, default=False)
    ai_available: Mapped[bool] = mapped_column(Integer, default=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
