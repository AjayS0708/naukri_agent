"""
Autonomous Cycle API Schemas - CHECKPOINT E3

Schemas for the autonomous cycle control API.
E5-R10: no application-count cap is enforced; max_applications is accepted
for backward compatibility but ignored at runtime.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AutonomousCycleStartRequest(BaseModel):
    """Request to start an autonomous cycle."""
    model_config = ConfigDict(extra="forbid")

    # Deprecated/ignored (E5-R10): kept so older clients do not break.
    # The run processes every eligible matching job; no count cap applies.
    max_applications: Optional[int] = Field(
        default=None,
        description="Ignored (E5-R10). Runs process all eligible matching jobs."
    )


class AutonomousCycleStartResponse(BaseModel):
    """Response when starting an autonomous cycle."""
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[int] = None
    status: str
    max_applications: Optional[int] = None
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
