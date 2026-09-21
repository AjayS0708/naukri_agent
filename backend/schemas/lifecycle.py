from typing import Optional, Dict, Any
from pydantic import BaseModel


class LifecycleStatusResponse(BaseModel):
    """Response for lifecycle status endpoint."""
    agent_state: str
    scheduler: Optional[Dict[str, Any]] = None
    ai_queue: Optional[Dict[str, Any]] = None
    prerequisites: Dict[str, Any]


class LifecycleActionResponse(BaseModel):
    """Response for lifecycle action endpoints (start, stop, pause, resume)."""
    success: bool
    state: Optional[str] = None
    message: Optional[str] = None
    reason: Optional[str] = None
    current_state: Optional[str] = None
    prerequisites: Optional[Dict[str, Any]] = None


class RecoveryStatsResponse(BaseModel):
    """Response for startup recovery statistics."""
    stale_queue_items_recovered: int
    scheduler_config_restored: bool
    agent_state_restored: str


class RecoveryResponse(BaseModel):
    """Response for startup recovery endpoint."""
    success: bool
    reason: Optional[str] = None
    recovery_stats: RecoveryStatsResponse
