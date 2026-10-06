"""Mocked tests for URL mode bug fixes and salary filter alignment."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from phase10_live_apply_launcher import (
    ingest_job_from_url,
    _extract_salary_from_page,
    _extract_employment_type_from_page,
    _extract_title_from_page,
    _extract_company_from_page,
    _extract_location_from_page,
    _extract_description_from_page,
    deterministic_check,
)


@pytest.fixture
def test_session():
    engine = create_engine("sqlite:///:memory:")
    from backend.database.database import Base
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def profile_and_prefs(test_session):
    """Create profile and preferences for filter testing."""
    resume = Resume(
        stored_filename="test_resume.pdf",
        original_filename="test_resume.pdf",
        sha256="0" * 64,
        file_size=1000,
        text_length=500,
    )
    test_session.add(resume)
    test_session.flush()

    profile = Profile(
        resume_id=resume.id,
        confirmed=True,
        data={"experience": [{"company": "Acme", "years": 5}]},
    )
    test_session.add(profile)

    prefs = JobPreference(
        job_titles=["DevOps", "Engineer"],
        locations=["Bengaluru"],
        min_salary_lpa=4.0,  # Minimum disclosed salary per user rule
        employment_types=["Full Time", "Internship"],
    )
    test_session.add(prefs)
    test_session.commit()

    return profile, prefs


class TestBug1NameErrorInAbortPath:
    """Test that job_id is handled correctly in URL mode error paths."""

    @pytest.mark.asyncio
    async def test_ingest_abort_missing_company_no_nameerror(self, test_session):
        """Ingest abort with missing company should not raise NameError."""
        adapter = AsyncMock()
        page = AsyncMock()
        page.is_closed = MagicMock(return_value=False)
        page.query_selector = AsyncMock(return_value=AsyncMock())
        page.evaluate = AsyncMock(return_value="Page text")
        page.screenshot = AsyncMock()
        page.content = AsyncMock(return_value="<html></html>")
        page.close = AsyncMock()

        result = AsyncMock()
        result.security_required = False
        result.page = page
        adapter.open_job_page.return_value = result

        with patch("phase10_live_apply_launcher._extract_title_from_page", return_value="Title"):
            with patch("phase10_live_apply_launcher._extract_company_from_page", return_value=None):
                with patch("phase10_live_apply_launcher._extract_location_from_page", return_value="Location"):
                    with patch("phase10_live_apply_launcher._extract_description_from_page", return_value="Desc"):
                        url = "https://www.naukri.com/job-listings-test-240926500723"
                        job = await ingest_job_from_url(adapter, url, test_session)
                        assert job is None


class TestBug3SalaryHandling:
    """Test Unpaid salary becomes 0 and is correctly filtered."""

    @pytest.mark.asyncio
    async def test_unpaid_salary_becomes_zero(self, test_session):
        """Unpaid salary stored as salary_min=0, salary_max=0."""
        adapter = AsyncMock()
        page = AsyncMock()
        page.is_closed = MagicMock(return_value=False)
        page.query_selector = AsyncMock(return_value=AsyncMock())
        page.evaluate = AsyncMock(return_value="Unpaid")
        page.screenshot = AsyncMock()
        page.content = AsyncMock(return_value="<html></html>")
        page.close = AsyncMock()

        result = AsyncMock()
        result.security_required = False
        result.page = page
        adapter.open_job_page.return_value = result

        with patch("phase10_live_apply_launcher._extract_title_from_page", return_value="Title"):
            with patch("phase10_live_apply_launcher._extract_company_from_page", return_value="Company"):
                with patch("phase10_live_apply_launcher._extract_location_from_page", return_value="Bengaluru"):
                    with patch("phase10_live_apply_launcher._extract_description_from_page", return_value="Job desc"):
                        with patch("phase10_live_apply_launcher._extract_salary_from_page", return_value="Unpaid"):
                            url = "https://www.naukri.com/job-listings-test-240926500723"
                            job = await ingest_job_from_url(adapter, url, test_session)
                            assert job is not None
                            assert job.salary == "Unpaid"
                            assert job.salary_min == 0
                            assert job.salary_max == 0


# ============================================================================
# CHECKPOINT A: Salary Filter Alignment Tests
# ============================================================================

class TestSalaryFilterAlignmentMatchEngine:
    """Test salary filter alignment in MatchEngine (salary_max==0 -> SKIP)."""

    def test_match_engine_unpaid_salary_skipped(self, test_session, profile_and_prefs):
        """MatchEngine: Unpaid (salary_max==0) MUST be skipped - disclosed zero pay below ₹4 LPA minimum."""
        from backend.services.matching.engine import MatchEngine
        from backend.schemas.ai import JobAnalysis, AIRecommendation

        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="unpaid_job_001",
            url="https://www.naukri.com/job-listings-unpaid-job-240926500723",
            title="AWS DevOps Engineer",
            company="Acme Corp",
            description="Job description here",
            location="Bengaluru",
            salary="Unpaid",
            salary_min=0,
            salary_max=0,  # Disclosed zero pay
            experience="0-1 Yrs",
            experience_min=0,
            experience_max=1,
            employment_type="Full Time",
            industry="IT Services & Consulting",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )

        # Mock AI provider
        mock_ai = MagicMock()
        engine = MatchEngine(test_session, ai_provider=mock_ai)
        decision = engine.evaluate_job(job, profile, prefs)

        # Should skip before calling AI due to salary_max==0
        assert decision.decision.value == "SKIP", f"Unpaid job should be skipped but got: {decision.reason}"
        assert "unpaid" in decision.reason.lower(), f"Reason should mention unpaid: {decision.reason}"
        # Verify AI was not called (hard filter caught it first)
        mock_ai.analyze_job.assert_not_called()

    def test_match_engine_undisclosed_salary_not_rejected(self, test_session, profile_and_prefs):
        """MatchEngine: Undisclosed salary (NULL) MUST NOT be rejected - follows user rule."""
        from backend.services.matching.engine import MatchEngine
        from backend.schemas.ai import JobAnalysis, AIRecommendation, JobQuality

        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="undisclosed_job_001",
            url="https://www.naukri.com/job-listings-undisclosed-job-240926500723",
            title="Senior DevOps Engineer",
            company="Tech Corp",
            description="Job description here",
            location="Bengaluru",
            salary=None,  # Undisclosed
            salary_min=None,
            salary_max=None,
            experience="0-1 Yrs",
            experience_min=0,
            experience_max=1,
            employment_type="Full Time",
            industry="IT Services & Consulting",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )

        # Mock AI provider to return APPLY
        mock_ai = MagicMock()
        mock_ai.analyze_job.return_value = JobAnalysis(
            match_score=80,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality=JobQuality.GOOD,
            duplicate_probability=0.0,
            suspicious=False,
            recommendation=AIRecommendation.APPLY,
            short_reason="Good match for role"
        )

        engine = MatchEngine(test_session, ai_provider=mock_ai)
        decision = engine.evaluate_job(job, profile, prefs)

        assert decision.decision.value == "APPLY", f"Undisclosed salary should pass but got: {decision.reason}"

    def test_match_engine_good_salary_passes(self, test_session, profile_and_prefs):
        """MatchEngine: Salary ₹5 LPA passes (above minimum ₹4 LPA)."""
        from backend.services.matching.engine import MatchEngine
        from backend.schemas.ai import JobAnalysis, AIRecommendation, JobQuality

        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="good_salary_job_001",
            url="https://www.naukri.com/job-listings-good-salary-240926500723",
            title="DevOps Engineer",
            company="Tech Corp",
            description="Salary: 5-7 LPA. Job description here",
            location="Bengaluru",
            salary="5-7 LPA",
            salary_min=5.0,
            salary_max=7.0,
            experience="0-1 Yrs",
            experience_min=0,
            experience_max=1,
            employment_type="Full Time",
            industry="IT Services & Consulting",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )

        # Mock AI provider to return APPLY
        mock_ai = MagicMock()
        mock_ai.analyze_job.return_value = JobAnalysis(
            match_score=85,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality=JobQuality.GOOD,
            duplicate_probability=0.0,
            suspicious=False,
            recommendation=AIRecommendation.APPLY,
            short_reason="Excellent match for role"
        )

        engine = MatchEngine(test_session, ai_provider=mock_ai)
        decision = engine.evaluate_job(job, profile, prefs)

        assert decision.decision.value == "APPLY", f"Salary 5 LPA should pass but got: {decision.reason}"

    def test_match_engine_below_minimum_salary_skipped(self, test_session, profile_and_prefs):
        """MatchEngine: Salary ₹2-4 LPA is skipped (below minimum ₹4 LPA start point)."""
        from backend.services.matching.engine import MatchEngine

        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="low_salary_job_001",
            url="https://www.naukri.com/job-listings-low-salary-240926500723",
            title="Junior DevOps Engineer",
            company="Startup",
            description="Salary: 2-4 LPA. Job description here",
            location="Bengaluru",
            salary="2-4 LPA",
            salary_min=2.0,
            salary_max=4.0,
            experience="0-1 Yrs",
            experience_min=0,
            experience_max=1,
            employment_type="Full Time",
            industry="IT Services & Consulting",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )

        # Mock AI provider
        mock_ai = MagicMock()
        engine = MatchEngine(test_session, ai_provider=mock_ai)
        decision = engine.evaluate_job(job, profile, prefs)

        assert decision.decision.value == "SKIP", f"Salary 2-4 LPA should be skipped but got: {decision.reason}"
        assert "Salary" in decision.reason, f"Reason should mention salary: {decision.reason}"
        # Verify AI was not called (hard filter caught it first)
        mock_ai.analyze_job.assert_not_called()


class TestSalaryFilterAlignmentSafetyGate:
    """Test salary filter alignment in ApplicationService.run_final_safety_gate()."""

    def test_safety_gate_unpaid_salary_skipped(self, test_session, profile_and_prefs):
        """SafetyGate: Unpaid (salary_max==0) MUST be skipped - disclosed zero pay below ₹4 LPA minimum."""
        from backend.services.applications.service import ApplicationService

        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="unpaid_job_002",
            url="https://www.naukri.com/job-listings-unpaid-job-240926500724",
            title="AWS DevOps Engineer",
            company="Acme Corp",
            description="Job description here",
            location="Bengaluru",
            salary="Unpaid",
            salary_min=0,
            salary_max=0,  # Disclosed zero pay
            experience="0-1 Yrs",
            experience_min=0,
            experience_max=1,
            employment_type="Full Time",
            industry="IT Services & Consulting",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )
        test_session.add(job)
        test_session.commit()

        service = ApplicationService(test_session)
        allowed, reason = service.run_final_safety_gate(job, profile, prefs)

        assert not allowed, f"Unpaid job should be rejected but got: {reason}"
        assert "unpaid" in reason.lower(), f"Reason should mention unpaid: {reason}"

    def test_safety_gate_undisclosed_salary_not_rejected(self, test_session, profile_and_prefs):
        """SafetyGate: Undisclosed salary (NULL) MUST NOT be rejected."""
        from backend.services.applications.service import ApplicationService

        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="undisclosed_job_002",
            url="https://www.naukri.com/job-listings-undisclosed-job-240926500724",
            title="Senior DevOps Engineer",
            company="Tech Corp",
            description="Job description here",
            location="Bengaluru",
            salary=None,  # Undisclosed
            salary_min=None,
            salary_max=None,
            experience="0-1 Yrs",
            experience_min=0,
            experience_max=1,
            employment_type="Full Time",
            industry="IT Services & Consulting",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )
        test_session.add(job)
        test_session.commit()

        service = ApplicationService(test_session)
        allowed, reason = service.run_final_safety_gate(job, profile, prefs)

        assert allowed, f"Undisclosed salary should pass but got: {reason}"

    def test_safety_gate_good_salary_passes(self, test_session, profile_and_prefs):
        """SafetyGate: Salary ₹5 LPA passes (above minimum ₹4 LPA)."""
        from backend.services.applications.service import ApplicationService

        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="good_salary_job_002",
            url="https://www.naukri.com/job-listings-good-salary-240926500724",
            title="DevOps Engineer",
            company="Tech Corp",
            description="Salary: 5-7 LPA. Job description here",
            location="Bengaluru",
            salary="5-7 LPA",
            salary_min=5.0,
            salary_max=7.0,
            experience="0-1 Yrs",
            experience_min=0,
            experience_max=1,
            employment_type="Full Time",
            industry="IT Services & Consulting",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )
        test_session.add(job)
        test_session.commit()

        service = ApplicationService(test_session)
        allowed, reason = service.run_final_safety_gate(job, profile, prefs)

        assert allowed, f"Salary 5 LPA should pass but got: {reason}"

    def test_safety_gate_below_minimum_salary_skipped(self, test_session, profile_and_prefs):
        """SafetyGate: Salary ₹2-4 LPA is skipped (below minimum ₹4 LPA start point)."""
        from backend.services.applications.service import ApplicationService

        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="low_salary_job_002",
            url="https://www.naukri.com/job-listings-low-salary-240926500724",
            title="Junior DevOps Engineer",
            company="Startup",
            description="Salary: 2-4 LPA. Job description here",
            location="Bengaluru",
            salary="2-4 LPA",
            salary_min=2.0,
            salary_max=4.0,
            experience="0-1 Yrs",
            experience_min=0,
            experience_max=1,
            employment_type="Full Time",
            industry="IT Services & Consulting",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )
        test_session.add(job)
        test_session.commit()

        service = ApplicationService(test_session)
        allowed, reason = service.run_final_safety_gate(job, profile, prefs)

        assert not allowed, f"Salary 2-4 LPA should be rejected but got: {reason}"
        assert "Salary" in reason, f"Reason should mention salary: {reason}"


class TestSalaryFilterAlignment:
    """Test salary filter alignment: unpaid (0) SKIP, null PASS, numeric filters apply (deterministic_check)."""

    def test_hard_filter_unpaid_salary_skipped(self, test_session, profile_and_prefs):
        """Unpaid (salary_max==0) MUST be skipped - disclosed zero pay below ₹4 LPA minimum.

        User rule: minimum disclosed salary is ₹4 LPA; undisclosed is NOT rejected.
        Unpaid is disclosed 0 LPA, so it must be SKIPPED.
        """
        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="unpaid_job_001",
            url="https://www.naukri.com/job-listings-unpaid-job-240926500723",
            title="AWS DevOps Engineer",
            company="Acme Corp",
            description="Job description here",
            location="Bengaluru",
            salary="Unpaid",
            salary_min=0,
            salary_max=0,  # Disclosed zero pay
            experience="0 years",
            experience_min=2,
            experience_max=2,
            employment_type="Full Time",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )

        allowed, reason = deterministic_check(job, profile, prefs, test_session)

        # Must be rejected because salary_max==0 (disclosed unpaid)
        assert not allowed, f"Unpaid job should be skipped but got: {reason}"
        assert "unpaid" in reason.lower(), f"Reason should mention unpaid: {reason}"

    def test_hard_filter_undisclosed_salary_not_rejected(self, test_session, profile_and_prefs):
        """Undisclosed salary (NULL) MUST NOT be rejected - follows user rule.

        User rule: undisclosed salary is NOT rejected.
        """
        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="undisclosed_job_001",
            url="https://www.naukri.com/job-listings-undisclosed-job-240926500723",
            title="Senior DevOps Engineer",
            company="Tech Corp",
            description="Job description here",
            location="Bengaluru",
            salary=None,  # Undisclosed
            salary_min=None,
            salary_max=None,
            experience="0 years",  # Match profile experience (5 years >= 2 + tolerance)
            experience_min=2,
            experience_max=2,
            employment_type="Full Time",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )

        allowed, reason = deterministic_check(job, profile, prefs, test_session)

        # Must pass because salary is undisclosed (NULL)
        assert allowed, f"Undisclosed salary should pass but got: {reason}"

    def test_hard_filter_good_salary_passes(self, test_session, profile_and_prefs):
        """Salary ₹5 LPA passes (above minimum ₹4 LPA).

        User rule: minimum disclosed salary is ₹4 LPA.
        """
        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="good_salary_job_001",
            url="https://www.naukri.com/job-listings-good-salary-240926500723",
            title="DevOps Engineer",
            company="Tech Corp",
            description="Job description here",
            location="Bengaluru",
            salary="5-7 LPA",
            salary_min=5.0,
            salary_max=7.0,
            experience="3 years",
            experience_min=3,
            experience_max=3,
            employment_type="Full Time",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )

        allowed, reason = deterministic_check(job, profile, prefs, test_session)

        # Must pass because salary 5 LPA >= minimum 4 LPA
        assert allowed, f"Salary 5 LPA should pass but got: {reason}"

    def test_hard_filter_below_minimum_salary_skipped(self, test_session, profile_and_prefs):
        """Salary ₹2-4 LPA is skipped (below minimum ₹4 LPA start point).

        User rule: "₹2-4 LPA" is a skip.
        """
        profile, prefs = profile_and_prefs

        job = Job(
            platform="naukri",
            external_job_id="low_salary_job_001",
            url="https://www.naukri.com/job-listings-low-salary-240926500723",
            title="Junior DevOps Engineer",
            company="Startup",
            description="Job description here",
            location="Bengaluru",
            salary="2-4 LPA",
            salary_min=2.0,
            salary_max=4.0,
            experience="1 year",
            experience_min=1,
            experience_max=1,
            employment_type="Full Time",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )

        allowed, reason = deterministic_check(job, profile, prefs, test_session)

        # Must be rejected because salary 2 LPA < minimum 4 LPA
        assert not allowed, f"Salary 2-4 LPA should be skipped but got: {reason}"
        assert "Salary" in reason, f"Reason should mention salary: {reason}"


class TestExtractionWithRealFixture:
    """Test extraction using real saved fixture page (personal data masked)."""

    @pytest.mark.asyncio
    async def test_extract_from_fixture_page(self, test_session):
        """Extract fields from real saved fixture HTML (missing company case).

        Expected: title="AWS DevOps Engineer", company=None (missing),
                  location="Bengaluru", experience="2yr", employment_type="Internship",
                  salary="Unpaid" -> salary_min=0, salary_max=0
        """
        fixture_path = Path("data/ingest_abort_missing_required_fields_20261002_095524_CLEANED.html")

        if not fixture_path.exists():
            pytest.skip(f"Fixture file not found: {fixture_path}")

        # Load real HTML fixture
        fixture_html = fixture_path.read_text(encoding='utf-8')

        # Create mock page with real HTML content
        adapter = AsyncMock()
        page = AsyncMock()
        page.is_closed = MagicMock(return_value=False)
        page.content = AsyncMock(return_value=fixture_html)
        page.screenshot = AsyncMock()
        page.close = AsyncMock()

        # Mock query_selector to return None (no visible elements in fixture)
        page.query_selector = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=[])
        page.evaluate = AsyncMock(return_value="AWS DevOps Engineer 2yr Bengaluru Internship Unpaid")

        result = AsyncMock()
        result.security_required = False
        result.page = page

        adapter.open_job_page.return_value = result

        # Ingest should abort with missing company
        url = "https://www.naukri.com/job-listings-aws-devops-engineer-quadrasystems-net-bengaluru-0-to-1-years-240926500723"
        job = await ingest_job_from_url(adapter, url, test_session)

        # Fixture missing company, so abort expected
        assert job is None, "Should abort due to missing company"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
