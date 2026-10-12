"""Singleton DB row coordinating a single autonomous-cycle run (E5-R15)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.database import Base


class CycleRunControl(Base):
    """Exactly one row (id=1). Status is IDLE, RUNNING, or CANCELLING."""

    __tablename__ = "cycle_run_control"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="IDLE")
    run_token: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    max_applications: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discovery_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
