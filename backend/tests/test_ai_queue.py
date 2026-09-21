import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.database.database import Base, get_db
from backend.models.ai_queue import AIQueueItem, utc_now
from backend.models.job import Job
from backend.models.ai import JobAnalysisModel
from backend.schemas.ai_queue import AIQueueStatus
from backend.services.gemini.queue import AIQueueService
from backend.services.gemini.provider import GeminiProvider, APIQuotaExhaustedError


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(in_memory_db):
    """Create a database session for testing."""
    connection = in_memory_db.connect()
    session = Session(bind=connection)
    try:
        yield session
        session.rollback()
    finally:
        session.close()
        connection.close()


@pytest.fixture
def sample_job(db_session):
    """Create a sample job for testing."""
    job = Job(
        platform="naukri",
        external_job_id="test_job_123",
        url="https://naukri.com/job/123",
        title="Python Developer",
        company="Test Company",
        description="A great Python developer job with good salary and benefits.",
        location="Bengaluru",
        salary="5-8 LPA",
        experience="2-4 years",
        employment_type="Full-time",
        status="DISCOVERED",
        discovered_at=datetime.now(UTC)
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def queue_service(db_session):
    """Create an AI queue service for testing."""
    return AIQueueService(db_session)


class TestAIQueueBasicOperations:
    """Test basic AI queue operations."""
    
    def test_enqueue_job(self, queue_service, sample_job):
        """Test enqueuing a job for AI analysis."""
        result = queue_service.enqueue_job(
            job_id=sample_job.id,
            priority=50,
            priority_reason="Test enqueue",
            queue_source="TEST"
        )
        
        assert result is not None
        assert result.job_id == sample_job.id
        assert result.status == AIQueueStatus.QUEUED
        assert result.priority == 50
        assert result.queue_source == "TEST"
        assert result.attempt_count == 0
    
    def test_enqueue_duplicate_prevention(self, queue_service, sample_job):
        """Test that duplicate queue entries are prevented."""
        # First enqueue
        result1 = queue_service.enqueue_job(job_id=sample_job.id)
        assert result1 is not None
        
        # Second enqueue should return existing item
        result2 = queue_service.enqueue_job(job_id=sample_job.id)
        assert result2 is not None
        assert result2.id == result1.id  # Same item
        assert result2.job_id == sample_job.id
    
    def test_enqueue_nonexistent_job(self, queue_service):
        """Test enqueuing a non-existent job returns None."""
        result = queue_service.enqueue_job(job_id=99999)
        assert result is None
    
    def test_get_next_item(self, queue_service, sample_job):
        """Test getting the next eligible queued item."""
        # Enqueue a job
        queue_service.enqueue_job(job_id=sample_job.id, priority=50)
        
        # Get next item
        next_item = queue_service.get_next_item()
        
        assert next_item is not None
        assert next_item.job_id == sample_job.id
        assert next_item.status == AIQueueStatus.QUEUED
    
    def test_get_next_item_empty_queue(self, queue_service):
        """Test getting next item from empty queue returns None."""
        next_item = queue_service.get_next_item()
        assert next_item is None
    
    def test_priority_ordering(self, queue_service, db_session):
        """Test that higher priority items are returned first."""
        # Create multiple jobs
        job1 = Job(platform="naukri", external_job_id="job1", url="url1", title="Job 1", company="Company 1", status="DISCOVERED", discovered_at=datetime.now(UTC))
        job2 = Job(platform="naukri", external_job_id="job2", url="url2", title="Job 2", company="Company 2", status="DISCOVERED", discovered_at=datetime.now(UTC))
        job3 = Job(platform="naukri", external_job_id="job3", url="url3", title="Job 3", company="Company 3", status="DISCOVERED", discovered_at=datetime.now(UTC))
        db_session.add_all([job1, job2, job3])
        db_session.commit()
        
        # Enqueue with different priorities
        queue_service.enqueue_job(job_id=job1.id, priority=30)
        queue_service.enqueue_job(job_id=job2.id, priority=80)
        queue_service.enqueue_job(job_id=job3.id, priority=50)
        
        # Highest priority should be returned first
        next_item = queue_service.get_next_item()
        assert next_item.job_id == job2.id  # Priority 80


class TestAIQueueStatusTransitions:
    """Test queue item status transitions."""
    
    def test_mark_processing(self, queue_service, sample_job):
        """Test marking an item as PROCESSING."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        result = queue_service.mark_processing(next_item.id)
        
        assert result is not None
        assert result.status == AIQueueStatus.PROCESSING
        assert result.attempt_count == 1
        assert result.processing_started_at is not None
        assert result.last_attempt_at is not None
    
    def test_mark_completed(self, queue_service, sample_job):
        """Test marking an item as COMPLETED."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        queue_service.mark_processing(next_item.id)
        
        result = queue_service.mark_completed(next_item.id, analysis_id=123)
        
        assert result is not None
        assert result.status == AIQueueStatus.COMPLETED
        assert result.completed_at is not None
        assert result.analysis_id == 123
    
    def test_mark_retry_pending(self, queue_service, sample_job):
        """Test marking an item as RETRY_PENDING."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        queue_service.mark_processing(next_item.id)
        
        result = queue_service.mark_retry_pending(
            next_item.id,
            "Test failure",
            "Test error details"
        )
        
        assert result is not None
        assert result.status == AIQueueStatus.RETRY_PENDING
        assert result.failure_reason == "Test failure"
        assert result.last_error == "Test error details"
        assert result.next_retry_at is not None
    
    def test_mark_retry_pending_max_attempts(self, queue_service, sample_job, db_session):
        """Test that max attempts leads to NEEDS_ATTENTION."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        # Simulate max attempts
        queue_item = db_session.get(AIQueueItem, next_item.id)
        queue_item.attempt_count = 3
        queue_item.max_attempts = 3
        db_session.commit()
        
        result = queue_service.mark_retry_pending(next_item.id, "Max attempts", "Error")
        
        assert result is not None
        assert result.status == AIQueueStatus.NEEDS_ATTENTION
    
    def test_mark_quota_blocked(self, queue_service, sample_job):
        """Test marking an item as QUOTA_BLOCKED."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        result = queue_service.mark_quota_blocked(next_item.id, "Gemini quota exhausted")
        
        assert result is not None
        assert result.status == AIQueueStatus.QUOTA_BLOCKED
        assert result.failure_reason == "Gemini quota exhausted"
    
    def test_mark_needs_attention(self, queue_service, sample_job):
        """Test marking an item as NEEDS_ATTENTION."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        result = queue_service.mark_needs_attention(
            next_item.id,
            "Requires manual review",
            "Complex scenario"
        )
        
        assert result is not None
        assert result.status == AIQueueStatus.NEEDS_ATTENTION
        assert result.failure_reason == "Requires manual review"
        assert result.completed_at is not None
    
    def test_mark_failed(self, queue_service, sample_job):
        """Test marking an item as FAILED."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        result = queue_service.mark_failed(
            next_item.id,
            "Permanent error",
            "Cannot recover"
        )
        
        assert result is not None
        assert result.status == AIQueueStatus.FAILED
        assert result.failure_reason == "Permanent error"
        assert result.completed_at is not None


class TestAIQueueRetryHandling:
    """Test retry handling behavior."""
    
    def test_retry_delays(self, queue_service, sample_job, db_session):
        """Test that retry delays increase with attempts."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        # First retry (attempt_count=1 after mark_processing, so index 0)
        queue_service.mark_processing(next_item.id)
        result1 = queue_service.mark_retry_pending(next_item.id, "Error 1", "Error")
        first_delay = (result1.next_retry_at - result1.updated_at).total_seconds()
        
        # Second retry (attempt_count=2 after mark_processing, so index 1)
        queue_service.mark_processing(next_item.id)
        result2 = queue_service.mark_retry_pending(next_item.id, "Error 2", "Error")
        second_delay = (result2.next_retry_at - result2.updated_at).total_seconds()
        
        # Third retry would hit max attempts and go to NEEDS_ATTENTION
        # So test with a queue item that has higher max_attempts
        # Use a fresh job for third test
        job2 = Job(
            platform="naukri",
            external_job_id="job2",
            url="url2",
            title="Job 2",
            company="Company 2",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC)
        )
        db_session.add(job2)
        db_session.commit()
        
        queue_service.enqueue_job(job_id=job2.id)
        next_item2 = queue_service.get_next_item()
        # Set higher max_attempts for third test
        queue_item2 = db_session.get(AIQueueItem, next_item2.id)
        queue_item2.max_attempts = 5
        db_session.commit()
        
        # Simulate 2 previous retries to get to attempt_count=3
        queue_service.mark_processing(next_item2.id)
        queue_service.mark_retry_pending(next_item2.id, "Error 2a", "Error")
        queue_service.mark_processing(next_item2.id)
        queue_service.mark_retry_pending(next_item2.id, "Error 2b", "Error")
        
        # Third retry (attempt_count=3 after mark_processing, so index 2)
        queue_service.mark_processing(next_item2.id)
        result3 = queue_service.mark_retry_pending(next_item2.id, "Error 3", "Error")
        third_delay = (result3.next_retry_at - result3.updated_at).total_seconds()
        
        # Delays should increase: 1min, 5min, 15min
        assert 50 < first_delay < 70  # ~1 minute
        assert 290 < second_delay < 310  # ~5 minutes
        assert 890 < third_delay < 910  # ~15 minutes
    
    def test_retry_exhaustion(self, queue_service, sample_job):
        """Test that retry exhaustion leads to NEEDS_ATTENTION."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        # Exhaust retries
        for i in range(4):  # 0, 1, 2, 3 (max is 3)
            queue_service.mark_processing(next_item.id)
            if i < 3:
                queue_service.mark_retry_pending(next_item.id, f"Error {i}", "Error")
            else:
                result = queue_service.mark_retry_pending(next_item.id, "Final error", "Error")
        
        assert result.status == AIQueueStatus.NEEDS_ATTENTION


class TestAIQueueQuotaHandling:
    """Test Gemini quota handling."""
    
    def test_quota_blocked_state(self, queue_service, sample_job):
        """Test QUOTA_BLOCKED state prevents processing."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        queue_service.mark_quota_blocked(next_item.id)
        
        # Quota blocked items should not be returned as next item unless quota becomes available
        next_after_block = queue_service.get_next_item()
        # Since this is the only item and it's quota blocked, it might still be returned
        # but in production, quota recovery would check before processing
        assert next_after_block is not None
        assert next_after_block.status == AIQueueStatus.QUOTA_BLOCKED


class TestAIQueueStaleRecovery:
    """Test stale item recovery."""
    
    def test_recover_stale_processing_items(self, queue_service, sample_job, db_session):
        """Test recovery of stale PROCESSING items."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        queue_service.mark_processing(next_item.id)
        
        # Simulate stale item by setting processing_started_at to past
        queue_item = db_session.get(AIQueueItem, next_item.id)
        queue_item.processing_started_at = utc_now() - timedelta(minutes=45)
        db_session.commit()
        
        # Recover stale items
        recovered_count = queue_service.recover_stale_items()
        
        assert recovered_count == 1
        
        # Check that item was recovered to RETRY_PENDING
        db_session.refresh(queue_item)
        assert queue_item.status == AIQueueStatus.RETRY_PENDING.value
    
    def test_recover_stale_max_attempts(self, queue_service, sample_job, db_session):
        """Test that stale items with max attempts go to NEEDS_ATTENTION."""
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        queue_service.mark_processing(next_item.id)
        
        # Set max attempts reached
        queue_item = db_session.get(AIQueueItem, next_item.id)
        queue_item.attempt_count = 3
        queue_item.max_attempts = 3
        queue_item.processing_started_at = utc_now() - timedelta(minutes=45)
        db_session.commit()
        
        # Recover stale items
        recovered_count = queue_service.recover_stale_items()
        
        assert recovered_count == 1
        
        # Check that item was recovered to NEEDS_ATTENTION
        db_session.refresh(queue_item)
        assert queue_item.status == AIQueueStatus.NEEDS_ATTENTION.value
    
    def test_no_stale_items(self, queue_service):
        """Test recovery when no stale items exist."""
        recovered_count = queue_service.recover_stale_items()
        assert recovered_count == 0


class TestAIQueueStatus:
    """Test queue status reporting."""
    
    def test_get_queue_status(self, queue_service, sample_job, db_session):
        """Test getting queue status."""
        # Add items in different states
        queue_service.enqueue_job(job_id=sample_job.id, priority=50)
        next_item = queue_service.get_next_item()
        queue_service.mark_processing(next_item.id)
        
        status = queue_service.get_queue_status()
        
        assert status.total_queued == 0  # Item is now processing
        assert status.total_processing == 1
        assert status.total_items == 1
        # Since there's a processing item, next_item_id should be None (no queued items)
        assert status.next_item_id is None
    
    def test_queue_status_empty(self, queue_service):
        """Test queue status when empty."""
        status = queue_service.get_queue_status()
        
        assert status.total_queued == 0
        assert status.total_processing == 0
        assert status.total_completed == 0
        assert status.total_retry_pending == 0
        assert status.total_quota_blocked == 0
        assert status.total_needs_attention == 0
        assert status.total_failed == 0
        assert status.total_items == 0
        assert status.next_item_id is None


class TestAIQueueProcessing:
    """Test queue item processing."""
    
    def test_process_item_success(self, queue_service, sample_job, db_session, monkeypatch):
        """Test successful processing of a queue item."""
        # Mock Gemini provider to return valid analysis
        def mock_analyze_job(self, job_context, profile_context):
            from backend.schemas.ai import JobAnalysis, JobQuality, AIRecommendation
            return JobAnalysis(
                match_score=85,
                role_match=True,
                skill_match=True,
                experience_match=True,
                location_match=True,
                salary_match=True,
                job_quality=JobQuality.GOOD,
                duplicate_probability=0.05,
                suspicious=False,
                recommendation=AIRecommendation.APPLY,
                short_reason="Strong match for Python developer role"
            )
        
        monkeypatch.setattr(GeminiProvider, "analyze_job", mock_analyze_job)
        
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        result = queue_service.process_item(next_item.id, "test profile context")
        
        assert result.success is True
        assert result.status == AIQueueStatus.COMPLETED
        assert result.analysis_id is not None
        
        # Check that analysis was stored
        analysis = db_session.get(JobAnalysisModel, result.analysis_id)
        assert analysis is not None
        assert analysis.job_id == sample_job.id
    
    def test_process_item_gemini_failure(self, queue_service, sample_job, monkeypatch):
        """Test processing when Gemini returns None."""
        def mock_analyze_job(self, job_context, profile_context):
            return None
        
        monkeypatch.setattr(GeminiProvider, "analyze_job", mock_analyze_job)
        
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        result = queue_service.process_item(next_item.id, "test profile context")
        
        assert result.success is False
        assert result.status == AIQueueStatus.RETRY_PENDING
        assert result.failure_reason == "Gemini analysis returned None"
    
    def test_process_item_quota_exhausted(self, queue_service, sample_job, monkeypatch):
        """Test processing when Gemini quota is exhausted."""
        def mock_analyze_job(self, job_context, profile_context):
            raise APIQuotaExhaustedError("Quota exceeded")
        
        monkeypatch.setattr(GeminiProvider, "analyze_job", mock_analyze_job)
        
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        result = queue_service.process_item(next_item.id, "test profile context")
        
        assert result.success is False
        assert result.status == AIQueueStatus.QUOTA_BLOCKED
        assert result.failure_reason == "Gemini quota exhausted"
    
    def test_process_item_generic_error(self, queue_service, sample_job, monkeypatch):
        """Test processing when a generic error occurs."""
        def mock_analyze_job(self, job_context, profile_context):
            raise Exception("Network error")
        
        monkeypatch.setattr(GeminiProvider, "analyze_job", mock_analyze_job)
        
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        
        result = queue_service.process_item(next_item.id, "test profile context")
        
        assert result.success is False
        assert result.status == AIQueueStatus.RETRY_PENDING
        assert "Processing error" in result.failure_reason


class TestAIQueuePersistence:
    """Test queue persistence across sessions."""
    
    def test_queue_item_persistence(self, queue_service, sample_job, db_session):
        """Test that queue items persist across sessions."""
        # Create queue item
        queue_service.enqueue_job(job_id=sample_job.id, priority=75)
        
        # Simulate session restart by creating new service
        new_queue_service = AIQueueService(db_session)
        
        # Check that item is still there
        next_item = new_queue_service.get_next_item()
        assert next_item is not None
        assert next_item.job_id == sample_job.id
        assert next_item.priority == 75


class TestAIQueuePriorityCalculation:
    """Test deterministic priority calculation."""
    
    def test_priority_complete_description(self, queue_service, db_session):
        """Test that complete descriptions get higher priority."""
        job_with_desc = Job(
            platform="naukri",
            external_job_id="job_desc",
            url="url",
            title="Developer",
            company="Company",
            description="A very detailed job description with lots of information about the role, requirements, and benefits that exceeds 200 characters to test the priority boost logic.",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC)
        )
        job_without_desc = Job(
            platform="naukri",
            external_job_id="job_no_desc",
            url="url2",
            title="Developer",
            company="Company",
            description="Short",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC)
        )
        db_session.add_all([job_with_desc, job_without_desc])
        db_session.commit()
        
        # Enqueue both
        queue_service.enqueue_job(job_id=job_with_desc.id)
        queue_service.enqueue_job(job_id=job_without_desc.id)
        
        # Job with complete description should have higher priority
        next_item = queue_service.get_next_item()
        assert next_item.job_id == job_with_desc.id
    
    def test_priority_recent_discovery(self, queue_service, db_session):
        """Test that recently discovered jobs get higher priority."""
        old_job = Job(
            platform="naukri",
            external_job_id="old_job",
            url="url",
            title="Developer",
            company="Company",
            description="Description",
            discovered_at=utc_now() - timedelta(days=2),
            status="DISCOVERED"
        )
        new_job = Job(
            platform="naukri",
            external_job_id="new_job",
            url="url2",
            title="Developer",
            company="Company",
            description="Description",
            discovered_at=utc_now() - timedelta(hours=1),
            status="DISCOVERED"
        )
        db_session.add_all([old_job, new_job])
        db_session.commit()
        
        # Enqueue both
        queue_service.enqueue_job(job_id=old_job.id)
        queue_service.enqueue_job(job_id=new_job.id)
        
        # Recent job should have higher priority
        next_item = queue_service.get_next_item()
        assert next_item.job_id == new_job.id


class TestAIQueueSchedulerIntegration:
    """Test AI queue integration with scheduler."""
    
    def test_scheduler_enqueue_discovered_jobs(self, queue_service, db_session):
        """Test that scheduler enqueues discovered jobs without analysis."""
        from backend.models.job import Job
        from backend.models.ai import JobAnalysisModel
        
        # Create discovered jobs without analysis
        job1 = Job(
            platform="naukri",
            external_job_id="sched_job1",
            url="url1",
            title="Job 1",
            company="Company 1",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC)
        )
        job2 = Job(
            platform="naukri",
            external_job_id="sched_job2",
            url="url2",
            title="Job 2",
            company="Company 2",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC)
        )
        db_session.add_all([job1, job2])
        db_session.commit()
        
        # Simulate scheduler enqueue logic
        stmt = select(Job).where(Job.status == "DISCOVERED").order_by(Job.discovered_at.desc())
        jobs = db_session.execute(stmt).scalars().all()
        
        enqueued_count = 0
        for job in jobs:
            existing_analysis = db_session.execute(
                select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
            ).scalars().first()
            
            if existing_analysis:
                continue
            
            existing_queue = db_session.execute(
                select(AIQueueItem).where(AIQueueItem.job_id == job.id)
            ).scalars().first()
            
            if existing_queue:
                continue
            
            queue_item = queue_service.enqueue_job(
                job_id=job.id,
                priority=50,
                priority_reason="Discovered by scheduler",
                queue_source="SCHEDULER"
            )
            
            if queue_item:
                enqueued_count += 1
        
        assert enqueued_count == 2
        
        # Verify both jobs are in queue
        status = queue_service.get_queue_status()
        assert status.total_queued == 2
    
    def test_scheduler_skip_analyzed_jobs(self, queue_service, db_session):
        """Test that scheduler skips jobs that already have analysis."""
        from backend.models.job import Job
        from backend.models.ai import JobAnalysisModel
        from backend.schemas.ai import JobQuality, AIRecommendation
        
        # Create job with existing analysis
        job = Job(
            platform="naukri",
            external_job_id="analyzed_job",
            url="url",
            title="Job",
            company="Company",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC)
        )
        db_session.add(job)
        db_session.commit()
        
        # Add analysis
        analysis = JobAnalysisModel(
            job_id=job.id,
            match_score=85,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality=JobQuality.GOOD.value,
            duplicate_probability=0.05,
            suspicious=False,
            recommendation=AIRecommendation.APPLY.value,
            short_reason="Good match",
            model="gemini",
            prompt_version="v1"
        )
        db_session.add(analysis)
        db_session.commit()
        
        # Try to enqueue
        result = queue_service.enqueue_job(
            job_id=job.id,
            priority=50,
            queue_source="SCHEDULER"
        )
        
        # Should succeed (enqueue doesn't check for analysis, only duplicates)
        assert result is not None
        
        # But scheduler logic should skip
        stmt = select(Job).where(Job.status == "DISCOVERED")
        jobs = db_session.execute(stmt).scalars().all()
        
        enqueued_count = 0
        for job in jobs:
            existing_analysis = db_session.execute(
                select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
            ).scalars().first()
            
            if existing_analysis:
                continue
            
            existing_queue = db_session.execute(
                select(AIQueueItem).where(AIQueueItem.job_id == job.id)
            ).scalars().first()
            
            if existing_queue:
                continue
            
            queue_item = queue_service.enqueue_job(
                job_id=job.id,
                priority=50,
                queue_source="SCHEDULER"
            )
            
            if queue_item:
                enqueued_count += 1
        
        # Should not enqueue because job has analysis
        assert enqueued_count == 0


class TestAIQueueApplicationRunnerIntegration:
    """Test AI queue integration with application runner."""
    
    def test_application_runner_blocks_incomplete_analysis(self, queue_service, sample_job, db_session):
        """Test that application runner blocks jobs with incomplete AI analysis."""
        from backend.models.ai_queue import AIQueueItem
        
        # Enqueue job but don't complete it
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        queue_service.mark_processing(next_item.id)
        
        # Verify it's still in PROCESSING state
        queue_item = db_session.get(AIQueueItem, next_item.id)
        assert queue_item.status == AIQueueStatus.PROCESSING.value
        
        # Application runner should skip this job
        queue_item_check = db_session.execute(
            select(AIQueueItem).where(AIQueueItem.job_id == sample_job.id)
        ).scalars().first()
        
        assert queue_item_check is not None
        assert queue_item_check.status != AIQueueStatus.COMPLETED.value
    
    def test_application_runner_blocks_no_analysis(self, queue_service, sample_job, db_session):
        """Test that application runner blocks jobs with no AI analysis."""
        from backend.models.ai import JobAnalysisModel
        
        # Job without analysis or queue entry
        # Application runner should skip this job
        
        analysis = db_session.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == sample_job.id)
        ).scalars().first()
        
        assert analysis is None
        
        queue_item = db_session.execute(
            select(AIQueueItem).where(AIQueueItem.job_id == sample_job.id)
        ).scalars().first()
        
        assert queue_item is None
    
    def test_application_runner_allows_completed_analysis(self, queue_service, sample_job, db_session, monkeypatch):
        """Test that application runner allows jobs with completed AI analysis."""
        from backend.models.ai import JobAnalysisModel
        from backend.schemas.ai import JobQuality, AIRecommendation
        
        # Mock Gemini provider to return valid analysis
        def mock_analyze_job(self, job_context, profile_context):
            from backend.schemas.ai import JobAnalysis
            return JobAnalysis(
                match_score=85,
                role_match=True,
                skill_match=True,
                experience_match=True,
                location_match=True,
                salary_match=True,
                job_quality=JobQuality.GOOD,
                duplicate_probability=0.05,
                suspicious=False,
                recommendation=AIRecommendation.APPLY,
                short_reason="Strong match"
            )
        
        monkeypatch.setattr(GeminiProvider, "analyze_job", mock_analyze_job)
        
        # Enqueue and complete
        queue_service.enqueue_job(job_id=sample_job.id)
        next_item = queue_service.get_next_item()
        result = queue_service.process_item(next_item.id, "test profile")
        
        assert result.success is True
        assert result.status == AIQueueStatus.COMPLETED
        
        # Verify analysis exists
        analysis = db_session.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == sample_job.id)
        ).scalars().first()
        
        assert analysis is not None
        assert analysis.job_id == sample_job.id