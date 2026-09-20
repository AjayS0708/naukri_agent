from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SchedulerStatusResponse(BaseModel):
    """Response model for scheduler status."""
    is_running: bool
    is_paused: bool
    enabled: bool
    interval_minutes: int
    max_instances: int
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None


class SchedulerConfigRequest(BaseModel):
    """Request model for updating scheduler configuration."""
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(None, ge=1, description="Interval in minutes (minimum 1)")


class SchedulerConfigResponse(BaseModel):
    """Response model for scheduler configuration."""
    enabled: bool
    interval_minutes: int
    max_instances: int
    is_running: bool
    is_paused: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None


class SchedulerActionResponse(BaseModel):
    """Response model for scheduler control actions."""
    success: bool
    message: str
    status: SchedulerStatusResponse
