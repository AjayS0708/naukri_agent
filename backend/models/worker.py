from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base
from backend.schemas.worker import WorkerType, WorkerStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class Worker(Base):
    """
    Persistent worker identity and registration.
    
    Tracks worker lifecycle across LOCAL_WINDOWS and future CLOUD_BROWSER
    deployment types without changing current Naukri execution architecture.
    """
    __tablename__ = "workers"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    worker_type: Mapped[WorkerType] = mapped_column(
        Enum(WorkerType),
        default=WorkerType.LOCAL_WINDOWS
    )
    status: Mapped[WorkerStatus] = mapped_column(
        Enum(WorkerStatus),
        default=WorkerStatus.STARTING
    )
    runtime_environment: Mapped[str] = mapped_column(String(255), default="local_windows")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
