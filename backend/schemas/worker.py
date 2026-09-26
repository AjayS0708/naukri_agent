from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WorkerType(StrEnum):
    """Worker deployment type."""
    LOCAL_WINDOWS = "LOCAL_WINDOWS"
    CLOUD_BROWSER = "CLOUD_BROWSER"


class WorkerStatus(StrEnum):
    """Worker lifecycle status."""
    STARTING = "STARTING"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class WorkerRegisterRequest(BaseModel):
    """Request to register a new worker."""
    model_config = ConfigDict(extra="forbid")
    
    worker_type: WorkerType
    runtime_environment: str = Field(default="local_windows", description="Runtime environment identifier")


class WorkerStatusResponse(BaseModel):
    """Response with worker status."""
    model_config = ConfigDict(extra="forbid")
    
    worker_id: str
    worker_type: WorkerType
    status: WorkerStatus
    runtime_environment: str
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkerListResponse(BaseModel):
    """Response with list of workers."""
    model_config = ConfigDict(extra="forbid")
    
    workers: list[WorkerStatusResponse]
    total_count: int
    active_count: int
