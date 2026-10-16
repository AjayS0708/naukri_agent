"""E5-R30: job-preference salary threshold 4 -> 3 LPA.

The threshold has a single source of truth (``evaluate_salary_gate`` in the
shared normalizer), the persisted preference row, and the preferences form
default. These tests pin the new 3 LPA boundary from all three angles:

- gate boundaries around 3 LPA (reject below, allow at/above, unpaid
  rejects, undisclosed/ambiguous never rejects),
- the same boundary end-to-end through ``MatchEngine.evaluate_job_deterministic``
  (the gate the runner and manual queue both run),
- the environment defaults: ``job_preferences.min_salary_lpa`` in the local
  database and the frontend form's initial value.
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.services.matching.engine import MatchEngine
from backend.services.matching.normalizer import evaluate_salary_gate

TEST_DATABASE_URL = "sqlite:///:memory:"
REPO_ROOT = Path(__file__).resolve().parents[2]


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
def confirmed_profile(db_session: Session) -> Profile:
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
        data={"name": "Test User", "skills": ["Python", "SQL"], "location": "Bengaluru"},
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def preferences_3lpa(db_session: Session) -> JobPreference:
    preferences = JobPreference(
        locations=["Bengaluru", "Remote"],
        job_titles=["Data Analyst", "Software Engineer"],
        employment_types=["Full-time"],
        min_salary_lpa=3.0,
        aggressiveness="BALANCED",
    )
    db_session.add(preferences)
    db_session.commit()
    db_session.refresh(preferences)
    return preferences


def _make_job(db_session: Session, *, salary: str, salary_max: float | None) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"salary{int((salary_max or 0) * 100)}{salary[:2]}",
        url=f"https://www.naukri.com/salary-{int((salary_max or 0) * 100)}",
        title="Data Analyst",
        company="Acme Analytics",
        description="Python and SQL reporting role",
        location="Bengaluru",
        salary=salary,
        salary_max=salary_max,
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
        application_mode="NAUKRI_NATIVE",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


class TestSalaryGateBoundaries:
    """Boundary behavior of the shared disclosed-salary gate at 3 LPA."""

    def test_disclosed_below_3_rejected(self) -> None:
        passed, reason = evaluate_salary_gate("2-3 LPA", 3.0, 3.0)
        assert passed is False
        assert reason is not None

    def test_fractional_below_3_rejected(self) -> None:
        passed, reason = evaluate_salary_gate("2.99 LPA", 2.99, 3.0)
        assert passed is False
        assert reason is not None

    def test_exactly_3_allowed(self) -> None:
        passed, reason = evaluate_salary_gate("3-5 LPA", 5.0, 3.0)
        assert passed is True
        assert reason is None

    def test_above_3_allowed(self) -> None:
        passed, reason = evaluate_salary_gate("3.5-4.5 LPA", 4.5, 3.0)
        assert passed is True
        assert reason is None

    def test_old_threshold_value_still_allowed(self) -> None:
        """Jobs that passed under the old 4 LPA minimum still pass."""
        passed, reason = evaluate_salary_gate("4-6 LPA", 6.0, 3.0)
        assert passed is True
        assert reason is None

    def test_unpaid_rejected(self) -> None:
        passed, reason = evaluate_salary_gate("Unpaid", 0.0, 3.0)
        assert passed is False
        assert reason is not None

    def test_zero_floor_rejected(self) -> None:
        passed, reason = evaluate_salary_gate("0 LPA", 0.0, 3.0)
        assert passed is False
        assert reason is not None

    def test_undisclosed_salary_never_rejects(self) -> None:
        passed, reason = evaluate_salary_gate("Not disclosed", None, 3.0)
        assert passed is True
        assert reason is None

    def test_missing_salary_never_rejects(self) -> None:
        passed, reason = evaluate_salary_gate(None, None, 3.0)
        assert passed is True
        assert reason is None

    def test_no_threshold_configured_never_rejects(self) -> None:
        passed, reason = evaluate_salary_gate("2-3 LPA", 3.0, None)
        assert passed is True
        assert reason is None


class TestDeterministicGateAt3Lpa:
    """End-to-end: the engine's hard filter uses the same 3 LPA boundary."""

    def test_below_minimum_job_hard_filtered(
        self, db_session: Session, confirmed_profile: Profile, preferences_3lpa: JobPreference
    ) -> None:
        _make_job(db_session, salary="2-3 LPA", salary_max=3.0)
        decision = MatchEngine(db_session).evaluate_job_deterministic(
            db_session.execute(select(Job)).scalars().first(),
            confirmed_profile,
            preferences_3lpa,
        )
        assert decision.decision.value != "APPLY"

    def test_at_minimum_job_allowed(
        self, db_session: Session, confirmed_profile: Profile, preferences_3lpa: JobPreference
    ) -> None:
        _make_job(db_session, salary="3-5 LPA", salary_max=5.0)
        decision = MatchEngine(db_session).evaluate_job_deterministic(
            db_session.execute(select(Job)).scalars().first(),
            confirmed_profile,
            preferences_3lpa,
        )
        assert decision.decision.value == "APPLY", decision.reason

    def test_control_job_well_above_threshold_allowed(
        self, db_session: Session, confirmed_profile: Profile, preferences_3lpa: JobPreference
    ) -> None:
        _make_job(db_session, salary="5-7 LPA", salary_max=7.0)
        decision = MatchEngine(db_session).evaluate_job_deterministic(
            db_session.execute(select(Job)).scalars().first(),
            confirmed_profile,
            preferences_3lpa,
        )
        assert decision.decision.value == "APPLY", decision.reason


class TestEnvironmentDefaults:
    def test_local_preference_row_is_3_lpa(self) -> None:
        """The persisted active preference row uses the new threshold."""
        db_path = REPO_ROOT / "data" / "naukri_agent.db"
        if not db_path.exists():
            pytest.skip("local database not present")
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT id, min_salary_lpa FROM job_preferences"
            ).fetchall()
        finally:
            conn.close()
        assert rows, "no job_preferences row found"
        for _row_id, value in rows:
            assert value == 3, f"expected min_salary_lpa=3, found {value}"

    def test_frontend_default_is_3(self) -> None:
        """The preferences form's initial value matches the threshold."""
        form = REPO_ROOT / "frontend" / "src" / "components" / "JobPreferences.tsx"
        if not form.exists():
            pytest.skip("frontend not present")
        content = form.read_text(encoding="utf-8")
        assert 'min_salary_lpa: "3"' in content

    def test_preferences_endpoint_tolerates_null_it_lists(self, client, db) -> None:
        """E5-R30 regression: a preference row whose IT allowlist columns are
        NULL (rows predating those columns) must still serve the preferences
        endpoint — the queue/settings UI reads it to show the threshold."""
        db.add(
            JobPreference(
                locations=["Bengaluru"],
                job_titles=["Data Analyst"],
                employment_types=["Full-time"],
                min_salary_lpa=3.0,
                aggressiveness="BALANCED",
                it_industry_allowlist=None,
                it_keyword_list=None,
            )
        )
        db.commit()

        response = client.get("/api/matching/preferences")

        assert response.status_code == 200
        body = response.json()
        assert body["min_salary_lpa"] == 3.0
        assert body["locations"] == ["Bengaluru"]
