import pytest
from datetime import UTC, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models.job import Job
from backend.models.feedback import JobFeedback
from backend.database.database import Base
from backend.services.learning.service import FeedbackService
from backend.schemas.feedback import FeedbackCreate, FeedbackType


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
        status="DISCOVERED"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


class TestFeedbackService:
    """Test feedback service."""
    
    def test_submit_feedback(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test submitting feedback for a job."""
        service = FeedbackService(db_session)
        
        feedback = FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.RELEVANT,
            comments="This job is highly relevant"
        )
        
        result = service.submit_feedback(feedback)
        
        assert result.id is not None
        assert result.job_id == sample_job.id
        assert result.feedback_type == FeedbackType.RELEVANT
        assert result.comments == "This job is highly relevant"
        assert result.created_at is not None
    
    def test_submit_feedback_without_comments(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test submitting feedback without comments."""
        service = FeedbackService(db_session)
        
        feedback = FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.NOT_RELEVANT
        )
        
        result = service.submit_feedback(feedback)
        
        assert result.id is not None
        assert result.comments is None
    
    def test_get_feedback_for_job(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test retrieving feedback for a job."""
        service = FeedbackService(db_session)
        
        # Submit multiple feedback entries
        feedback1 = FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.RELEVANT,
            comments="Good match"
        )
        service.submit_feedback(feedback1)
        
        feedback2 = FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.GOOD_MATCH,
            comments="Excellent opportunity"
        )
        service.submit_feedback(feedback2)
        
        # Retrieve feedback
        feedbacks = service.get_feedback_for_job(sample_job.id)
        
        assert len(feedbacks) == 2
        assert feedbacks[0].job_id == sample_job.id
        assert feedbacks[1].job_id == sample_job.id
    
    def test_get_feedback_for_job_empty(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test retrieving feedback for a job with no feedback."""
        service = FeedbackService(db_session)
        
        feedbacks = service.get_feedback_for_job(sample_job.id)
        
        assert len(feedbacks) == 0
    
    def test_get_feedback_summary(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test getting feedback summary."""
        service = FeedbackService(db_session)
        
        # Submit various feedback types
        service.submit_feedback(FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.RELEVANT
        ))
        service.submit_feedback(FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.RELEVANT
        ))
        service.submit_feedback(FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.NOT_RELEVANT
        ))
        service.submit_feedback(FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.GOOD_MATCH
        ))
        
        summary = service.get_feedback_summary()
        
        assert summary.total_feedback == 4
        assert summary.relevant_count == 2
        assert summary.not_relevant_count == 1
        assert summary.good_match_count == 1
        assert summary.relevance_rate == 0.5  # 2/4
    
    def test_get_feedback_summary_for_specific_job(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test getting feedback summary for a specific job."""
        service = FeedbackService(db_session)
        
        # Create another job
        job2 = Job(
            platform="naukri",
            external_job_id="test456",
            url="https://naukri.com/job/test456",
            title="Data Analyst",
            company="Another Company",
            description="Looking for a data analyst.",
            location="Remote",
            status="DISCOVERED"
        )
        db_session.add(job2)
        db_session.commit()
        db_session.refresh(job2)
        
        # Submit feedback for both jobs
        service.submit_feedback(FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.RELEVANT
        ))
        service.submit_feedback(FeedbackCreate(
            job_id=job2.id,
            feedback_type=FeedbackType.NOT_RELEVANT
        ))
        
        # Summary for specific job
        summary_job1 = service.get_feedback_summary(job_id=sample_job.id)
        assert summary_job1.total_feedback == 1
        assert summary_job1.relevant_count == 1
        
        # Summary for other job
        summary_job2 = service.get_feedback_summary(job_id=job2.id)
        assert summary_job2.total_feedback == 1
        assert summary_job2.not_relevant_count == 1
    
    def test_get_feedback_summary_empty(
        self,
        db_session: Session
    ):
        """Test getting feedback summary when no feedback exists."""
        service = FeedbackService(db_session)
        
        summary = service.get_feedback_summary()
        
        assert summary.total_feedback == 0
        assert summary.relevant_count == 0
        assert summary.not_relevant_count == 0
        assert summary.relevance_rate == 0.0
    
    def test_delete_feedback(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test deleting feedback."""
        service = FeedbackService(db_session)
        
        # Submit feedback
        feedback = FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.RELEVANT
        )
        result = service.submit_feedback(feedback)
        
        # Delete feedback
        success = service.delete_feedback(result.id)
        
        assert success is True
        
        # Verify deletion
        feedbacks = service.get_feedback_for_job(sample_job.id)
        assert len(feedbacks) == 0
    
    def test_delete_nonexistent_feedback(
        self,
        db_session: Session
    ):
        """Test deleting non-existent feedback."""
        service = FeedbackService(db_session)
        
        success = service.delete_feedback(99999)
        
        assert success is False
    
    def test_feedback_types(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test different feedback types."""
        service = FeedbackService(db_session)
        
        feedback_types = [
            FeedbackType.RELEVANT,
            FeedbackType.NOT_RELEVANT,
            FeedbackType.APPLIED,
            FeedbackType.SKIPPED,
            FeedbackType.INCORRECT_MATCH,
            FeedbackType.GOOD_MATCH,
            FeedbackType.TOO_SENIOR,
            FeedbackType.TOO_JUNIOR,
            FeedbackType.WRONG_LOCATION,
            FeedbackType.SALARY_TOO_LOW
        ]
        
        for feedback_type in feedback_types:
            feedback = FeedbackCreate(
                job_id=sample_job.id,
                feedback_type=feedback_type
            )
            result = service.submit_feedback(feedback)
            assert result.feedback_type == feedback_type
    
    def test_feedback_influence_on_prioritization(
        self,
        db_session: Session,
        sample_job: Job
    ):
        """Test that feedback can influence prioritization (via decision service)."""
        from backend.services.decision.quality import DecisionQualityService
        from backend.models.profile import Profile, Resume
        from backend.models.matching import JobPreference
        
        # Create resume first
        resume = Resume(
            stored_filename="test_resume3.pdf",
            original_filename="test_resume3.pdf",
            sha256="ghi789" * 16,
            file_size=1024,
            text_length=500,
            is_current=True
        )
        db_session.add(resume)
        db_session.commit()
        db_session.refresh(resume)
        
        # Create profile and preference
        profile = Profile(
            resume_id=resume.id,
            status="CONFIRMED",
            confirmed=True,
            data={
                "name": "Test User",
                "experience": [{"title": "Software Engineer", "company": "Test Company"}],
                "skills": ["Python", "JavaScript"]
            }
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)
        
        preference = JobPreference(
            locations=["Bengaluru"],
            job_titles=["Software Engineer"],
            min_salary_lpa=4.0
        )
        db_session.add(preference)
        db_session.commit()
        db_session.refresh(preference)
        
        decision_service = DecisionQualityService(db_session)
        feedback_service = FeedbackService(db_session)
        
        # Get initial decision
        initial_decision = decision_service.evaluate_job_decision(
            sample_job, profile, preference
        )
        initial_adjustment = initial_decision.feedback_adjustment
        
        # Submit positive feedback
        feedback_service.submit_feedback(FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.RELEVANT
        ))
        
        # Get decision after feedback
        updated_decision = decision_service.evaluate_job_decision(
            sample_job, profile, preference
        )
        
        # Feedback should have influenced the adjustment
        assert updated_decision.feedback_adjustment > initial_adjustment
        
        # Submit negative feedback
        feedback_service.submit_feedback(FeedbackCreate(
            job_id=sample_job.id,
            feedback_type=FeedbackType.NOT_RELEVANT
        ))
        
        # Get decision after negative feedback
        final_decision = decision_service.evaluate_job_decision(
            sample_job, profile, preference
        )
        
        # Negative feedback should reduce the adjustment
        assert final_decision.feedback_adjustment < updated_decision.feedback_adjustment
