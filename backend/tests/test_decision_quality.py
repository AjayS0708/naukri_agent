import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.models.feedback import DecisionQualityRecord
from backend.database.database import Base
from backend.services.decision.quality import DecisionQualityService
from backend.schemas.decision import (
    DecisionPriority, DecisionReasonCode, DecisionQuality
)


@pytest.fixture
def db_session():
    """Create a test database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(bind=engine)
    yield session
    session.close()


@pytest.fixture
def confirmed_profile(db_session: Session):
    """Create a confirmed profile for testing."""
    from backend.models.profile import Resume
    
    # Create a resume first (required by Profile model)
    resume = Resume(
        stored_filename="test_resume.pdf",
        original_filename="test_resume.pdf",
        sha256="abc123" * 16,  # 64 character hash
        file_size=1024,
        text_length=500,
        is_current=True
    )
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)
    
    # Create profile with resume_id
    profile = Profile(
        resume_id=resume.id,
        status="CONFIRMED",
        confirmed=True,
        data={
            "name": "Test User",
            "experience": [
                {
                    "title": "Software Engineer",
                    "company": "Test Company",
                    "start_date": "2020-01-01",
                    "end_date": "2023-01-01",
                    "responsibilities": ["Test responsibility"],
                    "technologies": ["Python", "JavaScript"]
                }
            ],
            "skills": ["Python", "JavaScript", "SQL"],
            "education": [
                {
                    "degree": "Bachelor of Computer Science",
                    "institution": "Test University",
                    "graduation_year": 2020
                }
            ],
            "location": "Bengaluru"
        }
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def job_preference(db_session: Session):
    """Create job preferences for testing."""
    preference = JobPreference(
        locations=["Bengaluru", "Remote"],
        job_titles=["Software Engineer", "Data Analyst"],
        employment_types=["Full-time", "Contract"],
        min_salary_lpa=4.0,
        aggressiveness="BALANCED",
        max_daily_applications=20,
        max_hourly_applications=4
    )
    db_session.add(preference)
    db_session.commit()
    db_session.refresh(preference)
    return preference


@pytest.fixture
def sample_job(db_session: Session):
    """Create a sample job for testing."""
    job = Job(
        platform="naukri",
        external_job_id="test123",
        url="https://naukri.com/job/test123",
        title="Software Engineer",
        company="Test Company",
        description="Looking for a software engineer with Python and JavaScript experience.",
        location="Bengaluru",
        salary="5-8 LPA",
        salary_min=5.0,
        salary_max=8.0,
        experience="2-4 years",
        experience_min=2.0,
        experience_max=4.0,
        employment_type="Full-time",
        posted_at=datetime.now(UTC) - timedelta(days=1),
        status="DISCOVERED"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def sample_job_analysis(db_session: Session, sample_job: Job):
    """Create a sample job analysis for testing."""
    analysis = JobAnalysisModel(
        job_id=sample_job.id,
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
        short_reason="Strong match for Python and JavaScript experience.",
        model="gemini-1.5-flash",
        prompt_version="v1.0"
    )
    db_session.add(analysis)
    db_session.commit()
    db_session.refresh(analysis)
    return analysis


class TestDecisionQualityService:
    """Test decision quality service."""
    
    def test_evaluate_job_strong_match(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_job: Job,
        sample_job_analysis: JobAnalysisModel
    ):
        """Test evaluation of a strong matching job."""
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(
            sample_job, confirmed_profile, job_preference, sample_job_analysis
        )
        
        assert decision.priority in [DecisionPriority.HIGH_PRIORITY, DecisionPriority.NORMAL_PRIORITY]
        assert decision.decision_score > 60
        assert decision.hard_filter_failed is False
        assert DecisionReasonCode.STRONG_MATCH in decision.reason_codes or decision.decision_score > 70
        assert "Strong title and skill match" in decision.explanation or "Good match" in decision.explanation
    
    def test_evaluate_job_location_mismatch(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference
    ):
        """Test evaluation of job with location mismatch."""
        job = Job(
            platform="naukri",
            external_job_id="test456",
            url="https://naukri.com/job/test456",
            title="Software Engineer",
            company="Test Company",
            description="Looking for a software engineer.",
            location="Hyderabad",  # Not in allowed locations
            salary="5-8 LPA",
            employment_type="Full-time",
            status="DISCOVERED"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(job, confirmed_profile, job_preference)
        
        assert decision.priority == DecisionPriority.HARD_REJECT
        assert decision.hard_filter_failed is True
        assert DecisionReasonCode.LOCATION_MISMATCH in decision.reason_codes
        assert "Location mismatch" in decision.explanation
    
    def test_evaluate_job_experience_too_high(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference
    ):
        """Test evaluation of job with too high experience requirement."""
        job = Job(
            platform="naukri",
            external_job_id="test789",
            url="https://naukri.com/job/test789",
            title="Senior Software Engineer",
            company="Test Company",
            description="Looking for a senior software engineer.",
            location="Bengaluru",
            salary="10-15 LPA",
            experience="8-10 years",  # Too high for 3 years experience
            employment_type="Full-time",
            status="DISCOVERED"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(job, confirmed_profile, job_preference)
        
        assert decision.priority == DecisionPriority.HARD_REJECT
        assert decision.hard_filter_failed is True
        assert DecisionReasonCode.EXPERIENCE_TOO_HIGH in decision.reason_codes
        assert "Experience" in decision.explanation
    
    def test_evaluate_job_salary_below_minimum(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference
    ):
        """Test evaluation of job with salary below minimum."""
        job = Job(
            platform="naukri",
            external_job_id="test101",
            url="https://naukri.com/job/test101",
            title="Software Engineer",
            company="Test Company",
            description="Looking for a software engineer.",
            location="Bengaluru",
            salary="2-3 LPA",  # Below 4 LPA minimum
            employment_type="Full-time",
            status="DISCOVERED"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(job, confirmed_profile, job_preference)
        
        assert decision.priority == DecisionPriority.HARD_REJECT
        assert decision.hard_filter_failed is True
        assert DecisionReasonCode.SALARY_BELOW_MINIMUM in decision.reason_codes
        assert "Salary" in decision.explanation
    
    def test_evaluate_job_profile_not_confirmed(
        self,
        db_session: Session,
        job_preference: JobPreference,
        sample_job: Job
    ):
        """Test evaluation when profile is not confirmed."""
        from backend.models.profile import Resume
        
        # Create a resume first
        resume = Resume(
            stored_filename="test_resume2.pdf",
            original_filename="test_resume2.pdf",
            sha256="def456" * 16,
            file_size=1024,
            text_length=500,
            is_current=True
        )
        db_session.add(resume)
        db_session.commit()
        db_session.refresh(resume)
        
        profile = Profile(
            resume_id=resume.id,
            status="REVIEW_REQUIRED",
            confirmed=False,
            data={"name": "Test User"}
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)
        
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(sample_job, profile, job_preference)
        
        assert decision.priority == DecisionPriority.HARD_REJECT
        assert decision.hard_filter_failed is True
        assert DecisionReasonCode.PROFILE_NOT_CONFIRMED in decision.reason_codes
        assert "Profile is not confirmed" in decision.explanation
    
    def test_evaluate_job_suspicious(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_job: Job
    ):
        """Test evaluation of suspicious job."""
        analysis = JobAnalysisModel(
            job_id=sample_job.id,
            match_score=30,
            role_match=False,
            skill_match=False,
            experience_match=False,
            location_match=True,
            salary_match=True,
            job_quality="SUSPICIOUS",
            duplicate_probability=0.8,
            suspicious=True,
            recommendation="SKIP",
            short_reason="Job appears suspicious",
            model="gemini-1.5-flash",
            prompt_version="v1.0"
        )
        db_session.add(analysis)
        db_session.commit()
        db_session.refresh(analysis)
        
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(
            sample_job, confirmed_profile, job_preference, analysis
        )
        
        assert decision.priority == DecisionPriority.HARD_REJECT
        assert decision.hard_filter_failed is True
        assert DecisionReasonCode.SUSPICIOUS_JOB in decision.reason_codes
        assert "suspicious" in decision.explanation.lower()
    
    def test_evaluate_job_without_ai_analysis(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_job: Job
    ):
        """Test evaluation without AI analysis (uses heuristics)."""
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(sample_job, confirmed_profile, job_preference)
        
        assert decision.ai_available is False
        assert decision.requires_ai_analysis is True
        # Should still produce a decision based on heuristics
        assert decision.priority in [
            DecisionPriority.HIGH_PRIORITY,
            DecisionPriority.NORMAL_PRIORITY,
            DecisionPriority.LOW_PRIORITY
        ]
    
    def test_save_decision_record(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_job: Job,
        sample_job_analysis: JobAnalysisModel
    ):
        """Test saving decision record to database."""
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(
            sample_job, confirmed_profile, job_preference, sample_job_analysis
        )
        
        service.save_decision_record(decision, sample_job.id)
        
        # Verify record was saved
        records = db_session.query(DecisionQualityRecord).filter(
            DecisionQualityRecord.job_id == sample_job.id
        ).all()
        
        assert len(records) == 1
        record = records[0]
        assert record.priority == decision.priority.value
        assert record.decision_score == int(decision.decision_score)
        assert record.primary_reason_code == decision.primary_reason_code.value
        assert record.hard_filter_failed == (1 if decision.hard_filter_failed else 0)
    
    def test_decision_score_calculation(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_job: Job,
        sample_job_analysis: JobAnalysisModel
    ):
        """Test that decision score is calculated correctly."""
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(
            sample_job, confirmed_profile, job_preference, sample_job_analysis
        )
        
        assert 0 <= decision.decision_score <= 100
        assert 0 <= decision.role_relevance_score <= 1
        assert 0 <= decision.skill_relevance_score <= 1
        assert 0 <= decision.experience_compatibility_score <= 1
        assert 0 <= decision.location_match_score <= 1
        assert 0 <= decision.salary_suitability_score <= 1
        assert 0 <= decision.job_quality_score <= 1
        assert 0 <= decision.freshness_score <= 1
        assert 0 <= decision.duplicate_probability <= 1
        assert 0 <= decision.suspicious_probability <= 1
        assert -1 <= decision.feedback_adjustment <= 1
    
    def test_explanation_generation(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_job: Job,
        sample_job_analysis: JobAnalysisModel
    ):
        """Test that explanations are generated correctly."""
        service = DecisionQualityService(db_session)
        decision = service.evaluate_job_decision(
            sample_job, confirmed_profile, job_preference, sample_job_analysis
        )
        
        assert decision.explanation
        assert len(decision.explanation) > 0
        assert len(decision.explanation) < 500  # Should be concise
        assert isinstance(decision.explanation, str)
