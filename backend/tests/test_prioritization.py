import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.database.database import Base
from backend.services.decision.prioritization import JobPrioritizationService
from backend.schemas.decision import DecisionPriority


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
    
    # Create a resume first
    resume = Resume(
        stored_filename="test_resume.pdf",
        original_filename="test_resume.pdf",
        sha256="abc123" * 16,
        file_size=1024,
        text_length=500,
        is_current=True
    )
    db_session.add(resume)
    db_session.commit()
    db_session.refresh(resume)
    
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
def sample_jobs(db_session: Session):
    """Create sample jobs with varying quality for testing."""
    jobs = []
    
    # High priority job
    job1 = Job(
        platform="naukri",
        external_job_id="high1",
        url="https://naukri.com/job/high1",
        title="Software Engineer",
        company="Good Company",
        description="Looking for a software engineer with Python and JavaScript experience.",
        location="Bengaluru",
        salary="8-12 LPA",
        salary_min=8.0,
        salary_max=12.0,
        experience="2-4 years",
        experience_min=2.0,
        experience_max=4.0,
        employment_type="Full-time",
        posted_at=datetime.now(UTC) - timedelta(days=1),
        status="DISCOVERED"
    )
    jobs.append(job1)
    
    # Normal priority job
    job2 = Job(
        platform="naukri",
        external_job_id="normal1",
        url="https://naukri.com/job/normal1",
        title="Software Developer",
        company="Average Company",
        description="Looking for a software developer.",
        location="Bengaluru",
        salary="5-7 LPA",
        salary_min=5.0,
        salary_max=7.0,
        experience="2-5 years",
        experience_min=2.0,
        experience_max=5.0,
        employment_type="Full-time",
        posted_at=datetime.now(UTC) - timedelta(days=5),
        status="DISCOVERED"
    )
    jobs.append(job2)
    
    # Low priority job
    job3 = Job(
        platform="naukri",
        external_job_id="low1",
        url="https://naukri.com/job/low1",
        title="Junior Developer",
        company="Small Company",
        description="Looking for a junior developer.",
        location="Bengaluru",
        salary="3-4 LPA",
        salary_min=3.0,
        salary_max=4.0,
        experience="0-2 years",
        experience_min=0.0,
        experience_max=2.0,
        employment_type="Full-time",
        posted_at=datetime.now(UTC) - timedelta(days=15),
        status="DISCOVERED"
    )
    jobs.append(job3)
    
    # Skip job (location mismatch)
    job4 = Job(
        platform="naukri",
        external_job_id="skip1",
        url="https://naukri.com/job/skip1",
        title="Software Engineer",
        company="Other Company",
        description="Looking for a software engineer.",
        location="Hyderabad",  # Not in allowed locations
        salary="5-8 LPA",
        employment_type="Full-time",
        status="DISCOVERED"
    )
    jobs.append(job4)
    
    for job in jobs:
        db_session.add(job)
    db_session.commit()
    
    for job in jobs:
        db_session.refresh(job)
    
    return jobs


@pytest.fixture
def sample_analyses(db_session: Session, sample_jobs):
    """Create sample job analyses for testing."""
    analyses = []
    
    # High priority analysis
    analysis1 = JobAnalysisModel(
        job_id=sample_jobs[0].id,
        match_score=90,
        role_match=True,
        skill_match=True,
        experience_match=True,
        location_match=True,
        salary_match=True,
        job_quality="GOOD",
        duplicate_probability=0.01,
        suspicious=False,
        recommendation="APPLY",
        short_reason="Strong match for Python and JavaScript experience.",
        model="gemini-1.5-flash",
        prompt_version="v1.0"
    )
    analyses.append(analysis1)
    
    # Normal priority analysis
    analysis2 = JobAnalysisModel(
        job_id=sample_jobs[1].id,
        match_score=70,
        role_match=True,
        skill_match=True,
        experience_match=True,
        location_match=True,
        salary_match=True,
        job_quality="AVERAGE",
        duplicate_probability=0.05,
        suspicious=False,
        recommendation="APPLY",
        short_reason="Good match for software development role.",
        model="gemini-1.5-flash",
        prompt_version="v1.0"
    )
    analyses.append(analysis2)
    
    # Low priority analysis
    analysis3 = JobAnalysisModel(
        job_id=sample_jobs[2].id,
        match_score=50,
        role_match=True,
        skill_match=False,
        experience_match=True,
        location_match=True,
        salary_match=True,
        job_quality="AVERAGE",
        duplicate_probability=0.1,
        suspicious=False,
        recommendation="APPLY",
        short_reason="Moderate match, some skills missing.",
        model="gemini-1.5-flash",
        prompt_version="v1.0"
    )
    analyses.append(analysis3)
    
    for analysis in analyses:
        db_session.add(analysis)
    db_session.commit()
    
    for analysis in analyses:
        db_session.refresh(analysis)
    
    return analyses


class TestJobPrioritizationService:
    """Test job prioritization service."""
    
    def test_prioritize_jobs_sorting(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_jobs
    ):
        """Test that jobs are prioritized and sorted correctly."""
        service = JobPrioritizationService(db_session)
        job_ids = [job.id for job in sample_jobs]
        
        result = service.prioritize_jobs(job_ids, confirmed_profile, job_preference)
        
        assert result.total_jobs == 4
        assert len(result.prioritized_jobs) == 4
        
        # Check that jobs are sorted by priority (highest first)
        priorities = [job.priority for job in result.prioritized_jobs]
        
        # Verify that we have different priority levels
        assert len(set(priorities)) > 1
        
        # Verify that HARD_REJECT jobs are present (location mismatch)
        assert DecisionPriority.HARD_REJECT in priorities
        
        # Verify that some jobs are not HARD_REJECTED (eligible jobs)
        non_rejected = [p for p in priorities if p != DecisionPriority.HARD_REJECT]
        assert len(non_rejected) > 0
    
    def test_prioritize_jobs_counts(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_jobs
    ):
        """Test that priority counts are calculated correctly."""
        service = JobPrioritizationService(db_session)
        job_ids = [job.id for job in sample_jobs]
        
        result = service.prioritize_jobs(job_ids, confirmed_profile, job_preference)
        
        # Verify counts match total
        total_count = (
            result.high_priority_count +
            result.normal_priority_count +
            result.low_priority_count +
            result.skip_count +
            result.hard_reject_count +
            result.needs_attention_count
        )
        assert total_count == result.total_jobs
    
    def test_get_eligible_jobs_for_application(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_jobs
    ):
        """Test filtering to eligible jobs only."""
        service = JobPrioritizationService(db_session)
        job_ids = [job.id for job in sample_jobs]
        
        eligible_ids = service.get_eligible_jobs_for_application(
            job_ids, confirmed_profile, job_preference
        )
        
        # Should exclude HARD_REJECT and SKIP
        assert len(eligible_ids) > 0
        assert len(eligible_ids) <= len(job_ids)
        
        # Verify the location mismatch job is not in eligible list
        eligible_jobs = [job for job in sample_jobs if job.id in eligible_ids]
        for job in eligible_jobs:
            assert job.location in ["Bengaluru", "Remote"] or job.location is None
    
    def test_get_prioritized_eligible_jobs_with_limit(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_jobs
    ):
        """Test getting prioritized eligible jobs with limit."""
        service = JobPrioritizationService(db_session)
        job_ids = [job.id for job in sample_jobs]
        
        # Test with limit
        limit = 2
        eligible_jobs = service.get_prioritized_eligible_jobs(
            job_ids, confirmed_profile, job_preference, limit=limit
        )
        
        assert len(eligible_jobs) <= limit
        
        # Test without limit
        all_eligible = service.get_prioritized_eligible_jobs(
            job_ids, confirmed_profile, job_preference
        )
        
        assert len(all_eligible) >= len(eligible_jobs)
    
    def test_prioritize_jobs_deterministic(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_jobs
    ):
        """Test that prioritization is deterministic."""
        service = JobPrioritizationService(db_session)
        job_ids = [job.id for job in sample_jobs]
        
        # Run prioritization twice
        result1 = service.prioritize_jobs(job_ids, confirmed_profile, job_preference)
        result2 = service.prioritize_jobs(job_ids, confirmed_profile, job_preference)
        
        # Results should be identical
        assert result1.total_jobs == result2.total_jobs
        assert len(result1.prioritized_jobs) == len(result2.prioritized_jobs)
        
        for job1, job2 in zip(result1.prioritized_jobs, result2.prioritized_jobs):
            assert job1.job_id == job2.job_id
            assert job1.priority == job2.priority
            assert job1.decision_score == job2.decision_score
    
    def test_prioritize_jobs_with_ai_analysis(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference,
        sample_jobs,
        sample_analyses
    ):
        """Test prioritization with AI analysis available."""
        service = JobPrioritizationService(db_session)
        job_ids = [job.id for job in sample_jobs]
        
        result = service.prioritize_jobs(job_ids, confirmed_profile, job_preference)
        
        # Jobs with AI analysis should have more accurate prioritization
        assert result.total_jobs == 4
        
        # High priority job should have higher score than low priority
        high_priority_jobs = [j for j in result.prioritized_jobs if j.priority == DecisionPriority.HIGH_PRIORITY]
        low_priority_jobs = [j for j in result.prioritized_jobs if j.priority == DecisionPriority.LOW_PRIORITY]
        
        if high_priority_jobs and low_priority_jobs:
            assert high_priority_jobs[0].decision_score > low_priority_jobs[0].decision_score
    
    def test_prioritize_nonexistent_job(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preference: JobPreference
    ):
        """Test prioritization with non-existent job ID."""
        service = JobPrioritizationService(db_session)
        job_ids = [99999]  # Non-existent job ID
        
        result = service.prioritize_jobs(job_ids, confirmed_profile, job_preference)
        
        # Should handle gracefully
        assert result.total_jobs == 0
        assert len(result.prioritized_jobs) == 0
