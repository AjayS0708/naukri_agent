from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.orm import Session

from backend.models.ai_queue import AIQueueItem, utc_now
from backend.models.worker import Worker
from backend.schemas.ai_queue import AIQueueStatus
from backend.core.logging import get_logger

logger = get_logger(__name__)


class WorkNotOwnedError(Exception):
    """Raised when a worker attempts an operation on work it doesn't own."""
    pass


class WorkNotFoundError(Exception):
    """Raised when a work item is not found."""
    pass


class WorkStateError(Exception):
    """Raised when a work item is in an invalid state for the operation."""
    pass


class WorkCoordinationService:
    """
    Coordinates ownership of distributed AI queue work among multiple workers.

    Provides atomic work claiming, heartbeat tracking, stale detection, and
    safe recovery semantics without bypassing existing application safety gates.

    Database-specific claiming:
    - PostgreSQL: Uses atomic SELECT...FOR UPDATE SKIP LOCKED
    - SQLite: Uses transaction-safe fallback without row-level locking

    Work ownership rules:
    - Only claiming worker can heartbeat, release, complete, or fail work
    - Stale work (no heartbeat > threshold) can be recovered with NEEDS_ATTENTION safety
    - Duplicate application protection remains authoritative
    - Application safety gates remain authoritative
    """

    def __init__(self, session: Session):
        self.session = session
        # Stale work threshold: items without heartbeat for 30 minutes are stale
        self.stale_threshold = timedelta(minutes=30)
        # Database dialect for conditional behavior
        self.db_dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"

    def claim_next_work(self, worker_id: str) -> Optional[dict]:
        """
        Atomically claim the next available work item for a worker.

        Selection criteria (deterministic by priority then creation order):
        1. Status must be QUEUED or RETRY_PENDING
        2. No current owner (claimed_by is null)
        3. available_at is null or in the past
        4. Ordered by priority (descending) then created_at (ascending)

        Returns work item dict with fields: id, job_id, priority, created_at, etc.
        Returns None if no eligible work available.

        PostgreSQL: Uses SELECT...FOR UPDATE SKIP LOCKED for atomicity
        SQLite: Uses transaction-safe fallback without row-level locking
        """
        now = utc_now()

        try:
            if self.db_dialect == "postgresql":
                return self._claim_work_postgresql(worker_id, now)
            else:
                # SQLite and other databases use transaction-safe fallback
                return self._claim_work_generic(worker_id, now)
        except Exception as e:
            logger.error(f"Error claiming work for worker {worker_id}: {e}", exc_info=True)
            return None

    def _claim_work_postgresql(self, worker_id: str, now: datetime) -> Optional[dict]:
        """
        PostgreSQL-specific claiming using atomic row-locking.

        Uses SELECT...FOR UPDATE SKIP LOCKED to:
        1. Lock the highest-priority available row
        2. Skip already-locked rows (other workers)
        3. Atomically assign it to this worker
        """
        # Subquery to find eligible items with proper ordering
        eligible = select(AIQueueItem).where(
            and_(
                AIQueueItem.status.in_([
                    AIQueueStatus.QUEUED.value,
                    AIQueueStatus.RETRY_PENDING.value
                ]),
                AIQueueItem.claimed_by.is_(None),
                or_(
                    AIQueueItem.available_at.is_(None),
                    AIQueueItem.available_at <= now
                )
            )
        ).order_by(
            AIQueueItem.priority.desc(),
            AIQueueItem.created_at.asc()
        ).limit(1).with_for_update(skip_locked=True)

        item = self.session.execute(eligible).scalars().first()

        if not item:
            return None

        # Atomically claim within same transaction
        item.claimed_by = worker_id
        item.last_heartbeat_at = now
        item.available_at = None
        self.session.commit()

        logger.info(
            f"Worker {worker_id} claimed work item {item.id} "
            f"(priority={item.priority})"
        )

        return self._item_to_dict(item)

    def _claim_work_generic(self, worker_id: str, now: datetime) -> Optional[dict]:
        """
        Database-agnostic claiming using transaction-safe selection.

        Works with SQLite and other databases without row-level locking.
        Uses transaction isolation to prevent most race conditions.

        Note: SQLite and transaction-only databases cannot guarantee
        the atomicity that PostgreSQL's SKIP LOCKED provides. Multiple
        workers may briefly see the same item. Claiming worker validates
        ownership before proceeding.
        """
        # Select eligible items deterministically
        stmt = select(AIQueueItem).where(
            and_(
                AIQueueItem.status.in_([
                    AIQueueStatus.QUEUED.value,
                    AIQueueStatus.RETRY_PENDING.value
                ]),
                AIQueueItem.claimed_by.is_(None),
                or_(
                    AIQueueItem.available_at.is_(None),
                    AIQueueItem.available_at <= now
                )
            )
        ).order_by(
            AIQueueItem.priority.desc(),
            AIQueueItem.created_at.asc()
        ).limit(1)

        item = self.session.execute(stmt).scalars().first()

        if not item:
            return None

        # Claim within transaction
        item.claimed_by = worker_id
        item.last_heartbeat_at = now
        item.available_at = None
        self.session.commit()

        logger.info(
            f"Worker {worker_id} claimed work item {item.id} "
            f"(priority={item.priority})"
        )

        return self._item_to_dict(item)

    def heartbeat_work(self, worker_id: str, work_id: int) -> bool:
        """
        Update heartbeat for a work item to prevent stale detection.

        Verifies worker owns the item and it's in a claimable state.

        Returns True if heartbeat successful, False otherwise.
        Raises WorkNotOwnedError if worker doesn't own the item.
        Raises WorkStateError if item is in a terminal state.
        """
        item = self.session.get(AIQueueItem, work_id)

        if not item:
            logger.warning(f"Heartbeat: work item {work_id} not found")
            return False

        # Check terminal states first (before ownership check)
        if item.status in [
            AIQueueStatus.COMPLETED.value,
            AIQueueStatus.FAILED.value,
            AIQueueStatus.NEEDS_ATTENTION.value
        ]:
            logger.warning(
                f"Heartbeat: cannot heartbeat work {work_id} in {item.status} state"
            )
            raise WorkStateError(
                f"Cannot heartbeat work item in {item.status} state"
            )

        # Verify ownership
        if item.claimed_by != worker_id:
            logger.warning(
                f"Heartbeat: worker {worker_id} does not own work {work_id} "
                f"(owned by {item.claimed_by})"
            )
            raise WorkNotOwnedError(
                f"Worker {worker_id} does not own work item {work_id}"
            )

        # Update heartbeat timestamp
        item.last_heartbeat_at = utc_now()
        self.session.commit()

        logger.debug(f"Worker {worker_id} heartbeat work {work_id}")
        return True

    def detect_stale_work(self) -> list[dict]:
        """
        Detect work items stuck in processing without recent heartbeat.

        Stale criteria:
        - Status in [PROCESSING, QUEUED, RETRY_PENDING] (actively being worked)
        - Has a worker owner (claimed_by is not null)
        - Last heartbeat older than stale_threshold

        Returns list of stale work item dicts.
        Does not modify any state.
        """
        now = utc_now()
        stale_cutoff = now - self.stale_threshold

        stale_items = self.session.execute(
            select(AIQueueItem).where(
                and_(
                    AIQueueItem.claimed_by.isnot(None),
                    AIQueueItem.status.in_([
                        AIQueueStatus.PROCESSING.value,
                        AIQueueStatus.QUEUED.value,
                        AIQueueStatus.RETRY_PENDING.value
                    ]),
                    or_(
                        AIQueueItem.last_heartbeat_at.is_(None),
                        AIQueueItem.last_heartbeat_at < stale_cutoff
                    )
                )
            )
        ).scalars().all()

        result = [self._item_to_dict(item) for item in stale_items]
        if result:
            logger.info(f"Detected {len(result)} stale work items")

        return result

    def recover_stale_work(self, work_id: int) -> Optional[dict]:
        """
        Recover a stale work item by clearing ownership and advancing it.

        Safety-critical: stale recovery must NOT blindly retry application.

        Recovery behavior:
        - Clear claimed_by
        - Clear last_heartbeat_at
        - If item hasn't exceeded max_attempts, return to RETRY_PENDING with
          next_retry_at set to now (eligible immediately)
        - If item has exceeded max_attempts, transition to NEEDS_ATTENTION
          (human review required, preserves existing safety gate)

        This ensures uncertain execution outcomes don't bypass duplicate
        protection or application safety gates.

        Returns updated item dict, or None if recovery failed.
        """
        item = self.session.get(AIQueueItem, work_id)

        if not item:
            logger.warning(f"Recovery: work item {work_id} not found")
            return None

        # Only recover items that are actually stale
        if not item.claimed_by:
            logger.warning(
                f"Recovery: work item {work_id} is not owned by any worker"
            )
            return None

        now = utc_now()
        stale_cutoff = now - self.stale_threshold

        # Handle both timezone-aware and naive datetimes
        last_hb = item.last_heartbeat_at
        if last_hb:
            # Ensure timezone-aware comparison
            if last_hb.tzinfo is None:
                last_hb = last_hb.replace(tzinfo=UTC)

            if last_hb > stale_cutoff:
                logger.warning(
                    f"Recovery: work item {work_id} is not stale "
                    f"(last heartbeat {last_hb})"
                )
                return None

        # Clear ownership
        item.claimed_by = None
        item.last_heartbeat_at = None

        # Determine recovery path based on attempt count
        if item.attempt_count < item.max_attempts:
            # Safe to retry: hasn't exceeded attempt limit
            item.status = AIQueueStatus.RETRY_PENDING.value
            item.next_retry_at = now  # Eligible immediately
            logger.info(
                f"Recovered stale work {work_id} to RETRY_PENDING "
                f"(attempt {item.attempt_count}/{item.max_attempts})"
            )
        else:
            # Exceeded attempts: escalate to NEEDS_ATTENTION
            # This preserves existing safety architecture and requires human review
            item.status = AIQueueStatus.NEEDS_ATTENTION.value
            item.failure_reason = (
                "Stale work recovery: max attempts exceeded, "
                "uncertain execution outcome, requires review"
            )
            logger.warning(
                f"Recovered stale work {work_id} to NEEDS_ATTENTION "
                f"(max attempts {item.max_attempts} exceeded)"
            )

        self.session.commit()
        return self._item_to_dict(item)

    def release_work(self, worker_id: str, work_id: int) -> Optional[dict]:
        """
        Release ownership of a work item without completing it.

        Verifies worker owns the item. Item transitions back to eligible
        for claiming after release_delay seconds (default 5min backoff).

        Use cases:
        - Worker cannot complete processing right now
        - Processing needs to be deferred
        - Item should be reattempted by different worker

        Returns updated item dict, or None if release failed.
        Raises WorkNotOwnedError if worker doesn't own the item.
        """
        item = self.session.get(AIQueueItem, work_id)

        if not item:
            logger.warning(f"Release: work item {work_id} not found")
            return None

        # Verify ownership
        if item.claimed_by != worker_id:
            logger.warning(
                f"Release: worker {worker_id} does not own work {work_id} "
                f"(owned by {item.claimed_by})"
            )
            raise WorkNotOwnedError(
                f"Worker {worker_id} does not own work item {work_id}"
            )

        # Clear ownership with backoff
        item.claimed_by = None
        item.last_heartbeat_at = None
        release_delay = timedelta(minutes=5)
        item.available_at = utc_now() + release_delay

        self.session.commit()

        logger.info(
            f"Worker {worker_id} released work {work_id} "
            f"(available_at {item.available_at})"
        )

        return self._item_to_dict(item)

    def complete_work(self, worker_id: str, work_id: int) -> Optional[dict]:
        """
        Mark a work item as COMPLETED by its owning worker.

        Verifies worker owns the item (or item is already completed). Clears ownership
        and transitions to COMPLETED state. This is terminal for the queue item.

        Idempotent: safely handles repeated completion calls.

        Returns updated item dict, or None if completion failed.
        Raises WorkNotOwnedError if worker doesn't own the item and item isn't completed.
        """
        item = self.session.get(AIQueueItem, work_id)

        if not item:
            logger.warning(f"Complete: work item {work_id} not found")
            return None

        # Allow idempotent completion: if already completed, just return
        if item.status == AIQueueStatus.COMPLETED.value:
            logger.debug(f"Complete: work {work_id} already completed, idempotent call")
            return self._item_to_dict(item)

        # Verify ownership for non-completed items
        if item.claimed_by != worker_id:
            logger.warning(
                f"Complete: worker {worker_id} does not own work {work_id} "
                f"(owned by {item.claimed_by})"
            )
            raise WorkNotOwnedError(
                f"Worker {worker_id} does not own work item {work_id}"
            )

        # Clear ownership and mark complete
        item.claimed_by = None
        item.last_heartbeat_at = None
        item.available_at = None
        item.status = AIQueueStatus.COMPLETED.value
        item.completed_at = utc_now()

        self.session.commit()

        logger.info(f"Worker {worker_id} completed work {work_id}")
        return self._item_to_dict(item)

    def fail_work(
        self,
        worker_id: str,
        work_id: int,
        error: str,
        failure_reason: Optional[str] = None
    ) -> Optional[dict]:
        """
        Mark a work item as FAILED by its owning worker.

        Verifies worker owns the item. Clears ownership and transitions
        to FAILED state. This is terminal for the queue item.

        Use cases:
        - Unrecoverable processing error
        - Duplicate application detected
        - Safety gate prevents application
        - Job no longer exists

        Returns updated item dict, or None if fail operation failed.
        Raises WorkNotOwnedError if worker doesn't own the item.
        """
        item = self.session.get(AIQueueItem, work_id)

        if not item:
            logger.warning(f"Fail: work item {work_id} not found")
            return None

        # Verify ownership
        if item.claimed_by != worker_id:
            logger.warning(
                f"Fail: worker {worker_id} does not own work {work_id} "
                f"(owned by {item.claimed_by})"
            )
            raise WorkNotOwnedError(
                f"Worker {worker_id} does not own work item {work_id}"
            )

        # Clear ownership and mark failed
        item.claimed_by = None
        item.last_heartbeat_at = None
        item.available_at = None
        item.status = AIQueueStatus.FAILED.value
        item.failure_reason = failure_reason or error
        item.last_error = error
        item.completed_at = utc_now()

        self.session.commit()

        logger.info(
            f"Worker {worker_id} failed work {work_id}: {failure_reason or error}"
        )

        return self._item_to_dict(item)

    def get_worker_load(self, worker_id: str) -> dict:
        """
        Get current work load for a worker.

        Returns dict with:
        - claimed_count: items currently owned by worker
        - processing_count: items in PROCESSING state
        """
        claimed = self.session.execute(
            select(AIQueueItem).where(AIQueueItem.claimed_by == worker_id)
        ).scalars().all()
        claimed_count = len(claimed)

        processing_count = len([
            item for item in claimed
            if item.status == AIQueueStatus.PROCESSING.value
        ])

        return {
            "worker_id": worker_id,
            "claimed_count": claimed_count,
            "processing_count": processing_count
        }

    def _item_to_dict(self, item: AIQueueItem) -> dict:
        """Convert AIQueueItem model to dict."""
        return {
            "id": item.id,
            "job_id": item.job_id,
            "status": item.status,
            "priority": item.priority,
            "claimed_by": item.claimed_by,
            "last_heartbeat_at": item.last_heartbeat_at,
            "available_at": item.available_at,
            "attempt_count": item.attempt_count,
            "max_attempts": item.max_attempts,
            "failure_reason": item.failure_reason,
            "created_at": item.created_at,
            "updated_at": item.updated_at
        }
