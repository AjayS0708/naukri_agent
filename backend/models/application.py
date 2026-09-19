from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Application(Base):
    """
    Stores application attempts and results per PRD.
    """
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    
    # Application status following PRD lifecycle
    status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", index=True)
    
    # Application method: NAUKRI_NATIVE, EXTERNAL
    application_method: Mapped[str] = mapped_column(String(32), nullable=True)
    
    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Failure/skip reasons
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    
    # External application tracking
    external_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    
    # Additional metadata
    needs_attention: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ApplicationAnswer(Base):
    """
    Stores application questions and answers.
    """
    __tablename__ = "application_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    
    # Answer type: FACTUAL, GENERATED, FALLBACK, NEEDS_ATTENTION
    answer_type: Mapped[str] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float] = mapped_column(Integer, nullable=True)  # 0-100
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
