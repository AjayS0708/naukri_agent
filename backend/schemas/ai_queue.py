from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AIQueueStatus(StrEnum):
    """Status of an AI queue item."""
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    RETRY_PENDING = "RETRY_PENDING"
    QUOTA_BLOCKED = "QUOTA_BLOCKED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    FAILED = "FAILED"


class AIQueueItemCreate(BaseModel):
    """Request to enqueue a job for AI analysis."""
    model_config = ConfigDict(extra="forbid")
    job_id: int = Field(ge=1)
    priority: int = Field(default=0, ge=0, le=100)
    priority_reason: str | None = Field(default=None, max_length=255)
    queue_source: str = Field(default="MANUAL", max_length=64)


class AIQueueItemUpdate(BaseModel):
    """Request to update an AI queue item."""
    model_config = ConfigDict(extra="forbid")
    status: AIQueueStatus | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    failure_reason: str | None = Field(default=None, max_length=512)
    last_error: str | None = None


class AIQueueItemResponse(BaseModel):
    """Response with AI queue item details."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    status: AIQueueStatus
    priority: int
    priority_reason: str | None
    attempt_count: int
    max_attempts: int
    last_attempt_at: datetime | None
    next_retry_at: datetime | None
    failure_reason: str | None
    last_error: str | None
    analysis_id: int | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    queue_source: str | None
    processing_started_at: datetime | None


class AIQueueStatusResponse(BaseModel):
    """Response with queue status and counts."""
    total_queued: int
    total_processing: int
    total_completed: int
    total_retry_pending: int
    total_quota_blocked: int
    total_needs_attention: int
    total_failed: int
    total_items: int
    next_item_id: int | None


class AIQueueProcessingResult(BaseModel):
    """Result of processing a queue item."""
    model_config = ConfigDict(extra="forbid")
    success: bool
    status: AIQueueStatus
    failure_reason: str | None = None
    last_error: str | None = None
    analysis_id: int | None = None
