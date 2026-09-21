from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session

from backend.models.ai_queue import AIQueueItem, utc_now
from backend.models.job import Job
from backend.models.ai import JobAnalysisModel
from backend.schemas.ai_queue import (
    AIQueueStatus, AIQueueItemCreate, AIQueueItemUpdate,
    AIQueueItemResponse, AIQueueStatusResponse, AIQueueProcessingResult
)
from backend.services.gemini.provider import GeminiProvider, APIQuotaExhaustedError
from backend.schemas.ai import JobAnalysis
from backend.core.logging import get_logger

logger = get_logger(__name__)


class AIQueueService:
    """
    Service for managing AI work queue for jobs requiring Gemini analysis.
    
    The queue allows discovery to continue collecting/filtering jobs without
    immediately performing uncontrolled Gemini calls. Jobs are enqueued and
    processed sequentially with proper quota handling and retry logic.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.gemini_provider = None  # Will be initialized when needed
        
        # Retry configuration
        self.max_retry_attempts = 3
        self.retry_delays = [60, 300, 900]  # 1min, 5min, 15min in seconds
        self.stale_processing_threshold = timedelta(minutes=30)  # Items stuck in PROCESSING for 30min are stale
    
    def enqueue_job(
        self,
        job_id: int,
        priority: int = 0,
        priority_reason: Optional[str] = None,
        queue_source: str = "MANUAL"
    ) -> Optional[AIQueueItemResponse]:
        """
        Enqueue a job for AI analysis.
        
        Prevents duplicate queue entries for the same job.
        Returns None if job already exists in queue.
        """
        # Check for existing queue item
        existing = self.session.execute(
            select(AIQueueItem).where(AIQueueItem.job_id == job_id)
        ).scalars().first()
        
        if existing:
            logger.info(f"Job {job_id} already in queue with status {existing.status}")
            return self._to_response(existing)
        
        # Verify job exists
        job = self.session.get(Job, job_id)
        if not job:
            logger.error(f"Job {job_id} not found, cannot enqueue")
            return None
        
        # Calculate deterministic priority if not provided
        if priority == 0:
            priority = self._calculate_priority(job, priority_reason)
        
        # Create queue item
        queue_item = AIQueueItem(
            job_id=job_id,
            status=AIQueueStatus.QUEUED.value,
            priority=priority,
            priority_reason=priority_reason,
            queue_source=queue_source,
            max_attempts=self.max_retry_attempts
        )
        
        self.session.add(queue_item)
        self.session.commit()
        self.session.refresh(queue_item)
        
        logger.info(f"Job {job_id} enqueued with priority {priority}")
        return self._to_response(queue_item)
    
    def get_next_item(self) -> Optional[AIQueueItemResponse]:
        """
        Get the next eligible queued item for processing.
        
        Priority order:
        1. Highest priority QUEUED items
        2. RETRY_PENDING items where next_retry_at <= now
        3. QUOTA_BLOCKED items (when quota becomes available)
        
        Returns None if no eligible items.
        """
        now = utc_now()
        
        # First check for retry items that are ready
        retry_ready = self.session.execute(
            select(AIQueueItem).where(
                and_(
                    AIQueueItem.status == AIQueueStatus.RETRY_PENDING.value,
                    AIQueueItem.next_retry_at <= now
                )
            ).order_by(AIQueueItem.priority.desc(), AIQueueItem.created_at.asc())
        ).scalars().first()
        
        if retry_ready:
            logger.info(f"Found retry-ready item {retry_ready.id}")
            return self._to_response(retry_ready)
        
        # Then check for queued items
        queued = self.session.execute(
            select(AIQueueItem).where(
                AIQueueItem.status == AIQueueStatus.QUEUED.value
            ).order_by(AIQueueItem.priority.desc(), AIQueueItem.created_at.asc())
        ).scalars().first()
        
        if queued:
            logger.info(f"Found queued item {queued.id}")
            return self._to_response(queued)
        
        # Finally check quota-blocked items (when quota might be available)
        quota_blocked = self.session.execute(
            select(AIQueueItem).where(
                AIQueueItem.status == AIQueueStatus.QUOTA_BLOCKED.value
            ).order_by(AIQueueItem.priority.desc(), AIQueueItem.created_at.asc())
        ).scalars().first()
        
        if quota_blocked:
            logger.info(f"Found quota-blocked item {quota_blocked.id}")
            return self._to_response(quota_blocked)
        
        return None
    
    def mark_processing(self, queue_item_id: int) -> Optional[AIQueueItemResponse]:
        """Mark a queue item as PROCESSING."""
        item = self.session.get(AIQueueItem, queue_item_id)
        if not item:
            logger.error(f"Queue item {queue_item_id} not found")
            return None
        
        if item.status not in [AIQueueStatus.QUEUED.value, AIQueueStatus.RETRY_PENDING.value, AIQueueStatus.QUOTA_BLOCKED.value]:
            logger.warning(f"Cannot mark item {queue_item_id} as PROCESSING - current status {item.status}")
            return None
        
        item.status = AIQueueStatus.PROCESSING.value
        item.processing_started_at = utc_now()
        item.attempt_count += 1
        item.last_attempt_at = utc_now()
        
        self.session.commit()
        self.session.refresh(item)
        
        logger.info(f"Queue item {queue_item_id} marked as PROCESSING (attempt {item.attempt_count})")
        return self._to_response(item)
    
    def mark_completed(self, queue_item_id: int, analysis_id: Optional[int] = None) -> Optional[AIQueueItemResponse]:
        """Mark a queue item as COMPLETED with optional analysis result."""
        item = self.session.get(AIQueueItem, queue_item_id)
        if not item:
            logger.error(f"Queue item {queue_item_id} not found")
            return None
        
        item.status = AIQueueStatus.COMPLETED.value
        item.completed_at = utc_now()
        item.analysis_id = analysis_id
        
        self.session.commit()
        self.session.refresh(item)
        
        logger.info(f"Queue item {queue_item_id} marked as COMPLETED")
        return self._to_response(item)
    
    def mark_retry_pending(self, queue_item_id: int, failure_reason: str, last_error: str) -> Optional[AIQueueItemResponse]:
        """
        Mark a queue item as RETRY_PENDING with scheduled retry time.
        
        Returns None if max attempts exceeded.
        """
        item = self.session.get(AIQueueItem, queue_item_id)
        if not item:
            logger.error(f"Queue item {queue_item_id} not found")
            return None
        
        if item.attempt_count >= item.max_attempts:
            logger.warning(f"Queue item {queue_item_id} exceeded max attempts ({item.max_attempts})")
            return self.mark_needs_attention(queue_item_id, f"Max retry attempts exceeded: {failure_reason}", last_error)
        
        # Calculate retry delay based on attempt count (attempt_count is 1-indexed)
        retry_delay_seconds = self.retry_delays[min(item.attempt_count - 1, len(self.retry_delays) - 1)]
        next_retry_at = utc_now() + timedelta(seconds=retry_delay_seconds)
        
        item.status = AIQueueStatus.RETRY_PENDING.value
        item.failure_reason = failure_reason
        item.last_error = last_error
        item.next_retry_at = next_retry_at
        
        self.session.commit()
        self.session.refresh(item)
        
        logger.info(f"Queue item {queue_item_id} marked as RETRY_PENDING, retry at {next_retry_at}")
        return self._to_response(item)
    
    def mark_quota_blocked(self, queue_item_id: int, reason: str = "Gemini quota exhausted") -> Optional[AIQueueItemResponse]:
        """Mark a queue item as QUOTA_BLOCKED."""
        item = self.session.get(AIQueueItem, queue_item_id)
        if not item:
            logger.error(f"Queue item {queue_item_id} not found")
            return None
        
        item.status = AIQueueStatus.QUOTA_BLOCKED.value
        item.failure_reason = reason
        item.last_error = reason
        
        self.session.commit()
        self.session.refresh(item)
        
        logger.info(f"Queue item {queue_item_id} marked as QUOTA_BLOCKED")
        return self._to_response(item)
    
    def mark_needs_attention(self, queue_item_id: int, failure_reason: str, last_error: str) -> Optional[AIQueueItemResponse]:
        """Mark a queue item as NEEDS_ATTENTION."""
        item = self.session.get(AIQueueItem, queue_item_id)
        if not item:
            logger.error(f"Queue item {queue_item_id} not found")
            return None
        
        item.status = AIQueueStatus.NEEDS_ATTENTION.value
        item.failure_reason = failure_reason
        item.last_error = last_error
        item.completed_at = utc_now()
        
        self.session.commit()
        self.session.refresh(item)
        
        logger.info(f"Queue item {queue_item_id} marked as NEEDS_ATTENTION")
        return self._to_response(item)
    
    def mark_failed(self, queue_item_id: int, failure_reason: str, last_error: str) -> Optional[AIQueueItemResponse]:
        """Mark a queue item as FAILED (permanent/non-retryable error)."""
        item = self.session.get(AIQueueItem, queue_item_id)
        if not item:
            logger.error(f"Queue item {queue_item_id} not found")
            return None
        
        item.status = AIQueueStatus.FAILED.value
        item.failure_reason = failure_reason
        item.last_error = last_error
        item.completed_at = utc_now()
        
        self.session.commit()
        self.session.refresh(item)
        
        logger.info(f"Queue item {queue_item_id} marked as FAILED")
        return self._to_response(item)
    
    def recover_stale_items(self) -> int:
        """
        Recover items stuck in PROCESSING state.
        
        Items that have been in PROCESSING state longer than the threshold
        are returned to QUEUED or RETRY_PENDING state.
        
        Returns the number of items recovered.
        """
        now = utc_now()
        stale_threshold = now - self.stale_processing_threshold
        
        stale_items = self.session.execute(
            select(AIQueueItem).where(
                and_(
                    AIQueueItem.status == AIQueueStatus.PROCESSING.value,
                    AIQueueItem.processing_started_at < stale_threshold
                )
            )
        ).scalars().all()
        
        recovered_count = 0
        for item in stale_items:
            if item.attempt_count < item.max_attempts:
                # Return to retry pending
                item.status = AIQueueStatus.RETRY_PENDING.value
                item.next_retry_at = now
                logger.info(f"Recovered stale item {item.id} to RETRY_PENDING")
            else:
                # Mark as needs attention
                item.status = AIQueueStatus.NEEDS_ATTENTION.value
                item.failure_reason = "Stale processing - max attempts exceeded"
                logger.info(f"Recovered stale item {item.id} to NEEDS_ATTENTION")
            
            recovered_count += 1
        
        if recovered_count > 0:
            self.session.commit()
            logger.info(f"Recovered {recovered_count} stale queue items")
        
        return recovered_count
    
    def get_queue_status(self) -> AIQueueStatusResponse:
        """Get current queue status and counts."""
        total_queued = self.session.execute(
            select(func.count(AIQueueItem.id)).where(AIQueueItem.status == AIQueueStatus.QUEUED.value)
        ).scalar()
        
        total_processing = self.session.execute(
            select(func.count(AIQueueItem.id)).where(AIQueueItem.status == AIQueueStatus.PROCESSING.value)
        ).scalar()
        
        total_completed = self.session.execute(
            select(func.count(AIQueueItem.id)).where(AIQueueItem.status == AIQueueStatus.COMPLETED.value)
        ).scalar()
        
        total_retry_pending = self.session.execute(
            select(func.count(AIQueueItem.id)).where(AIQueueItem.status == AIQueueStatus.RETRY_PENDING.value)
        ).scalar()
        
        total_quota_blocked = self.session.execute(
            select(func.count(AIQueueItem.id)).where(AIQueueItem.status == AIQueueStatus.QUOTA_BLOCKED.value)
        ).scalar()
        
        total_needs_attention = self.session.execute(
            select(func.count(AIQueueItem.id)).where(AIQueueItem.status == AIQueueStatus.NEEDS_ATTENTION.value)
        ).scalar()
        
        total_failed = self.session.execute(
            select(func.count(AIQueueItem.id)).where(AIQueueItem.status == AIQueueStatus.FAILED.value)
        ).scalar()
        
        total_items = total_queued + total_processing + total_completed + total_retry_pending + total_quota_blocked + total_needs_attention + total_failed
        
        # Get next item ID if any
        next_item = self.get_next_item()
        next_item_id = next_item.id if next_item else None
        
        return AIQueueStatusResponse(
            total_queued=total_queued,
            total_processing=total_processing,
            total_completed=total_completed,
            total_retry_pending=total_retry_pending,
            total_quota_blocked=total_quota_blocked,
            total_needs_attention=total_needs_attention,
            total_failed=total_failed,
            total_items=total_items,
            next_item_id=next_item_id
        )
    
    def process_item(self, queue_item_id: int, profile_context: str) -> AIQueueProcessingResult:
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
        # Initialize Gemini provider lazily
        if self.gemini_provider is None:
            self.gemini_provider = GeminiProvider()
        
        # Mark as processing
        item = self.mark_processing(queue_item_id)
        if not item:
            return AIQueueProcessingResult(
                success=False,
                status=AIQueueStatus.FAILED,
                failure_reason="Queue item not found or invalid state"
            )
        
        # Get job
        job = self.session.get(Job, item.job_id)
        if not job:
            return AIQueueProcessingResult(
                success=False,
                status=AIQueueStatus.FAILED,
                failure_reason="Job not found"
            )
        
        # Prepare job context
        job_context = f"Title: {job.title}\nCompany: {job.company}\nDescription: {job.description or ''}"
        
        try:
            # Call Gemini for analysis
            analysis = self.gemini_provider.analyze_job(job_context, profile_context)
            
            if not analysis:
                # Analysis failed - mark for retry
                self.mark_retry_pending(
                    queue_item_id,
                    "Gemini analysis returned None",
                    "Analysis provider returned None"
                )
                return AIQueueProcessingResult(
                    success=False,
                    status=AIQueueStatus.RETRY_PENDING,
                    failure_reason="Gemini analysis returned None"
                )
            
            # Store analysis result
            analysis_model = JobAnalysisModel(
                job_id=job.id,
                match_score=analysis.match_score,
                role_match=analysis.role_match,
                skill_match=analysis.skill_match,
                experience_match=analysis.experience_match,
                location_match=analysis.location_match,
                salary_match=analysis.salary_match,
                job_quality=analysis.job_quality.value,
                duplicate_probability=analysis.duplicate_probability,
                suspicious=analysis.suspicious,
                recommendation=analysis.recommendation.value,
                short_reason=analysis.short_reason,
                model="gemini",
                prompt_version="v1"
            )
            
            self.session.add(analysis_model)
            self.session.commit()
            self.session.refresh(analysis_model)
            
            # Mark as completed
            self.mark_completed(queue_item_id, analysis_model.id)
            
            return AIQueueProcessingResult(
                success=True,
                status=AIQueueStatus.COMPLETED,
                analysis_id=analysis_model.id
            )
            
        except APIQuotaExhaustedError as e:
            # Quota exhausted - mark as quota blocked
            self.mark_quota_blocked(queue_item_id, str(e))
            return AIQueueProcessingResult(
                success=False,
                status=AIQueueStatus.QUOTA_BLOCKED,
                failure_reason="Gemini quota exhausted",
                last_error=str(e)
            )
            
        except Exception as e:
            # Other error - mark for retry or needs attention
            error_str = str(e)
            logger.error(f"Error processing queue item {queue_item_id}: {error_str}", exc_info=True)
            
            self.mark_retry_pending(
                queue_item_id,
                f"Processing error: {error_str}",
                error_str
            )
            
            return AIQueueProcessingResult(
                success=False,
                status=AIQueueStatus.RETRY_PENDING,
                failure_reason=f"Processing error: {error_str}",
                last_error=error_str
            )
    
    def _calculate_priority(self, job: Job, priority_reason: Optional[str]) -> int:
        """
        Calculate deterministic priority for a job.
        
        Priority factors (higher = higher priority):
        - Jobs discovered earlier (lower priority)
        - Jobs with complete descriptions (higher priority)
        - Jobs from preferred sources (higher priority)
        
        Returns priority value (0-100).
        """
        priority = 50  # Base priority
        
        # Boost for complete description
        if job.description and len(job.description) > 200:
            priority += 20
        
        # Boost for recent discovery (within last 24 hours)
        if job.discovered_at:
            try:
                # Handle both timezone-aware and naive datetimes
                job_discovered = job.discovered_at
                if job_discovered.tzinfo is None:
                    job_discovered = job_discovered.replace(tzinfo=UTC)
                
                hours_since_discovery = (utc_now() - job_discovered).total_seconds() / 3600
                if hours_since_discovery < 24:
                    priority += 15
            except (AttributeError, TypeError):
                # Skip datetime calculation if there's an issue
                pass
        
        # Boost for known job title matches
        if job.title and any(keyword in job.title.lower() for keyword in ["python", "data", "machine learning", "ai", "engineer"]):
            priority += 10
        
        # Ensure priority is within bounds
        return max(0, min(100, priority))
    
    def _to_response(self, item: AIQueueItem) -> AIQueueItemResponse:
        """Convert model to response schema."""
        return AIQueueItemResponse(
            id=item.id,
            job_id=item.job_id,
            status=AIQueueStatus(item.status),
            priority=item.priority,
            priority_reason=item.priority_reason,
            attempt_count=item.attempt_count,
            max_attempts=item.max_attempts,
            last_attempt_at=item.last_attempt_at,
            next_retry_at=item.next_retry_at,
            failure_reason=item.failure_reason,
            last_error=item.last_error,
            analysis_id=item.analysis_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            completed_at=item.completed_at,
            queue_source=item.queue_source,
            processing_started_at=item.processing_started_at
        )
