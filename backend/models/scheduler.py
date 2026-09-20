from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class SchedulerConfig(Base):
    """
    Stores scheduler configuration and state for persistence across application restarts.
    """
    __tablename__ = "scheduler_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    max_instances: Mapped[int] = mapped_column(Integer, default=1)
    
    is_running: Mapped[bool] = mapped_column(Boolean, default=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
