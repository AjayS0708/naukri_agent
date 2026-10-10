"""E5-R5.2: truthful outcomes and bounded error recovery in the autonomous cycle.

All browser/runner behavior is mocked: no live Naukri pages, no Apply clicks,
no real browser sessions, no database writes beyond the in-memory test DB.
"""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.ai import JobAnalysisModel
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.services.autonomous_cycle.service import AutonomousCycle
from backend.schemas.ai import AIRecommendation, JobQuality

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
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
    resume = Resume(
        stored_filename="test_resume.pdf",
        original_filename="resume.pdf",
        sha256="abc123",
        file_size=1000,
        text_length=5000,
        is_current=True,
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
            "notice_period": "30 days",
        },
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def job_preferences(db_session: Session):
    preferences = JobPreference(
        locations=["Bengaluru", "Remote"],
        job_titles=["Software Engineer", "Data Analyst"],
        employment_types=["Full-time", "Contract"],
        min_salary_lpa=4.0,
        aggressiveness="BALANCED",
        max_daily_applications=20,
        max_hourly_applications=4,
    )
    db_session.add(preferences)
    db_session.commit()
    db_session.refresh(preferences)
    return preferences


def _make_analyzed_job(db_session: Session, index: int) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"e5r52job{index}",
        url=f"https://www.naukri.com/e5r52job{index}",
        title="Software Engineer",
        company=f"Company {index}",
        description="Python developer role",
        location="Bengaluru",
        salary="5-7 LPA",
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    db_session.add(
        JobAnalysisModel(
            job_id=job.id,
            match_score=80,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality=JobQuality.GOOD.value,
            duplicate_probability=0.05,
            suspicious=False,
            recommendation=AIRecommendation.APPLY.value,
            short_reason="Strong match",
            model="gemini",
            prompt_version="v1",
        )
    )
    db_session.commit()
    return job


def _make_cycle(db_session: Session, jobs, max_applications: int) -> AutonomousCycle:
    cycle = AutonomousCycle(
        max_applications=max_applications, dry_run=False, enable_cli_output=False
    )
    cycle.current_discovery_run = DiscoveryRun(
        status="COMPLETED",
        jobs_discovered=len(jobs),
        current_run_job_ids=",".join(str(job.id) for job in jobs),
    )
    return cycle


def _unconfirmed_stats() -> dict:
    return {
        "total": 1,
        "processed": 1,
        "applied": 0,
        "submitted_unconfirmed": 1,
        "skipped": 0,
        "needs_attention": 0,
        "external": 0,
        "failed": 0,
        "errors": 0,
        "dry_run": 0,
        "dry_run_mode": False,
    }


class TestBudgetAccounting:
    """max_applications counts only confirmed APPLIED outcomes (E5-R5.2)."""

    @pytest.mark.asyncio
    async def test_unconfirmed_submission_not_counted_in_budget(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_analyzed_job(db_session, 0)
        cycle = _make_cycle(db_session, [job], max_applications=1)

        with patch(
            "backend.services.autonomous_cycle.service.ApplicationRunner"
        ) as mock_runner:
            mock_runner.return_value.run_applications = AsyncMock(
                return_value=_unconfirmed_stats()
            )
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["submitted_unconfirmed"] == 1
        assert stats["applied"] == 0
        assert cycle.applications_count == 0
        assert cycle.stop_reason is None
        mock_runner.return_value.run_applications.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_external_needs_attention_failed_do_not_consume_budget(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(3)]
        cycle = _make_cycle(db_session, jobs, max_applications=2)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["EXTERNAL", "NEEDS_ATTENTION", "FAILED"],
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 3
        assert stats["external"] == 1
        assert stats["needs_attention"] == 1
        assert stats["failed"] == 1
        assert stats["applied"] == 0
        assert cycle.applications_count == 0
        assert cycle.stop_reason is None

    @pytest.mark.asyncio
    async def test_confirmed_applied_consumes_budget_and_stops_at_limit(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(3)]
        cycle = _make_cycle(db_session, jobs, max_applications=2)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["APPLIED", "APPLIED", "APPLIED"],
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 2
        assert stats["applied"] == 2
        assert cycle.applications_count == 2
        assert cycle.stop_reason is not None
        assert "max-applications" in cycle.stop_reason
        assert cycle.stop_is_normal is True


class TestBoundedErrorRecovery:
    """One isolated ERROR continues; two consecutive ERRORs abort (E5-R5.2)."""

    @pytest.mark.asyncio
    async def test_one_error_permits_next_candidate(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(2)]
        cycle = _make_cycle(db_session, jobs, max_applications=5)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["ERROR", "APPLIED"],
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 2
        assert stats["failed"] == 1
        assert stats["applied"] == 1
        assert cycle.applications_count == 1
        assert cycle.stop_reason is None

    @pytest.mark.asyncio
    async def test_two_consecutive_errors_stop_processing(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(3)]
        cycle = _make_cycle(db_session, jobs, max_applications=5)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["ERROR", "ERROR", "APPLIED"],
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 2
        assert stats["failed"] == 2
        assert stats["applied"] == 0
        assert cycle.applications_count == 0
        assert cycle.stop_reason is not None
        assert "consecutive" in cycle.stop_reason.lower()
        assert cycle.stop_is_normal is False

    @pytest.mark.asyncio
    async def test_valid_outcome_resets_error_counter(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(4)]
        cycle = _make_cycle(db_session, jobs, max_applications=5)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["ERROR", "EXTERNAL", "ERROR", "APPLIED"],
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 4
        assert stats["failed"] == 2
        assert stats["external"] == 1
        assert stats["applied"] == 1
        assert cycle.applications_count == 1
        assert cycle.stop_reason is None

    @pytest.mark.asyncio
    async def test_security_required_aborts_immediately(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(2)]
        cycle = _make_cycle(db_session, jobs, max_applications=5)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["SECURITY_REQUIRED", "APPLIED"],
        ) as mock_process:
            await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 1
        assert cycle.stop_reason == "Security challenge encountered"
        assert cycle.applications_count == 0

    @pytest.mark.asyncio
    async def test_auth_required_aborts_immediately(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(2)]
        cycle = _make_cycle(db_session, jobs, max_applications=5)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["AUTH_REQUIRED", "APPLIED"],
        ) as mock_process:
            await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 1
        assert cycle.stop_reason == "Authentication required"
        assert cycle.applications_count == 0
