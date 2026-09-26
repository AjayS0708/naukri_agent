"""
Tests for distributed work coordination service.

Covers:
- Atomic work claiming
- Ownership verification
- Heartbeat functionality
- Stale work detection
- Stale work recovery with safety semantics
- Release/complete/fail operations
- PostgreSQL and SQLite database behaviors
"""

import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy.orm import Session

from backend.models.ai_queue import AIQueueItem, utc_now
from backend.models.job import Job
from backend.schemas.ai_queue import AIQueueStatus
from backend.services.coordination import (
    WorkCoordinationService,
    WorkNotOwnedError,
    WorkStateError,
)


@pytest.fixture
def coordination_service(db: Session) -> WorkCoordinationService:
    """Create a coordination service with test database."""
    return WorkCoordinationService(db)


@pytest.fixture
def test_job(db: Session) -> Job:
    """Create a test job."""
    job = Job(
        platform="NAUKRI",
        external_job_id="naukri_123",
        title="Software Engineer",
        company="TestCorp",
        url="https://naukri.com/job/123",
        location="Mumbai",
        salary="12-15 LPA"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@pytest.fixture
def queued_item(db: Session, test_job: Job) -> AIQueueItem:
    """Create a QUEUED work item."""
    item = AIQueueItem(
        job_id=test_job.id,
        status=AIQueueStatus.QUEUED.value,
        priority=50
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


class TestClaimingBasics:
    """Test basic work claiming functionality."""

    def test_claim_eligible_work(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Worker can claim eligible QUEUED work."""
        work = coordination_service.claim_next_work("worker-1")

        assert work is not None
        assert work["id"] == queued_item.id
        assert work["claimed_by"] == "worker-1"
        assert work["last_heartbeat_at"] is not None

        # Verify in database
        db.refresh(queued_item)
        assert queued_item.claimed_by == "worker-1"

    def test_claim_no_eligible_work(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Claim returns None when no eligible work."""
        work = coordination_service.claim_next_work("worker-1")
        assert work is None

    def test_claim_respects_priority(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        test_job: Job
    ):
        """Claim selects highest priority work."""
        # Create low priority item
        low = AIQueueItem(
            job_id=test_job.id,
            status=AIQueueStatus.QUEUED.value,
            priority=10
        )
        db.add(low)
        db.commit()

        # Create high priority item
        job2 = Job(
            platform="NAUKRI",
            external_job_id="naukri_456",
            title="Engineer",
            company="Corp",
            url="https://naukri.com/job/456",
            location="Delhi"
        )
        db.add(job2)
        db.commit()

        high = AIQueueItem(
            job_id=job2.id,
            status=AIQueueStatus.QUEUED.value,
            priority=90
        )
        db.add(high)
        db.commit()

        # Claim should get high priority
        work = coordination_service.claim_next_work("worker-1")
        assert work["id"] == high.id
        assert work["priority"] == 90

    def test_claim_already_claimed_excluded(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Already-claimed work is excluded from claiming."""
        # First worker claims it
        work1 = coordination_service.claim_next_work("worker-1")
        assert work1 is not None

        # Second worker cannot claim same item
        work2 = coordination_service.claim_next_work("worker-2")
        assert work2 is None

    def test_claim_respects_available_at(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Claim respects available_at timestamp."""
        future = utc_now() + timedelta(minutes=5)
        queued_item.available_at = future
        db.commit()

        # Cannot claim while available_at is in future
        work = coordination_service.claim_next_work("worker-1")
        assert work is None

        # Can claim after available_at passes
        queued_item.available_at = utc_now() - timedelta(seconds=1)
        db.commit()

        work = coordination_service.claim_next_work("worker-1")
        assert work is not None

    def test_claim_retry_pending_items(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        test_job: Job
    ):
        """Claim can select RETRY_PENDING items."""
        item = AIQueueItem(
            job_id=test_job.id,
            status=AIQueueStatus.RETRY_PENDING.value,
            priority=50,
            next_retry_at=utc_now() - timedelta(seconds=1)
        )
        db.add(item)
        db.commit()

        work = coordination_service.claim_next_work("worker-1")
        assert work is not None
        assert work["id"] == item.id

    def test_claim_completed_excluded(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """COMPLETED work is not claimable."""
        queued_item.status = AIQueueStatus.COMPLETED.value
        queued_item.completed_at = utc_now()
        db.commit()

        work = coordination_service.claim_next_work("worker-1")
        assert work is None

    def test_claim_failed_excluded(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """FAILED work is not claimable."""
        queued_item.status = AIQueueStatus.FAILED.value
        db.commit()

        work = coordination_service.claim_next_work("worker-1")
        assert work is None

    def test_multiple_workers_dont_claim_same_item(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        test_job: Job
    ):
        """Two workers cannot both claim the same item."""
        item = AIQueueItem(
            job_id=test_job.id,
            status=AIQueueStatus.QUEUED.value,
            priority=50
        )
        db.add(item)
        db.commit()

        # First worker claims
        work1 = coordination_service.claim_next_work("worker-1")
        assert work1 is not None
        assert work1["claimed_by"] == "worker-1"

        # Second worker gets nothing
        work2 = coordination_service.claim_next_work("worker-2")
        assert work2 is None


class TestOwnershipVerification:
    """Test ownership verification for operations."""

    def test_wrong_worker_cannot_heartbeat(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Non-owning worker cannot heartbeat work."""
        # Worker 1 claims
        coordination_service.claim_next_work("worker-1")

        # Worker 2 cannot heartbeat
        with pytest.raises(WorkNotOwnedError):
            coordination_service.heartbeat_work("worker-2", queued_item.id)

    def test_wrong_worker_cannot_release(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Non-owning worker cannot release work."""
        coordination_service.claim_next_work("worker-1")

        with pytest.raises(WorkNotOwnedError):
            coordination_service.release_work("worker-2", queued_item.id)

    def test_wrong_worker_cannot_complete(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Non-owning worker cannot complete work."""
        coordination_service.claim_next_work("worker-1")

        with pytest.raises(WorkNotOwnedError):
            coordination_service.complete_work("worker-2", queued_item.id)

    def test_wrong_worker_cannot_fail(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Non-owning worker cannot fail work."""
        coordination_service.claim_next_work("worker-1")

        with pytest.raises(WorkNotOwnedError):
            coordination_service.fail_work("worker-2", queued_item.id, "some error")


class TestHeartbeat:
    """Test heartbeat functionality."""

    def test_owner_can_heartbeat(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Owner can heartbeat work."""
        coordination_service.claim_next_work("worker-1")

        before = utc_now()
        result = coordination_service.heartbeat_work("worker-1", queued_item.id)
        after = utc_now()

        assert result is True

        db.refresh(queued_item)
        assert queued_item.last_heartbeat_at is not None

        # Handle timezone-aware comparison
        ts = queued_item.last_heartbeat_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        assert before <= ts <= after

    def test_heartbeat_nonexistent_work(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Heartbeat returns False for missing work."""
        result = coordination_service.heartbeat_work("worker-1", 99999)
        assert result is False

    def test_cannot_heartbeat_completed_work(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Cannot heartbeat COMPLETED work."""
        coordination_service.claim_next_work("worker-1")

        # Complete the work
        coordination_service.complete_work("worker-1", queued_item.id)

        # Cannot heartbeat completed work
        with pytest.raises(WorkStateError):
            coordination_service.heartbeat_work("worker-1", queued_item.id)

    def test_cannot_heartbeat_failed_work(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Cannot heartbeat FAILED work."""
        coordination_service.claim_next_work("worker-1")

        # Fail the work
        coordination_service.fail_work("worker-1", queued_item.id, "error")

        # Cannot heartbeat failed work
        with pytest.raises(WorkStateError):
            coordination_service.heartbeat_work("worker-1", queued_item.id)

    def test_heartbeat_updates_timestamp(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Multiple heartbeats update timestamp each time."""
        coordination_service.claim_next_work("worker-1")

        hb1 = utc_now()
        coordination_service.heartbeat_work("worker-1", queued_item.id)
        db.refresh(queued_item)
        ts1 = queued_item.last_heartbeat_at

        # Wait a bit
        import time
        time.sleep(0.1)

        hb2 = utc_now()
        coordination_service.heartbeat_work("worker-1", queued_item.id)
        db.refresh(queued_item)
        ts2 = queued_item.last_heartbeat_at

        assert ts2 > ts1


class TestStaleDetection:
    """Test stale work detection."""

    def test_detect_stale_work(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Stale work is detected."""
        # Claim work
        coordination_service.claim_next_work("worker-1")

        # Make it stale by setting old heartbeat
        stale_time = utc_now() - timedelta(minutes=35)
        queued_item.last_heartbeat_at = stale_time
        db.commit()

        stale = coordination_service.detect_stale_work()
        assert len(stale) == 1
        assert stale[0]["id"] == queued_item.id

    def test_fresh_work_not_detected_stale(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Recent heartbeat prevents stale detection."""
        # Claim and heartbeat
        coordination_service.claim_next_work("worker-1")
        coordination_service.heartbeat_work("worker-1", queued_item.id)

        stale = coordination_service.detect_stale_work()
        assert len(stale) == 0

    def test_completed_work_not_detected_stale(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """COMPLETED work is not detected as stale."""
        queued_item.status = AIQueueStatus.COMPLETED.value
        queued_item.completed_at = utc_now()
        queued_item.claimed_by = "worker-1"
        queued_item.last_heartbeat_at = utc_now() - timedelta(minutes=60)
        db.commit()

        stale = coordination_service.detect_stale_work()
        assert len(stale) == 0

    def test_failed_work_not_detected_stale(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """FAILED work is not detected as stale."""
        queued_item.status = AIQueueStatus.FAILED.value
        queued_item.claimed_by = "worker-1"
        queued_item.last_heartbeat_at = utc_now() - timedelta(minutes=60)
        db.commit()

        stale = coordination_service.detect_stale_work()
        assert len(stale) == 0

    def test_unclaimed_work_not_detected_stale(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Unclaimed work is not detected as stale."""
        queued_item.claimed_by = None
        queued_item.last_heartbeat_at = utc_now() - timedelta(minutes=60)
        db.commit()

        stale = coordination_service.detect_stale_work()
        assert len(stale) == 0


class TestStaleRecovery:
    """Test stale work recovery with safety semantics."""

    def test_recover_stale_work_to_retry(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Stale work within attempt limit recovered to RETRY_PENDING."""
        # Claim and make stale
        coordination_service.claim_next_work("worker-1")
        queued_item.last_heartbeat_at = utc_now() - timedelta(minutes=35)
        queued_item.attempt_count = 1
        queued_item.max_attempts = 3
        db.commit()

        result = coordination_service.recover_stale_work(queued_item.id)

        assert result is not None
        assert result["status"] == AIQueueStatus.RETRY_PENDING.value
        assert result["claimed_by"] is None
        assert result["last_heartbeat_at"] is None

    def test_recover_stale_work_exceeds_attempts(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Stale work exceeding attempts goes to NEEDS_ATTENTION (safety)."""
        # Claim and make stale
        coordination_service.claim_next_work("worker-1")
        queued_item.last_heartbeat_at = utc_now() - timedelta(minutes=35)
        queued_item.attempt_count = 3
        queued_item.max_attempts = 3
        db.commit()

        result = coordination_service.recover_stale_work(queued_item.id)

        assert result is not None
        assert result["status"] == AIQueueStatus.NEEDS_ATTENTION.value
        assert result["claimed_by"] is None
        assert "uncertain execution outcome" in result["failure_reason"]

    def test_recover_not_stale_fails(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Recovery fails for non-stale work."""
        # Claim with fresh heartbeat
        coordination_service.claim_next_work("worker-1")
        coordination_service.heartbeat_work("worker-1", queued_item.id)

        result = coordination_service.recover_stale_work(queued_item.id)
        assert result is None

    def test_recover_unclaimed_fails(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Recovery fails for unclaimed work."""
        queued_item.claimed_by = None
        db.commit()

        result = coordination_service.recover_stale_work(queued_item.id)
        assert result is None

    def test_recover_nonexistent_fails(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Recovery fails for missing work."""
        result = coordination_service.recover_stale_work(99999)
        assert result is None

    def test_stale_recovery_does_not_bypass_safety(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Stale recovery with max attempts escalates to NEEDS_ATTENTION.

        This ensures uncertain execution outcomes (browser crash, etc)
        don't bypass duplicate detection or application safety gates.
        Recovery with exhausted attempts goes to NEEDS_ATTENTION rather
        than blindly retrying application.
        """
        coordination_service.claim_next_work("worker-1")
        queued_item.last_heartbeat_at = utc_now() - timedelta(minutes=40)
        queued_item.attempt_count = 3
        queued_item.max_attempts = 3
        db.commit()

        result = coordination_service.recover_stale_work(queued_item.id)

        # Should NOT be automatically retried
        assert result["status"] == AIQueueStatus.NEEDS_ATTENTION.value
        # Should have helpful context for human review
        assert result["failure_reason"] is not None


class TestReleaseCompleteFail:
    """Test release, complete, and fail operations."""

    def test_release_work(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Owner can release work with backoff."""
        coordination_service.claim_next_work("worker-1")

        result = coordination_service.release_work("worker-1", queued_item.id)

        assert result is not None
        assert result["claimed_by"] is None
        assert result["available_at"] is not None
        # Available_at should be roughly 5 minutes in future
        available_at = result["available_at"]
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=UTC)
        now = utc_now()
        time_diff = (available_at - now).total_seconds()
        assert 250 < time_diff < 350  # ~5 minutes, with some tolerance

    def test_release_creates_backoff(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Released work has backoff preventing immediate reclaim."""
        coordination_service.claim_next_work("worker-1")
        coordination_service.release_work("worker-1", queued_item.id)

        # Cannot claim immediately
        work = coordination_service.claim_next_work("worker-2")
        assert work is None

    def test_complete_work(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Owner can complete work."""
        coordination_service.claim_next_work("worker-1")

        result = coordination_service.complete_work("worker-1", queued_item.id)

        assert result is not None
        assert result["status"] == AIQueueStatus.COMPLETED.value
        assert result["claimed_by"] is None

    def test_fail_work(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Owner can fail work with error details."""
        coordination_service.claim_next_work("worker-1")

        result = coordination_service.fail_work(
            "worker-1",
            queued_item.id,
            "Browser crashed",
            "Execution error: Browser crashed"
        )

        assert result is not None
        assert result["status"] == AIQueueStatus.FAILED.value
        assert result["claimed_by"] is None

        db.refresh(queued_item)
        assert queued_item.failure_reason == "Execution error: Browser crashed"
        assert queued_item.last_error == "Browser crashed"

    def test_complete_idempotent(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Completing already-completed work is safe."""
        coordination_service.claim_next_work("worker-1")
        result1 = coordination_service.complete_work("worker-1", queued_item.id)

        # Try to complete again (simulating retry)
        result2 = coordination_service.complete_work("worker-1", queued_item.id)

        assert result2 is not None
        assert result2["status"] == AIQueueStatus.COMPLETED.value


class TestWorkerLoad:
    """Test worker load tracking."""

    def test_get_worker_load_empty(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Worker with no work has zero load."""
        load = coordination_service.get_worker_load("worker-1")

        assert load["worker_id"] == "worker-1"
        assert load["claimed_count"] == 0
        assert load["processing_count"] == 0

    def test_get_worker_load_claimed(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        test_job: Job
    ):
        """Worker load counts claimed items."""
        # Create multiple items
        for i in range(3):
            item = AIQueueItem(
                job_id=test_job.id,
                status=AIQueueStatus.QUEUED.value,
                priority=50 - i
            )
            db.add(item)
        db.commit()

        # Claim all for worker-1
        for _ in range(3):
            coordination_service.claim_next_work("worker-1")

        load = coordination_service.get_worker_load("worker-1")
        assert load["claimed_count"] == 3

    def test_get_worker_load_processing_subset(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        test_job: Job
    ):
        """Worker load distinguishes PROCESSING items."""
        # Create items
        for i in range(3):
            item = AIQueueItem(
                job_id=test_job.id,
                status=AIQueueStatus.QUEUED.value,
                priority=50 - i
            )
            db.add(item)
        db.commit()

        # Claim all
        for _ in range(3):
            coordination_service.claim_next_work("worker-1")

        # Mark one as PROCESSING
        items = db.query(AIQueueItem).filter_by(claimed_by="worker-1").all()
        items[0].status = AIQueueStatus.PROCESSING.value
        db.commit()

        load = coordination_service.get_worker_load("worker-1")
        assert load["claimed_count"] == 3
        assert load["processing_count"] == 1


class TestDeterministicPriority:
    """Test deterministic priority-based selection."""

    def test_claim_deterministic_by_priority_then_creation(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        test_job: Job
    ):
        """Claiming is deterministic: priority desc, then created_at asc."""
        # Create items with same priority, different creation times
        items = []
        for i in range(3):
            item = AIQueueItem(
                job_id=test_job.id,
                status=AIQueueStatus.QUEUED.value,
                priority=50
            )
            db.add(item)
            db.flush()
            items.append(item)

        db.commit()

        # First to claim should be first created (earliest created_at)
        work1 = coordination_service.claim_next_work("worker-1")
        assert work1["id"] == items[0].id

        work2 = coordination_service.claim_next_work("worker-2")
        assert work2["id"] == items[1].id

        work3 = coordination_service.claim_next_work("worker-3")
        assert work3["id"] == items[2].id

    def test_claim_priority_overrides_creation_time(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        test_job: Job
    ):
        """Higher priority is claimed before earlier-created lower priority."""
        # Create low priority item
        low = AIQueueItem(
            job_id=test_job.id,
            status=AIQueueStatus.QUEUED.value,
            priority=10
        )
        db.add(low)
        db.flush()

        # Create high priority item (after low)
        high = AIQueueItem(
            job_id=test_job.id,
            status=AIQueueStatus.QUEUED.value,
            priority=90
        )
        db.add(high)
        db.commit()

        # High priority should be claimed first despite later creation
        work = coordination_service.claim_next_work("worker-1")
        assert work["id"] == high.id


class TestDatabaseCompatibility:
    """Test database-specific behavior."""

    def test_service_detects_database_dialect(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Service identifies database dialect."""
        dialect = coordination_service.db_dialect
        assert dialect in ["sqlite", "postgresql"]

    def test_claiming_works_with_current_database(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Claiming works regardless of database type."""
        work = coordination_service.claim_next_work("worker-1")

        assert work is not None
        assert work["claimed_by"] == "worker-1"


class TestEdgeCases:
    """Test edge cases and error scenarios."""

    def test_heartbeat_missing_work_returns_false(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Heartbeat returns False for missing work (no exception)."""
        result = coordination_service.heartbeat_work("worker-1", 99999)
        assert result is False

    def test_release_missing_work_returns_none(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Release returns None for missing work."""
        result = coordination_service.release_work("worker-1", 99999)
        assert result is None

    def test_complete_missing_work_returns_none(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Complete returns None for missing work."""
        result = coordination_service.complete_work("worker-1", 99999)
        assert result is None

    def test_fail_missing_work_returns_none(
        self,
        coordination_service: WorkCoordinationService
    ):
        """Fail returns None for missing work."""
        result = coordination_service.fail_work("worker-1", 99999, "error")
        assert result is None

    def test_claim_empty_available_at_included(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Items with null available_at are immediately available."""
        assert queued_item.available_at is None

        work = coordination_service.claim_next_work("worker-1")
        assert work is not None

    def test_multiple_workers_independent_loads(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        test_job: Job
    ):
        """Workers have independent work loads."""
        # Create items
        for i in range(4):
            item = AIQueueItem(
                job_id=test_job.id,
                status=AIQueueStatus.QUEUED.value,
                priority=50 - i
            )
            db.add(item)
        db.commit()

        # Worker 1 claims 2
        coordination_service.claim_next_work("worker-1")
        coordination_service.claim_next_work("worker-1")

        # Worker 2 claims 2
        coordination_service.claim_next_work("worker-2")
        coordination_service.claim_next_work("worker-2")

        load1 = coordination_service.get_worker_load("worker-1")
        load2 = coordination_service.get_worker_load("worker-2")

        assert load1["claimed_count"] == 2
        assert load2["claimed_count"] == 2


class TestSafetyPreservation:
    """Test that existing safety architecture is preserved."""

    def test_coordination_does_not_modify_queue_status_on_claim(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Claiming does not change queue item status (coordination is separate)."""
        original_status = queued_item.status

        coordination_service.claim_next_work("worker-1")

        db.refresh(queued_item)
        # Status should remain QUEUED - coordination is orthogonal
        assert queued_item.status == original_status

    def test_stale_recovery_with_exhausted_attempts_requires_review(
        self,
        db: Session,
        coordination_service: WorkCoordinationService,
        queued_item: AIQueueItem
    ):
        """Stale recovery with exhausted attempts goes to NEEDS_ATTENTION.

        This is a critical safety requirement: if execution outcome is uncertain
        (worker crashed, no heartbeat, max attempts exceeded), we preserve the
        requirement for human review before retry.
        """
        coordination_service.claim_next_work("worker-1")
        queued_item.last_heartbeat_at = utc_now() - timedelta(minutes=40)
        queued_item.attempt_count = 3
        queued_item.max_attempts = 3
        db.commit()

        result = coordination_service.recover_stale_work(queued_item.id)

        # Must not auto-retry
        assert result["status"] == AIQueueStatus.NEEDS_ATTENTION.value
        # Must provide context for review
        assert "uncertain" in result["failure_reason"].lower()

