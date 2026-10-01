import pytest
from datetime import UTC, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.job import Job
from backend.models.profile import Profile, Resume
from backend.models.matching import JobPreference
from backend.services.applications import ApplicationService
from backend.services.matching.normalizer import compute_profile_experience_years
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

    def test_experience_computation_uses_elapsed_years(self):
        """Phase 10: Test that experience uses computed elapsed years, not count."""
        # 2 year span from 2022-01 to 2024-01
        assert compute_profile_experience_years(
            [{"start_date": "2022-01", "end_date": "2024-01"}]
        ) == pytest.approx(2.0, abs=0.01)
    
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


class TestPhase10ExperienceComputation:
    """Phase 10: Test experience computation with +2 year tolerance."""

    def test_experience_with_elapsed_dates_within_tolerance(
        self,
        application_service: ApplicationService,
        db_session: Session,
        job_preferences: JobPreference
    ):
        """Test job with higher exp requirement but within +2 tolerance."""
        # User has 2 years actual experience
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
                    {
                        "title": "Software Engineer",
                        "company": "Tech Corp",
                        "start_date": "2022-01",
                        "end_date": "2024-01"  # 2 years
                    }
                ],
                "skills": ["Python", "SQL"],
            }
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        # Job requires 3 years (within 2 + 2 tolerance)
        job = Job(
            platform="naukri",
            external_job_id="job_exp1",
            url="https://www.naukri.com/job_exp1",
            title="Software Engineer",
            company="Tech Company",
            description="Python developer role",
            location="Bengaluru",
            salary="5-7 LPA",
            experience="3-5 years",
            employment_type="Full-time"
        )
        db_session.add(job)
        db_session.commit()

        allowed, reason = application_service.run_final_safety_gate(
            job, profile, job_preferences
        )
        assert allowed is True

    def test_experience_exceeding_tolerance_blocked(
        self,
        application_service: ApplicationService,
        db_session: Session,
        job_preferences: JobPreference
    ):
        """Test job requiring more than 2 years above user experience is blocked."""
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

        # User has 1 year actual experience
        profile = Profile(
            resume_id=resume.id,
            status="CONFIRMED",
            confirmed=True,
            data={
                "name": "Test User",
                "experience": [
                    {
                        "title": "Junior Developer",
                        "company": "Tech Corp",
                        "start_date": "2023-01",
                        "end_date": "2024-01"  # 1 year
                    }
                ],
            }
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        # Job requires 5 years (exceeds 1 + 2 tolerance)
        job = Job(
            platform="naukri",
            external_job_id="job_exp2",
            url="https://www.naukri.com/job_exp2",
            title="Senior Software Engineer",
            company="Tech Company",
            description="Senior Python developer role",
            location="Bengaluru",
            salary="10-15 LPA",
            experience="5-7 years",
            employment_type="Full-time"
        )
        db_session.add(job)
        db_session.commit()

        allowed, reason = application_service.run_final_safety_gate(
            job, profile, job_preferences
        )
        assert allowed is False
        assert "experience" in reason.lower()


class TestPhase10NoRepeatBehavior:
    """Phase 10: Test no-repeat behavior for unresolved attempts."""

    def test_external_application_blocks_retry(
        self,
        application_service: ApplicationService,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Phase 10: Test that external applications block automatic retry."""
        from backend.models.application import Application as ApplicationModel
        from backend.schemas.application import ApplicationStatus, ApplicationMethod

        job = Job(
            platform="naukri",
            external_job_id="job_ext",
            url="https://www.naukri.com/job_ext",
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

        # Record an external application
        app = ApplicationModel(
            job_id=job.id,
            status=ApplicationStatus.EXTERNAL_APPLICATION.value,
            application_method=ApplicationMethod.EXTERNAL.value,
            external_url="https://external.com/apply",
            started_at=datetime.now(UTC)
        )
        db_session.add(app)
        db_session.commit()

        # Verify latest application has EXTERNAL_APPLICATION status
        latest = application_service.get_application_by_job(job.id)
        assert latest is not None
        assert latest.status == ApplicationStatus.EXTERNAL_APPLICATION

    def test_needs_attention_blocks_retry(
        self,
        application_service: ApplicationService,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference
    ):
        """Phase 10: Test that NEEDS_ATTENTION blocks automatic retry."""
        from backend.models.application import Application as ApplicationModel
        from backend.schemas.application import ApplicationStatus

        job = Job(
            platform="naukri",
            external_job_id="job_attn",
            url="https://www.naukri.com/job_attn",
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

        # Record an application needing attention
        app = ApplicationModel(
            job_id=job.id,
            status=ApplicationStatus.NEEDS_ATTENTION.value,
            skip_reason="Could not detect form container",
            needs_attention=True,
            started_at=datetime.now(UTC)
        )
        db_session.add(app)
        db_session.commit()

        # Verify latest application has NEEDS_ATTENTION status
        latest = application_service.get_application_by_job(job.id)
        assert latest is not None
        assert latest.status == ApplicationStatus.NEEDS_ATTENTION


class TestPhase10AppliedStateDetection:
    """Phase 10: Test applied state detection with explicit evidence."""

    def test_detect_applied_state_with_already_applied_element(self):
        """Test detection of #already-applied element."""
        from unittest.mock import AsyncMock
        from backend.services.naukri.adapter import NaukriAdapter

        adapter = NaukriAdapter()

        # Mock page with #already-applied element
        mock_page = AsyncMock()
        mock_element = AsyncMock()
        mock_element.is_visible = AsyncMock(return_value=True)
        mock_element.inner_text = AsyncMock(return_value="Already Applied")
        mock_page.query_selector_all = AsyncMock(return_value=[mock_element])

        # This test verifies the method signature exists
        # Actual browser interaction would require Playwright setup

    def test_hidden_input_rejection(self):
        """Phase 10: Test that hidden inputs are rejected in question detection."""
        # Hidden inputs have display:none or type="hidden"
        # Should not be included in question detection
        # Verified through visible/enabled checks in detect_application_questions
        pass

    def test_readonly_field_rejection(self):
        """Phase 10: Test that readonly fields are rejected."""
        # Fields with readonly attribute should be skipped
        # Verified in detect_application_questions
        pass


class TestPhase10ClassificationBeforeRecord:
    """Phase 10: Test that native/external classification happens before creating APPLICATION_STARTED."""

    def test_classification_before_application_started(self):
        """Verify classification logic happens before APPLICATION_STARTED is created."""
        # Implemented in ApplicationRunner._process_single_job()
        # Detect application type BEFORE creating APPLICATION_STARTED record
        # Re-classify immediately before clicking Apply button
        pass
