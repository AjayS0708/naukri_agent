from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobPreference(Base):
    __tablename__ = "job_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Allows a 1:1 mapped preference per profile, but decoupled so we can have preferences independent of a profile
    locations: Mapped[dict] = mapped_column(JSON, default=list) # Stored as a list of strings
    job_titles: Mapped[dict] = mapped_column(JSON, default=list) # Stored as a list of strings
    employment_types: Mapped[dict] = mapped_column(JSON, default=list) # list of strings
    
    min_salary_lpa: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)
    aggressiveness: Mapped[str] = mapped_column(String(32), default="BALANCED") 
    
    max_daily_applications: Mapped[int] = mapped_column(Integer, default=20)
    max_hourly_applications: Mapped[int] = mapped_column(Integer, default=4)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MatchResult(Base):
    """
    Stores the final verdict across all matching rules (deterministic + AI).
    """
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    preference_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_preferences.id"), nullable=True)
    
    decision: Mapped[str] = mapped_column(String(32), index=True) # APPLY, SKIP, NEEDS_ATTENTION
    skip_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    
    # Store JSON arrays for rules
    matched_rules: Mapped[dict] = mapped_column(JSON, default=list)
    failed_rules: Mapped[dict] = mapped_column(JSON, default=list)
    warnings: Mapped[dict] = mapped_column(JSON, default=list)
    
    match_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True) # 0-100 if evaluated by AI
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
