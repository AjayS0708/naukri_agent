from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.database import get_session
from backend.schemas.ai_queue import (
    AIQueueItemCreate, AIQueueItemUpdate, AIQueueItemResponse,
    AIQueueStatusResponse
)
from backend.services.gemini.queue import AIQueueService

router = APIRouter(prefix="/api/ai-queue", tags=["ai-queue"])


@router.get("/status", response_model=AIQueueStatusResponse)
def get_queue_status(db: Session = Depends(get_session)):
    """
    Get current AI queue status and counts.
    
    Returns counts of items in each queue state and the next item to process.
    """
    queue_service = AIQueueService(db)
    return queue_service.get_queue_status()


@router.post("/enqueue", response_model=AIQueueItemResponse)
def enqueue_job(request: AIQueueItemCreate, db: Session = Depends(get_session)):
    """
    Enqueue a job for AI analysis.
    
    Prevents duplicate queue entries for the same job.
    Returns existing item if job already in queue.
    """
    queue_service = AIQueueService(db)
    result = queue_service.enqueue_job(
        job_id=request.job_id,
        priority=request.priority,
        priority_reason=request.priority_reason,
        queue_source=request.queue_source
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return result


@router.get("/next", response_model=Optional[AIQueueItemResponse])
def get_next_item(db: Session = Depends(get_session)):
    """
    Get the next eligible queued item for processing.
    
    Returns None if no eligible items.
    """
    queue_service = AIQueueService(db)
    return queue_service.get_next_item()


@router.get("/items", response_model=list[AIQueueItemResponse])
def get_queue_items(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_session)
):
    """
    Get AI queue items with optional filtering.
    
    Query parameters:
    - status: Filter by queue status (QUEUED, PROCESSING, COMPLETED, etc.)
    - limit: Maximum number of items to return (default: 100)
    - offset: Number of items to skip (default: 0)
    """
    from sqlalchemy import select
    from backend.models.ai_queue import AIQueueItem
    
    query = select(AIQueueItem)
    
    if status:
        query = query.where(AIQueueItem.status == status)
    
    query = query.order_by(AIQueueItem.created_at.desc()).limit(limit).offset(offset)
    
    items = db.execute(query).scalars().all()
    
    queue_service = AIQueueService(db)
    return [queue_service._to_response(item) for item in items]


@router.post("/{item_id}/process")
def process_item(item_id: int, profile_context: str, db: Session = Depends(get_session)):
    """
    Process a queue item through Gemini analysis.
    
    This method:
    1. Marks item as PROCESSING
    2. Calls Gemini for job analysis
    3. Validates Pydantic schema
    4. Stores analysis result
    5. Marks item as COMPLETED or handles errors
    
    Returns processing result with status and any error information.
    """
    queue_service = AIQueueService(db)
    result = queue_service.process_item(item_id, profile_context)
    return result


@router.post("/{item_id}/mark-processing", response_model=AIQueueItemResponse)
def mark_processing(item_id: int, db: Session = Depends(get_session)):
    """Mark a queue item as PROCESSING."""
    queue_service = AIQueueService(db)
    result = queue_service.mark_processing(item_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Queue item not found or invalid state")
    
    return result


@router.post("/{item_id}/mark-completed", response_model=AIQueueItemResponse)
def mark_completed(item_id: int, analysis_id: Optional[int] = None, db: Session = Depends(get_session)):
    """Mark a queue item as COMPLETED with optional analysis result."""
    queue_service = AIQueueService(db)
    result = queue_service.mark_completed(item_id, analysis_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Queue item not found")
    
    return result


@router.post("/{item_id}/mark-retry-pending", response_model=AIQueueItemResponse)
def mark_retry_pending(item_id: int, failure_reason: str, last_error: str, db: Session = Depends(get_session)):
    """
    Mark a queue item as RETRY_PENDING with scheduled retry time.
    
    Returns None if max attempts exceeded.
    """
    queue_service = AIQueueService(db)
    result = queue_service.mark_retry_pending(item_id, failure_reason, last_error)
    
    if not result:
        raise HTTPException(status_code=400, detail="Max retry attempts exceeded")
    
    return result


@router.post("/{item_id}/mark-quota-blocked", response_model=AIQueueItemResponse)
def mark_quota_blocked(item_id: int, reason: str = "Gemini quota exhausted", db: Session = Depends(get_session)):
    """Mark a queue item as QUOTA_BLOCKED."""
    queue_service = AIQueueService(db)
    result = queue_service.mark_quota_blocked(item_id, reason)
    
    if not result:
        raise HTTPException(status_code=404, detail="Queue item not found")
    
    return result


@router.post("/{item_id}/mark-needs-attention", response_model=AIQueueItemResponse)
def mark_needs_attention(item_id: int, failure_reason: str, last_error: str, db: Session = Depends(get_session)):
    """Mark a queue item as NEEDS_ATTENTION."""
    queue_service = AIQueueService(db)
    result = queue_service.mark_needs_attention(item_id, failure_reason, last_error)
    
    if not result:
        raise HTTPException(status_code=404, detail="Queue item not found")
    
    return result


@router.post("/{item_id}/mark-failed", response_model=AIQueueItemResponse)
def mark_failed(item_id: int, failure_reason: str, last_error: str, db: Session = Depends(get_session)):
    """Mark a queue item as FAILED (permanent/non-retryable error)."""
    queue_service = AIQueueService(db)
    result = queue_service.mark_failed(item_id, failure_reason, last_error)
    
    if not result:
        raise HTTPException(status_code=404, detail="Queue item not found")
    
    return result


@router.post("/recover-stale")
def recover_stale_items(db: Session = Depends(get_session)):
    """
    Recover items stuck in PROCESSING state.
    
    Items that have been in PROCESSING state longer than the threshold
    are returned to QUEUED or RETRY_PENDING state.
    
    Returns the number of items recovered.
    """
    queue_service = AIQueueService(db)
    recovered_count = queue_service.recover_stale_items()
    return {"recovered_count": recovered_count}
