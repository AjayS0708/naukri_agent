"""
Autonomous Cycle API Schemas - CHECKPOINT E3

Schemas for the autonomous cycle control API.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AutonomousCycleStartRequest(BaseModel):
    """Request to start an autonomous cycle."""
    model_config = ConfigDict(extra="forbid")

    max_applications: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum number of real applications to perform (1-10)"
    )

    @field_validator("max_applications")
    @classmethod
    def validate_max_applications(cls, v: int) -> int:
        """Validate max_applications is within safe bounds."""
        if v < 1:
            raise ValueError("max_applications must be at least 1")
        if v > 10:
            raise ValueError("max_applications cannot exceed 10")
        return v


class AutonomousCycleStartResponse(BaseModel):
    """Response when starting an autonomous cycle."""
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[int] = None
    status: str
    max_applications: int
    message: str


class AutonomousCycleStatusResponse(BaseModel):
    """Response for autonomous cycle status."""
    model_config = ConfigDict(extra="forbid")

    active_state: str  # IDLE or RUNNING; never a historical terminal result
    lock_held: bool
    active_run: Optional["AutonomousCycleRunResponse"] = None
    last_run: Optional["AutonomousCycleRunResponse"] = None


class AutonomousCycleRunResponse(BaseModel):
    """Safe summary of either an active or completed autonomous cycle."""
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[int] = None
    status: str
    max_applications: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stats: dict = Field(default_factory=dict)
    error: Optional[str] = None
