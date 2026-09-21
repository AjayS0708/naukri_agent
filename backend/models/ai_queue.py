from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AIQueueItem(Base):
    """
    Persistent AI work queue for jobs requiring Gemini analysis.
    
    The queue allows discovery to continue collecting/filtering jobs without
    immediately performing uncontrolled Gemini calls. Jobs are enqueued and
    processed sequentially with proper quota handling and retry logic.
    """
    __tablename__ = "ai_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    
    # Queue status
    status: Mapped[str] = mapped_column(
        String(32),
        default="QUEUED",
        index=True,
        nullable=False
    )  # QUEUED, PROCESSING, COMPLETED, RETRY_PENDING, QUOTA_BLOCKED, NEEDS_ATTENTION, FAILED
    
    # Priority handling (deterministic only)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)  # Higher = higher priority
    priority_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Retry handling
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Failure tracking
    failure_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # AI analysis result (when completed)
    analysis_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_analyses.id"), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    queue_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # SCHEDULER, MANUAL, etc.
    processing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
