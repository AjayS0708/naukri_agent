from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Job(Base):
    """
    Core job entity as per PRD. Added in Phase 3 just enough to support JobAnalysis foreign key.
    More fields will be mapped in Phase 5.
    """
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    external_job_id: Mapped[str] = mapped_column(String(128), index=True, unique=True)
    url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(255))
    company: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # Phase 5 discovery fields
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    salary: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    salary_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    salary_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    experience: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    experience_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    experience_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role_category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # E5-R9: classified during discovery enrichment (same open page as
    # description fetch). Values: NAUKRI_NATIVE, EXTERNAL, AMBIGUOUS, or
    # NULL when never classified. Ranking treats unknown as ambiguous.
    application_mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # E5-R25: stamp of the most recent live-page application-mode
    # re-verification for a job whose stored mode is AMBIGUOUS/NULL. The
    # existing-job recovery stage uses it as a cooldown so a still-ambiguous
    # posting is not re-visited on every run.
    mode_reverified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True) # search term

    # Simple states according to PRD
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
