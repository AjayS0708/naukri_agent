import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models.job import Job
from backend.models.application import Application
from backend.models.ai import AIUsage, JobAnalysisModel
from backend.models.discovery import DiscoveryRun
from backend.models.feedback import DecisionQualityRecord, JobFeedback
from backend.database.database import Base
from backend.services.analytics.service import AnalyticsService


@pytest.fixture
def db_session():
    """Create a test database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    yield session
    session.close()


@pytest.fixture
def sample_job(db_session: Session):
    """Create a sample job for testing."""
    job = Job(
        platform="naukri",
        external_job_id="test123",
        url="https://naukri.com/job/test123",
        title="Software Engineer",
        company="Test Company",
        description="Looking for a software engineer.",
        location="Bengaluru",
        posted_at=datetime.now(UTC) - timedelta(days=5),
        status="DISCOVERED"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def sample_application(db_session: Session, sample_job: Job):
    """Create a sample application for testing."""
    application = Application(
        job_id=sample_job.id,
        status="APPLIED",
        application_method="NAUKRI_NATIVE",
        started_at=datetime.now(UTC) - timedelta(days=3),
        applied_at=datetime.now(UTC) - timedelta(days=3)
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


@pytest.fixture
def sample_data(db_session: Session):
    """Create comprehensive sample data for analytics testing."""
    # Create multiple jobs
    jobs = []
    for i in range(5):
        job = Job(
            platform="naukri",
            external_job_id=f"test{i}",
            url=f"https://naukri.com/job/test{i}",
            title=f"Software Engineer {i}",
            company=f"Company {i}",
            description="Looking for a software engineer.",
            location="Bengaluru",
            posted_at=datetime.now(UTC) - timedelta(days=i),
            status="DISCOVERED"
        )
        jobs.append(job)
        db_session.add(job)
    db_session.commit()
    
    for job in jobs:
        db_session.refresh(job)
    
    # Create applications with different statuses
    applications = []
    for i, job in enumerate(jobs):
        status = "APPLIED" if i < 2 else ("SKIPPED" if i < 4 else "NEEDS_ATTENTION")
        application = Application(
            job_id=job.id,
            status=status,
            application_method="NAUKRI_NATIVE",
            started_at=datetime.now(UTC) - timedelta(days=i),
            applied_at=datetime.now(UTC) - timedelta(days=i) if status == "APPLIED" else None,
            skip_reason="Location mismatch" if status == "SKIPPED" else None
        )
        applications.append(application)
        db_session.add(application)
    db_session.commit()
    
    # Create AI usage records
    ai_usage = AIUsage(
        operation="JOB_ANALYSIS",
        model="gemini-1.5-flash",
        status="SUCCESS",
        tokens_used=150
    )
    db_session.add(ai_usage)
    
    # Create job analysis
    job_analysis = JobAnalysisModel(
        job_id=jobs[0].id,
        match_score=85,
        role_match=True,
        skill_match=True,
        experience_match=True,
        location_match=True,
        salary_match=True,
        job_quality="GOOD",
        duplicate_probability=0.02,
        suspicious=False,
        recommendation="APPLY",
        short_reason="Strong match",
        model="gemini-1.5-flash",
        prompt_version="v1.0"
    )
    db_session.add(job_analysis)
    
    # Create discovery run
    discovery_run = DiscoveryRun(
        status="COMPLETED",
        jobs_discovered=5,
        new_jobs=5,
        duplicate_jobs=0,
        pages_processed=1,
        searches_attempted=1
    )
    db_session.add(discovery_run)
    
    # Create decision quality records
    for i, job in enumerate(jobs):
        priority = "HIGH_PRIORITY" if i < 2 else ("NORMAL_PRIORITY" if i < 4 else "LOW_PRIORITY")
        decision_record = DecisionQualityRecord(
            job_id=job.id,
            priority=priority,
            decision_score=90 - i * 10,
            role_relevance_score=100,
            skill_relevance_score=90,
            experience_compatibility_score=80,
            location_match_score=100,
            salary_suitability_score=85,
            job_quality_score=90,
            freshness_score=100 - i * 10,
            duplicate_probability=0,
            suspicious_probability=0,
            feedback_adjustment=0,
            primary_reason_code="STRONG_MATCH",
            reason_codes='["STRONG_MATCH"]',
            explanation="Strong match",
            hard_filter_failed=0,
            requires_ai_analysis=0,
            ai_available=1
        )
        db_session.add(decision_record)
    
    db_session.commit()
    
    return {
        "jobs": jobs,
        "applications": applications,
        "ai_usage": ai_usage,
        "job_analysis": job_analysis,
        "discovery_run": discovery_run
    }


class TestAnalyticsService:
    """Test analytics service."""
    
    def test_get_analytics_summary(
        self,
        db_session: Session,
        sample_data
    ):
        """Test getting analytics summary."""
        service = AnalyticsService(db_session)
        
        summary = service.get_analytics_summary(days=30)
        
        assert summary["period_days"] == 30
        assert summary["discovered_jobs"] >= 5
        assert summary["total_applications"] >= 5
        assert summary["successful_applications"] >= 2
        assert summary["skipped_applications"] >= 2
        assert summary["needs_attention"] >= 1
        assert summary["ai_requests"] >= 1
        assert summary["ai_analyses"] >= 1
        assert summary["discovery_runs"] >= 1
        assert 0 <= summary["success_rate"] <= 100
    
    def test_get_analytics_summary_empty(
        self,
        db_session: Session
    ):
        """Test getting analytics summary with no data."""
        service = AnalyticsService(db_session)
        
        summary = service.get_analytics_summary(days=30)
        
        assert summary["period_days"] == 30
        assert summary["discovered_jobs"] == 0
        assert summary["total_applications"] == 0
        assert summary["successful_applications"] == 0
        assert summary["success_rate"] == 0.0
    
    def test_get_skip_reasons(
        self,
        db_session: Session,
        sample_data
    ):
        """Test getting top skip reasons."""
        service = AnalyticsService(db_session)
        
        skip_reasons = service.get_skip_reasons(days=30, limit=10)
        
        assert isinstance(skip_reasons, list)
        assert len(skip_reasons) > 0
        assert "reason" in skip_reasons[0]
        assert "count" in skip_reasons[0]
        assert skip_reasons[0]["count"] > 0
    
    def test_get_skip_reasons_empty(
        self,
        db_session: Session
    ):
        """Test getting skip reasons with no data."""
        service = AnalyticsService(db_session)
        
        skip_reasons = service.get_skip_reasons(days=30, limit=10)
        
        assert isinstance(skip_reasons, list)
        assert len(skip_reasons) == 0
    
    def test_get_decision_breakdown(
        self,
        db_session: Session,
        sample_data
    ):
        """Test getting decision breakdown."""
        service = AnalyticsService(db_session)
        
        breakdown = service.get_decision_breakdown(days=30)
        
        assert "breakdown" in breakdown
        assert "total" in breakdown
        assert "percentages" in breakdown
        assert breakdown["total"] >= 5
        assert "HIGH_PRIORITY" in breakdown["breakdown"]
        assert "NORMAL_PRIORITY" in breakdown["breakdown"]
        assert "LOW_PRIORITY" in breakdown["breakdown"]
        
        # Verify percentages sum to approximately 100
        total_percentage = sum(breakdown["percentages"].values())
        assert 95 <= total_percentage <= 105  # Allow for rounding
    
    def test_get_decision_breakdown_empty(
        self,
        db_session: Session
    ):
        """Test getting decision breakdown with no data."""
        service = AnalyticsService(db_session)
        
        breakdown = service.get_decision_breakdown(days=30)
        
        assert breakdown["total"] == 0
        assert sum(breakdown["breakdown"].values()) == 0
    
    def test_get_applications_by_day(
        self,
        db_session: Session,
        sample_data
    ):
        """Test getting application counts by day."""
        service = AnalyticsService(db_session)
        
        by_day = service.get_applications_by_day(days=30)
        
        assert isinstance(by_day, list)
        assert len(by_day) > 0
        assert "date" in by_day[0]
        assert "count" in by_day[0]
    
    def test_get_applications_by_day_empty(
        self,
        db_session: Session
    ):
        """Test getting applications by day with no data."""
        service = AnalyticsService(db_session)
        
        by_day = service.get_applications_by_day(days=30)
        
        assert isinstance(by_day, list)
        assert len(by_day) == 0
    
    def test_get_applications_by_job_profile(
        self,
        db_session: Session,
        sample_data
    ):
        """Test getting application breakdown by job title."""
        service = AnalyticsService(db_session)
        
        by_profile = service.get_applications_by_job_profile(days=30)
        
        assert isinstance(by_profile, list)
        assert len(by_profile) > 0
        assert "job_title" in by_profile[0]
        assert "count" in by_profile[0]
        assert by_profile[0]["count"] > 0
    
    def test_get_applications_by_job_profile_empty(
        self,
        db_session: Session
    ):
        """Test getting applications by job profile with no data."""
        service = AnalyticsService(db_session)
        
        by_profile = service.get_applications_by_job_profile(days=30)
        
        assert isinstance(by_profile, list)
        assert len(by_profile) == 0
    
    def test_get_primary_reason_codes(
        self,
        db_session: Session,
        sample_data
    ):
        """Test getting top primary reason codes."""
        service = AnalyticsService(db_session)
        
        reason_codes = service.get_primary_reason_codes(days=30, limit=10)
        
        assert isinstance(reason_codes, list)
        assert len(reason_codes) > 0
        assert "reason_code" in reason_codes[0]
        assert "count" in reason_codes[0]
        assert reason_codes[0]["count"] > 0
    
    def test_get_primary_reason_codes_empty(
        self,
        db_session: Session
    ):
        """Test getting primary reason codes with no data."""
        service = AnalyticsService(db_session)
        
        reason_codes = service.get_primary_reason_codes(days=30, limit=10)
        
        assert isinstance(reason_codes, list)
        assert len(reason_codes) == 0
    
    def test_get_feedback_summary(
        self,
        db_session: Session
    ):
        """Test getting feedback summary."""
        service = AnalyticsService(db_session)
        
        # Create some feedback
        job = Job(
            platform="naukri",
            external_job_id="feedback_test",
            url="https://naukri.com/job/feedback_test",
            title="Software Engineer",
            company="Test Company",
            description="Looking for a software engineer.",
            location="Bengaluru",
            status="DISCOVERED"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        
        feedback1 = JobFeedback(
            job_id=job.id,
            feedback_type="RELEVANT"
        )
        db_session.add(feedback1)
        
        feedback2 = JobFeedback(
            job_id=job.id,
            feedback_type="NOT_RELEVANT"
        )
        db_session.add(feedback2)
        
        db_session.commit()
        
        summary = service.get_feedback_summary(days=30)
        
        assert summary["total_feedback"] >= 2
        assert summary["relevant_count"] >= 1
        assert summary["not_relevant_count"] >= 1
        assert 0 <= summary["relevance_rate"] <= 1
    
    def test_get_feedback_summary_empty(
        self,
        db_session: Session
    ):
        """Test getting feedback summary with no data."""
        service = AnalyticsService(db_session)
        
        summary = service.get_feedback_summary(days=30)
        
        assert summary["total_feedback"] == 0
        assert summary["relevance_rate"] == 0.0
    
    def test_get_recent_decision_activity(
        self,
        db_session: Session,
        sample_data
    ):
        """Test getting recent decision activity."""
        service = AnalyticsService(db_session)
        
        recent = service.get_recent_decision_activity(limit=10)
        
        assert isinstance(recent, list)
        assert len(recent) > 0
        assert "job_id" in recent[0]
        assert "priority" in recent[0]
        assert "decision_score" in recent[0]
        assert "primary_reason_code" in recent[0]
        assert "explanation" in recent[0]
        assert "created_at" in recent[0]
    
    def test_get_recent_decision_activity_empty(
        self,
        db_session: Session
    ):
        """Test getting recent decision activity with no data."""
        service = AnalyticsService(db_session)
        
        recent = service.get_recent_decision_activity(limit=10)
        
        assert isinstance(recent, list)
        assert len(recent) == 0
    
    def test_analytics_respects_time_period(
        self,
        db_session: Session,
        sample_data
    ):
        """Test that analytics respects the time period parameter."""
        service = AnalyticsService(db_session)
        
        # Get summary for different time periods
        summary_7_days = service.get_analytics_summary(days=7)
        summary_30_days = service.get_analytics_summary(days=30)
        summary_90_days = service.get_analytics_summary(days=90)
        
        # Longer periods should include more or equal data
        assert summary_30_days["discovered_jobs"] >= summary_7_days["discovered_jobs"]
        assert summary_90_days["discovered_jobs"] >= summary_30_days["discovered_jobs"]
    
    def test_analytics_limit_parameters(
        self,
        db_session: Session,
        sample_data
    ):
        """Test that limit parameters work correctly."""
        service = AnalyticsService(db_session)
        
        # Test with different limits
        skip_reasons_5 = service.get_skip_reasons(days=30, limit=5)
        skip_reasons_10 = service.get_skip_reasons(days=30, limit=10)
        
        assert len(skip_reasons_5) <= 5
        assert len(skip_reasons_10) <= 10
        assert len(skip_reasons_10) >= len(skip_reasons_5)
