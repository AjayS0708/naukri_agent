import pytest
from datetime import UTC, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.job import Job
from backend.models.profile import Profile, Resume
from backend.models.matching import JobPreference
from backend.services.applications import ApplicationService
from backend.schemas.ai import JobAnalysis, JobQuality, AIRecommendation


# Test database setup
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    """Create a test database session."""
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(autocommit=False, autoflush=False, bind=engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def confirmed_profile(db_session: Session):
    """Create a confirmed profile."""
    resume = Resume(
        stored_filename="test_resume.pdf",
        original_filename="resume.pdf",
        sha256="abc123",
        file_size=1000,
        text_length=5000,
        is_current=True
    )
    db_session.add(resume)
    db_session.commit()
    
    profile = Profile(
        resume_id=resume.id,
        status="CONFIRMED",
        confirmed=True,
        data={
            "name": "Test User",
            "experience": [
                {"title": "Software Engineer", "company": "Tech Corp", "years": 2}
            ],
            "skills": ["Python", "SQL"],
            "education": [{"degree": "B.Tech", "university": "Test University"}],
            "location": "Bengaluru",
            "current_ctc": "5 LPA",
            "notice_period": "30 days"
        }
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def job_preferences(db_session: Session):
    """Create job preferences."""
    preferences = JobPreference(
        locations=["Bengaluru", "Remote"],
        job_titles=["Software Engineer", "Data Analyst"],
        employment_types=["Full-time", "Contract"],
        min_salary_lpa=4.0,
        aggressiveness="BALANCED",
        max_daily_applications=20,
        max_hourly_applications=4
    )
    db_session.add(preferences)
    db_session.commit()
    db_session.refresh(preferences)
    return preferences


@pytest.fixture
def eligible_job(db_session: Session):
    """Create an eligible job."""
    job = Job(
        platform="naukri",
        external_job_id="job123",
        url="https://www.naukri.com/job123",
        title="Software Engineer",
        company="Tech Company",
        description="Python developer role",
        location="Bengaluru",
        salary="5-7 LPA",
        experience="2-4 years",
        employment_type="Full-time"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def application_service(db_session: Session):
    """Create application service."""
    return ApplicationService(db_session)


class TestSafetyGate:
    """Test the final safety gate."""
    
    def test_eligible_job_allowed(
        self,
        application_service: ApplicationService,
        eligible_job: Job,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Test that an eligible job passes the safety gate."""
        allowed, reason = application_service.run_final_safety_gate(
            eligible_job, confirmed_profile, job_preferences
        )
        assert allowed is True
        assert "passed" in reason.lower()
    
    def test_location_mismatch_blocked(
        self,
        application_service: ApplicationService,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Test that location mismatch blocks application."""
        job = Job(
            platform="naukri",
            external_job_id="job456",
            url="https://www.naukri.com/job456",
            title="Software Engineer",
            company="Tech Company",
            description="Python developer role",
            location="Hyderabad",  # Not in allowed locations
            salary="5-7 LPA",
            experience="2-4 years",
            employment_type="Full-time"
        )
        db_session.add(job)
        db_session.commit()
        
        allowed, reason = application_service.run_final_safety_gate(
            job, confirmed_profile, job_preferences
        )
        assert allowed is False
        assert "location" in reason.lower()
    
    def test_experience_mismatch_blocked(
        self,
        application_service: ApplicationService,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Test that experience requirement too high blocks application."""
        job = Job(
            platform="naukri",
            external_job_id="job789",
            url="https://www.naukri.com/job789",
            title="Senior Software Engineer",
            company="Tech Company",
            description="Senior Python developer role",
            location="Bengaluru",
            salary="10-15 LPA",
            experience="5-7 years",  # More than user's 2 years + 2 grace
            employment_type="Full-time"
        )
        db_session.add(job)
        db_session.commit()
        
        allowed, reason = application_service.run_final_safety_gate(
            job, confirmed_profile, job_preferences
        )
        assert allowed is False
        assert "experience" in reason.lower()
    
    def test_salary_below_minimum_blocked(
        self,
        application_service: ApplicationService,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Test that salary below minimum blocks application."""
        job = Job(
            platform="naukri",
            external_job_id="job101",
            url="https://www.naukri.com/job101",
            title="Software Engineer",
            company="Tech Company",
            description="Python developer role",
            location="Bengaluru",
            salary="2-3 LPA",  # Below 4 LPA minimum
            experience="2-4 years",
            employment_type="Full-time"
        )
        db_session.add(job)
        db_session.commit()
        
        allowed, reason = application_service.run_final_safety_gate(
            job, confirmed_profile, job_preferences
        )
        assert allowed is False
        assert "salary" in reason.lower()
    
    def test_profile_not_confirmed_blocked(
        self,
        application_service: ApplicationService,
        eligible_job: Job,
        db_session: Session,
        job_preferences: JobPreference
    ):
        """Test that unconfirmed profile blocks application."""
        profile = Profile(
            resume_id=1,
            status="REVIEW_REQUIRED",
            confirmed=False,
            data={"name": "Test User"}
        )
        db_session.add(profile)
        db_session.commit()
        
        allowed, reason = application_service.run_final_safety_gate(
            eligible_job, profile, job_preferences
        )
        assert allowed is False
        assert "confirmed" in reason.lower()
    
    def test_suspicious_job_blocked(
        self,
        application_service: ApplicationService,
        eligible_job: Job,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Test that suspicious job (flagged by AI) blocks application."""
        job_analysis = JobAnalysis(
            match_score=50,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality=JobQuality.SUSPICIOUS,
            duplicate_probability=0.1,
            suspicious=True,
            recommendation=AIRecommendation.SKIP,
            short_reason="Suspicious posting"
        )
        
        allowed, reason = application_service.run_final_safety_gate(
            eligible_job, confirmed_profile, job_preferences, job_analysis
        )
        assert allowed is False
        assert "suspicious" in reason.lower()
    
    def test_ai_needs_attention_blocked(
        self,
        application_service: ApplicationService,
        eligible_job: Job,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Test that AI NEEDS_ATTENTION recommendation blocks application."""
        job_analysis = JobAnalysis(
            match_score=60,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality=JobQuality.AVERAGE,
            duplicate_probability=0.1,
            suspicious=False,
            recommendation=AIRecommendation.NEEDS_ATTENTION,
            short_reason="Requires manual review"
        )
        
        allowed, reason = application_service.run_final_safety_gate(
            eligible_job, confirmed_profile, job_preferences, job_analysis
        )
        assert allowed is False
        assert "attention" in reason.lower()
    
    def test_employment_type_not_allowed_blocked(
        self,
        application_service: ApplicationService,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Test that disallowed employment type blocks application."""
        job = Job(
            platform="naukri",
            external_job_id="job202",
            url="https://www.naukri.com/job202",
            title="Software Engineer",
            company="Tech Company",
            description="Python developer role",
            location="Bengaluru",
            salary="5-7 LPA",
            experience="2-4 years",
            employment_type="Part-time"  # Not in allowed types
        )
        db_session.add(job)
        db_session.commit()
        
        allowed, reason = application_service.run_final_safety_gate(
            job, confirmed_profile, job_preferences
        )
        assert allowed is False
        assert "employment" in reason.lower() or "type" in reason.lower()
    
    def test_job_title_not_in_scope_blocked(
        self,
        application_service: ApplicationService,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Test that job title not in configured scope blocks application."""
        job = Job(
            platform="naukri",
            external_job_id="job303",
            url="https://www.naukri.com/job303",
            title="Marketing Manager",  # Not in job_titles
            company="Tech Company",
            description="Marketing role",
            location="Bengaluru",
            salary="5-7 LPA",
            experience="2-4 years",
            employment_type="Full-time"
        )
        db_session.add(job)
        db_session.commit()
        
        allowed, reason = application_service.run_final_safety_gate(
            job, confirmed_profile, job_preferences
        )
        assert allowed is False
        assert "title" in reason.lower() or "scope" in reason.lower()
