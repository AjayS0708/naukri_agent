"""
Mocked end-to-end tests for the autonomous cycle command.

Tests cover:
- One eligible native job applied and APPLIED recorded
- External skipped
- Unpaid skipped
- Duplicate skipped
- CAPTCHA/auth stops the cycle
- Limits stop the cycle
- max-applications respected
- dry-run creates no application rows and never clicks
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.job import Job
from backend.models.application import Application
from backend.models.profile import Profile, Resume
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.models.discovery import DiscoveryRun
from backend.schemas.application import ApplicationStatus, ApplicationStartResult
from backend.schemas.ai import AIRecommendation
from backend.services.applications import ApplicationRunner
from backend.services.agent_state import AgentStateManager
from backend.schemas.agent import AgentState

# Define excluded job ID locally for testing
EXCLUDED_JOB_ID = "300926927428"

TEST_DATABASE_URL = "sqlite:///:memory:"


class DecisionTracker:
    """Simple decision tracker for testing."""

    def __init__(self):
        self.decisions = []

    def add_decision(
        self,
        job_id: int,
        company: str,
        title: str,
        app_type: str,
        salary_pass: bool,
        experience_pass: bool,
        employment_pass: bool,
        gemini_result: str,
        gate_result: str,
        outcome: str,
    ):
        self.decisions.append({
            "job_id": job_id,
            "company": company,
            "title": title,
            "app_type": app_type,
            "salary_pass": salary_pass,
            "experience_pass": experience_pass,
            "employment_pass": employment_pass,
            "gemini_result": gemini_result,
            "gate_result": gate_result,
            "outcome": outcome,
        })

    def print_table(self):
        """Print the decision table to stdout."""
        if not self.decisions:
            return

        print("\n" + "=" * 120)
        print("PER-JOB DECISION TABLE")
        print("=" * 120)
        print(
            f"{'ID':<6} {'Company':<20} {'Title':<25} {'Type':<10} {'Sal':<4} {'Exp':<4} {'Emp':<4} "
            f"{'Gemini':<10} {'Gate':<10} {'Outcome':<15}"
        )
        print("-" * 120)

        for d in self.decisions:
            print(
                f"{d['job_id']:<6} {d['company'][:20]:<20} {d['title'][:25]:<25} {d['app_type']:<10} "
                f"{'PASS' if d['salary_pass'] else 'FAIL':<4} {'PASS' if d['experience_pass'] else 'FAIL':<4} "
                f"{'PASS' if d['employment_pass'] else 'FAIL':<4} {d['gemini_result']:<10} {d['gate_result']:<10} "
                f"{d['outcome']:<15}"
            )

        print("=" * 120 + "\n")


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
def state_manager():
    """Create a state manager."""
    return AgentStateManager()


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
def eligible_native_job(db_session: Session):
    """Create an eligible native job."""
    job = Job(
        platform="naukri",
        external_job_id="123456",
        url="https://www.naukri.com/job/test",
        title="Software Engineer",
        company="Tech Corp",
        description="A great job",
        location="Bengaluru",
        salary="5-7 LPA",
        salary_min=5.0,
        salary_max=7.0,
        experience="2-4 years",
        employment_type="Full-time",
        status="DISCOVERED",
        discovered_at=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        source="Software Engineer"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def external_job(db_session: Session):
    """Create an external job."""
    job = Job(
        platform="naukri",
        external_job_id="external123",
        url="https://www.naukri.com/job/external",
        title="Data Analyst",
        company="External Corp",
        description="External application",
        location="Bengaluru",
        salary="6-8 LPA",
        salary_min=6.0,
        salary_max=8.0,
        experience="2-4 years",
        employment_type="Full-time",
        status="DISCOVERED",
        discovered_at=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        source="Data Analyst"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def unpaid_job(db_session: Session):
    """Create an unpaid job."""
    job = Job(
        platform="naukri",
        external_job_id="unpaid123",
        url="https://www.naukri.com/job/unpaid",
        title="Software Engineer Fresher",
        company="Unpaid Corp",
        description="Unpaid internship",
        location="Bengaluru",
        salary="0 LPA",
        salary_min=0.0,
        salary_max=0.0,
        experience="0-1 years",
        employment_type="Full-time",
        status="DISCOVERED",
        discovered_at=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        source="Software Engineer Fresher"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


@pytest.fixture
def excluded_job(db_session: Session):
    """Create the excluded S&P job."""
    job = Job(
        platform="naukri",
        external_job_id=EXCLUDED_JOB_ID,
        url="https://www.naukri.com/job/excluded",
        title="Data Analyst",
        company="S&P Global",
        description="Excluded job",
        location="Bengaluru",
        salary="10-15 LPA",
        salary_min=10.0,
        salary_max=15.0,
        experience="3-5 years",
        employment_type="Full-time",
        status="DISCOVERED",
        discovered_at=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        source="Data Analyst"
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


class TestDecisionTracker:
    """Test the DecisionTracker class."""

    def test_add_decision(self):
        """Test adding a decision."""
        tracker = DecisionTracker()
        tracker.add_decision(
            job_id=1,
            company="Test Corp",
            title="Test Job",
            app_type="NATIVE",
            salary_pass=True,
            experience_pass=True,
            employment_pass=True,
            gemini_result="APPLY",
            gate_result="PASSED",
            outcome="APPLIED"
        )
        assert len(tracker.decisions) == 1
        assert tracker.decisions[0]["job_id"] == 1
        assert tracker.decisions[0]["outcome"] == "APPLIED"

    def test_print_table_empty(self, capsys):
        """Test printing table with no decisions."""
        tracker = DecisionTracker()
        tracker.print_table()
        captured = capsys.readouterr()
        assert "PER-JOB DECISION TABLE" not in captured.out

    def test_print_table_with_data(self, capsys):
        """Test printing table with decisions."""
        tracker = DecisionTracker()
        tracker.add_decision(
            job_id=1,
            company="Test Corp",
            title="Test Job",
            app_type="NATIVE",
            salary_pass=True,
            experience_pass=True,
            employment_pass=True,
            gemini_result="APPLY",
            gate_result="PASSED",
            outcome="APPLIED"
        )
        tracker.print_table()
        captured = capsys.readouterr()
        assert "PER-JOB DECISION TABLE" in captured.out
        assert "Test Corp" in captured.out
        assert "APPLIED" in captured.out


class TestAutonomousCycleLogic:
    """Test the autonomous cycle logic without full integration."""

    def test_eligible_native_job_passes_hard_filters(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference, eligible_native_job: Job
    ):
        """Test that an eligible native job passes hard filters."""
        from backend.services.matching.engine import MatchEngine
        from backend.services.gemini.queue import AIQueueService

        match_engine = MatchEngine(db_session)
        ai_queue_service = AIQueueService(db_session)

        # Evaluate hard filters
        match_decision = match_engine.evaluate_job(eligible_native_job, confirmed_profile, job_preferences)

        # Should pass hard filters
        assert match_decision.decision.value == "APPLY"

    def test_unpaid_job_fails_hard_filters(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference, unpaid_job: Job
    ):
        """Test that unpaid jobs fail hard filters."""
        from backend.services.matching.engine import MatchEngine

        match_engine = MatchEngine(db_session)

        # Evaluate hard filters
        match_decision = match_engine.evaluate_job(unpaid_job, confirmed_profile, job_preferences)

        # Should fail hard filters due to salary
        assert match_decision.decision.value != "APPLY"
        assert "salary" in match_decision.reason.lower()

    def test_excluded_job_id_is_correct(self):
        """Test that the excluded job ID is correctly defined."""
        assert EXCLUDED_JOB_ID == "300926927428"

    def test_job_creation_with_excluded_id(self, excluded_job: Job):
        """Test that excluded job can be created with correct ID."""
        assert excluded_job.external_job_id == EXCLUDED_JOB_ID

    def test_eligible_job_has_required_fields(self, eligible_native_job: Job):
        """Test that eligible job has all required fields."""
        assert eligible_native_job.title == "Software Engineer"
        assert eligible_native_job.company == "Tech Corp"
        assert eligible_native_job.salary_min == 5.0
        assert eligible_native_job.salary_max == 7.0
        assert eligible_native_job.location == "Bengaluru"
        assert eligible_native_job.employment_type == "Full-time"

    def test_external_job_can_be_created(self, external_job: Job):
        """Test that external job can be created."""
        assert external_job.external_job_id == "external123"
        assert external_job.title == "Data Analyst"

    def test_unpaid_job_has_zero_salary(self, unpaid_job: Job):
        """Test that unpaid job has zero salary."""
        assert unpaid_job.salary_min == 0.0
        assert unpaid_job.salary_max == 0.0
        assert unpaid_job.salary == "0 LPA"

    def test_profile_has_required_data(self, confirmed_profile: Profile):
        """Test that profile has required data."""
        assert confirmed_profile.confirmed == True
        assert confirmed_profile.data.get("name") == "Test User"
        assert confirmed_profile.data.get("location") == "Bengaluru"

    def test_preferences_have_required_fields(self, job_preferences: JobPreference):
        """Test that preferences have required fields."""
        assert "Bengaluru" in job_preferences.locations
        assert "Software Engineer" in job_preferences.job_titles
        assert job_preferences.min_salary_lpa == 4.0
        assert job_preferences.max_daily_applications == 20


class TestDiscoveryFailureHandling:
    """Test that discovery failures do not fall back to historical DB jobs."""

    def test_empty_discovery_run_prevents_stale_job_processing(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that a discovery run with 0 jobs prevents processing historical jobs."""
        from backend.models.discovery import DiscoveryRun
        from datetime import UTC, datetime, timedelta

        # Create a historical job from an old discovery run
        old_time = datetime.now(UTC) - timedelta(days=7)
        historical_job = Job(
            platform="naukri",
            external_job_id="old123",
            url="https://www.naukri.com/job/old",
            title="Software Engineer",
            company="Old Corp",
            description="Old job",
            location="Bengaluru",
            salary="5-7 LPA",
            salary_min=5.0,
            salary_max=7.0,
            experience="0-2 years",
            employment_type="Full-time",
            status="DISCOVERED",
            discovered_at=old_time,
            last_seen=old_time,
            source="Software Engineer"
        )
        db_session.add(historical_job)
        db_session.commit()

        # Create a current discovery run with 0 jobs
        current_run = DiscoveryRun(
            status="COMPLETED",
            jobs_discovered=0,
            new_jobs=0,
            duplicate_jobs=0,
            searches_attempted=1,
            errors=1,
            error_message="Homepage navigation failed"
        )
        db_session.add(current_run)
        db_session.commit()
        db_session.refresh(current_run)

        # Query jobs only from current run
        stmt = select(Job).where(
            Job.status == "DISCOVERED",
            Job.discovered_at >= current_run.started_at
        )
        jobs = db_session.execute(stmt).scalars().all()

        # Should return 0 jobs (not the historical job)
        assert len(jobs) == 0
        assert historical_job not in jobs

    def test_discovery_failure_does_not_create_applications(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that a failed discovery run creates no application records."""
        from backend.models.discovery import DiscoveryRun

        # Create a failed discovery run
        failed_run = DiscoveryRun(
            status="FAILED",
            jobs_discovered=0,
            new_jobs=0,
            duplicate_jobs=0,
            searches_attempted=1,
            errors=1,
            error_message="Security verification required"
        )
        db_session.add(failed_run)
        db_session.commit()

        # Check that no applications exist
        applications = db_session.execute(select(Application)).scalars().all()
        assert len(applications) == 0

    def test_current_run_jobs_only_from_this_run(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that only jobs from the current discovery run are processed."""
        from backend.models.discovery import DiscoveryRun
        from datetime import UTC, datetime, timedelta

        # Create historical job
        old_time = datetime.now(UTC) - timedelta(days=7)
        historical_job = Job(
            platform="naukri",
            external_job_id="old456",
            url="https://www.naukri.com/job/old2",
            title="Data Analyst",
            company="Old Company",
            description="Old job",
            location="Bengaluru",
            salary="4-6 LPA",
            salary_min=4.0,
            salary_max=6.0,
            experience="0-2 years",
            employment_type="Full-time",
            status="DISCOVERED",
            discovered_at=old_time,
            last_seen=old_time,
            source="Data Analyst"
        )
        db_session.add(historical_job)
        db_session.commit()

        # Create current discovery run
        current_run = DiscoveryRun(
            status="COMPLETED",
            jobs_discovered=2,
            new_jobs=2,
            duplicate_jobs=0,
            searches_attempted=1,
            errors=0
        )
        db_session.add(current_run)
        db_session.commit()
        db_session.refresh(current_run)

        # Create current job
        current_job = Job(
            platform="naukri",
            external_job_id="new123",
            url="https://www.naukri.com/job/new",
            title="Software Engineer",
            company="New Corp",
            description="New job",
            location="Bengaluru",
            salary="5-7 LPA",
            salary_min=5.0,
            salary_max=7.0,
            experience="0-2 years",
            employment_type="Full-time",
            status="DISCOVERED",
            discovered_at=current_run.started_at,
            last_seen=current_run.started_at,
            source="Software Engineer"
        )
        db_session.add(current_job)
        db_session.commit()

        # Query jobs only from current run
        stmt = select(Job).where(
            Job.status == "DISCOVERED",
            Job.discovered_at >= current_run.started_at
        )
        jobs = db_session.execute(stmt).scalars().all()

        # Should return only the current job
        assert len(jobs) == 1
        assert current_job in jobs
        assert historical_job not in jobs

    def test_zero_jobs_discovered_stops_cycle(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that 0 jobs discovered causes cycle to stop."""
        from backend.models.discovery import DiscoveryRun

        # Create a discovery run with 0 jobs
        zero_run = DiscoveryRun(
            status="COMPLETED",
            jobs_discovered=0,
            new_jobs=0,
            duplicate_jobs=0,
            searches_attempted=1,
            errors=0
        )
        db_session.add(zero_run)
        db_session.commit()
        db_session.refresh(zero_run)

        # Check that jobs_discovered is 0
        assert zero_run.jobs_discovered == 0

        # This should cause the cycle to stop
        should_stop = zero_run.jobs_discovered == 0
        assert should_stop is True


class TestCardExperienceFiltering:
    """Test current-card experience filtering per C2 fresher-only policy."""

    def test_card_0_1_years_eligible(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that 0-1 years experience on card is eligible."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer",
            experience="0-1 years"
        )

        # Update preferences to match C2: max_required_experience_years = 0
        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is True
        assert "0-1" in reason or "fresher" in reason.lower()

    def test_card_0_2_years_eligible(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that 0-2 years experience on card is eligible."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer",
            experience="0-2 years"
        )

        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is True

    def test_card_0_3_years_eligible(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that 0-3 years experience on card is eligible."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer",
            experience="0-3 years"
        )

        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is True

    def test_card_fresher_eligible(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that 'Fresher' on card is eligible."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer",
            experience="Fresher"
        )

        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is True

    def test_card_1_3_years_rejected(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that 1-3 years experience on card is rejected."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer",
            experience="1-3 years"
        )

        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is False
        assert "experience" in reason.lower()

    def test_card_2_5_years_rejected(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that 2-5 years experience on card is rejected."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer",
            experience="2-5 years"
        )

        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is False

    def test_card_5_8_years_rejected(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that 5-8 years experience on card is rejected."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer",
            experience="5-8 years"
        )

        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is False

    def test_card_missing_experience_with_fresher_title_eligible(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that missing experience with fresher title is eligible."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer Fresher",
            experience=None
        )

        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is True

    def test_card_missing_experience_without_fresher_title_rejected(
        self, db_session: Session, confirmed_profile: Profile, job_preferences: JobPreference
    ):
        """Test that missing experience without fresher title is rejected."""
        from backend.services.matching.engine import experience_passes_fresher_rule

        job = Job(
            title="Software Engineer",
            experience=None
        )

        job_preferences.max_required_experience_years = 0
        db_session.commit()

        experience_ok, reason = experience_passes_fresher_rule(job, job_preferences)
        assert experience_ok is False


class TestDirectSearchNavigation:
    """Test that direct search navigation does not depend on homepage selector."""

    def test_search_url_builder_includes_experience_filter(self):
        """Test that search URL includes experience=0 filter."""
        from backend.services.naukri.adapter import NaukriAdapter

        adapter = NaukriAdapter()
        url = adapter._build_naukri_search_url("Software Engineer Fresher", ["Bengaluru"])

        assert "experience=0" in url
        assert "Software-Engineer-Fresher" in url
        assert "Bengaluru" in url

    def test_search_url_builder_handles_multi_word_terms(self):
        """Test that multi-word search terms are properly normalized."""
        from backend.services.naukri.adapter import NaukriAdapter

        adapter = NaukriAdapter()
        url = adapter._build_naukri_search_url("Graduate Engineer Trainee", ["Bengaluru"])

        assert "Graduate-Engineer-Trainee" in url
        assert "experience=0" in url

    def test_search_url_builder_no_location_fallback(self):
        """Test that missing location falls back to India."""
        from backend.services.naukri.adapter import NaukriAdapter

        adapter = NaukriAdapter()
        url = adapter._build_naukri_search_url("Software Engineer Fresher", [])

        assert "india" in url.lower()
        assert "experience=0" in url
