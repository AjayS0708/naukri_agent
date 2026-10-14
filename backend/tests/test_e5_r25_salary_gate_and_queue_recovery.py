"""E5-R25: salary gate consistency + existing-job queue recovery.

Evidence from controlled live run #87 (2026-10-14):

1. Queue-recovery defect — the enqueue stage hard-filtered to the current
   run's current_run_job_ids and the candidate query additionally required
   application_mode == 'NAUKRI_NATIVE', so 64 eligible, unattempted jobs
   discovered in earlier runs (including job #503 "MACHINE LEARNING - TRAINEE
   ENG" and #527 "Business Analyst", both NAUKRI_NATIVE) never re-entered the
   pipeline unless a later search re-listed them. Run #87 scanned 561 cards of
   which 552 were duplicates.
2. Salary-parse defects — bare annual rupees ("60,000-80,000 PA",
   "50,000 PA") parsed to (None, None), so disclosed-but-malformed postings
   slipped past the disclosed-salary floor; mixed-unit strings
   ("50,000-3 Lacs PA") parsed to (3.0, 50000.0), a 16,000x range error.
   A missing salary (undisclosed) must NEVER be treated as below-minimum —
   only a disclosed value may reject.

Browser behavior is mocked: no live Naukri pages, no apply clicks, no
credential or application-record changes.
"""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job, utc_now
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.services.applications.runner import ApplicationRunner
from backend.services.agent_state import AgentStateManager
from backend.services.autonomous_cycle.service import (
    AutonomousCycle,
    MAX_RECOVERY_JOBS_PER_RUN,
    MAX_RECOVERY_MODE_REVERIFY_PER_RUN,
    RECOVERY_MODE_REVERIFY_COOLDOWN,
)
from backend.services.decision.quality import DecisionQualityService
from backend.services.matching.engine import MatchEngine
from backend.services.matching.normalizer import (
    evaluate_salary_gate,
    parse_salary_to_range,
)
from backend.schemas.ai import AIRecommendation, JobQuality
from backend.schemas.application import ApplicationStatus
from backend.services.naukri.adapter import JobPageResult

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
            "location": "Bengaluru",
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
        job_titles=["Software Engineer", "Data Analyst", "Data Scientist"],
        employment_types=["Full-time", "Contract"],
        min_salary_lpa=4.0,
        aggressiveness="BALANCED",
    )
    db_session.add(preferences)
    db_session.commit()
    db_session.refresh(preferences)
    return preferences


def _make_job(
    db_session: Session,
    index: int,
    *,
    title: str = "Data Analyst",
    description: str = "Python developer role",
    salary: str | None = "5-7 LPA",
    salary_max: float | None = 7.0,
    application_mode: str | None = "NAUKRI_NATIVE",
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"e5r25job{index}",
        url=f"https://www.naukri.com/e5r25job{index}",
        title=title,
        company=f"Company {index}",
        description=description,
        location="Bengaluru",
        salary=salary,
        salary_max=salary_max,
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
        application_mode=application_mode,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_analysis(db_session: Session, job_id: int) -> None:
    db_session.add(
        JobAnalysisModel(
            job_id=job_id,
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
            short_reason="good match",
            model="gemini",
            prompt_version="v1",
        )
    )
    db_session.commit()


def _make_run(db_session: Session, jobs: list[Job]) -> DiscoveryRun:
    run = DiscoveryRun(
        status="COMPLETED",
        jobs_discovered=len(jobs),
        current_run_job_ids=",".join(str(job.id) for job in jobs),
    )
    db_session.add(run)
    db_session.commit()
    return run


def _make_cycle(db_session: Session, jobs: list[Job]) -> AutonomousCycle:
    for job in jobs:
        _make_analysis(db_session, job.id)
    run = _make_run(db_session, jobs)
    cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
    cycle.current_discovery_run = run
    return cycle


# ── Parser: unit-aware salary parsing ─────────────────────────────────────


class TestSalaryParser:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("60,000-80,000 PA", (0.6, 0.8)),
            ("50,000 PA", (0.5, 0.5)),
            ("1,20,000 - 1,80,000 PA", (1.2, 1.8)),
            ("50,000/month", (6.0, 6.0)),
            ("Rs 15,000 - 20,000 per month", (1.8, 2.4)),
            ("15,000 p.m.", (1.8, 1.8)),
            ("30,000-50,000/month", (3.6, 6.0)),
            ("50,000-3 Lacs PA", (0.5, 3.0)),
            ("90,000-1.25 Lacs PA", (0.9, 1.25)),
            ("80,000-1.5 Lacs PA", (0.8, 1.5)),
            ("50,000-2.25 Lacs PA", (0.5, 2.25)),
            ("50,000-2 Lacs PA", (0.5, 2.0)),
        ],
    )
    def test_disclosed_salaries_parse_to_sane_lpa(self, raw, expected):
        """Bare annual rupees, monthly, and mixed-unit ranges parse correctly."""
        low, high = parse_salary_to_range(raw)
        assert low is not None and high is not None, raw
        assert low == pytest.approx(expected[0]), raw
        assert high == pytest.approx(expected[1]), raw

    @pytest.mark.parametrize(
        "raw",
        ["Not disclosed", "Undisclosed", "", None, "50,000-80,000", "1-2"],
    )
    def test_unknown_salary_is_never_fabricated(self, raw):
        """Unknown/ambiguous salary yields (None, None), never a fake number."""
        assert parse_salary_to_range(raw) == (None, None)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Unpaid", (0.0, 0.0)),
            ("unpaid", (0.0, 0.0)),
            ("Unpaid P.M", (0.0, 0.0)),
            ("3-5 Lacs PA", (3.0, 5.0)),
            ("5-7 LPA", (5.0, 7.0)),
            ("5 LPA", (5.0, 5.0)),
            ("₹4 LPA", (4.0, 4.0)),
            ("400000 to 600000", (4.0, 6.0)),
        ],
    )
    def test_existing_behaviors_are_preserved(self, raw, expected):
        low, high = parse_salary_to_range(raw)
        assert low == pytest.approx(expected[0]), raw
        assert high == pytest.approx(expected[1]), raw


# ── Shared gate: one decision, three stages ───────────────────────────────


class TestSharedSalaryGate:
    @pytest.mark.parametrize(
        "salary_text,salary_max",
        [
            (None, None),
            ("Not disclosed", None),
            ("Undisclosed", None),
            ("50,000-80,000", None),
            ("", None),
        ],
    )
    def test_undisclosed_salary_passes_the_gate(self, salary_text, salary_max):
        passed, reason = evaluate_salary_gate(salary_text, salary_max, 4.0)
        assert passed is True
        assert reason is None

    def test_disclosed_below_minimum_is_rejected_with_reason(self):
        passed, reason = evaluate_salary_gate("2-3 Lacs PA", 3.0, 4.0)
        assert passed is False
        assert "below minimum" in reason.lower()
        assert "salary" in reason.lower()

    def test_disclosed_at_or_above_minimum_passes(self):
        assert evaluate_salary_gate("5-7 LPA", 7.0, 4.0)[0] is True
        assert evaluate_salary_gate("4 LPA", 4.0, 4.0)[0] is True

    def test_unpaid_is_rejected_with_unpaid_reason(self):
        passed, reason = evaluate_salary_gate("Unpaid", 0.0, 4.0)
        assert passed is False
        assert "unpaid" in reason.lower()

    def test_malformed_bare_rupees_below_floor_is_rejected(self):
        """The parser fix means disclosed 60k PA now rejects below 4 LPA."""
        passed, reason = evaluate_salary_gate("60,000-80,000 PA", 0.8, 4.0)
        assert passed is False
        assert "below minimum" in reason.lower()

    def test_no_min_preference_never_rejects(self):
        assert evaluate_salary_gate("2 LPA", 2.0, None)[0] is True


class TestStagesAgreeOnTheSameJob:
    """The deterministic filter, safety gate, and quality scoring must
    return the same salary verdict for the same job (E5-R25)."""

    @staticmethod
    def _persist_job(
        db_session: Session,
        index: int,
        salary,
        salary_max,
    ) -> Job:
        job = _make_job(
            db_session,
            index,
            title="Data Analyst",
            salary=salary,
            salary_max=salary_max,
        )
        return job

    @pytest.mark.asyncio
    async def test_undisclosed_salary_is_not_rejected_by_any_stage(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = self._persist_job(db_session, 50, None, None)

        engine = MatchEngine(db_session)
        decision = engine.evaluate_job_deterministic(
            job, confirmed_profile, job_preferences
        )
        assert decision.decision.value == "APPLY", decision.reason

        from backend.services.applications.service import ApplicationService

        allowed, reason = ApplicationService(db_session).run_final_safety_gate(
            job, confirmed_profile, job_preferences, None
        )
        assert allowed is True, reason

        from backend.services.decision.quality import DecisionQualityService

        quality = DecisionQualityService(db_session).evaluate_job_decision(
            job, confirmed_profile, job_preferences
        )
        assert quality.hard_filter_failed is False

    @pytest.mark.asyncio
    async def test_below_minimum_is_rejected_by_every_stage(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = self._persist_job(db_session, 51, "2-3 Lacs PA", 3.0)

        engine = MatchEngine(db_session)
        decision = engine.evaluate_job_deterministic(
            job, confirmed_profile, job_preferences
        )
        assert decision.decision.value == "SKIP"
        assert "below minimum" in decision.reason.lower()

        from backend.services.applications.service import ApplicationService

        allowed, reason = ApplicationService(db_session).run_final_safety_gate(
            job, confirmed_profile, job_preferences, None
        )
        assert allowed is False
        assert "below minimum" in reason.lower()

        from backend.services.decision.quality import DecisionQualityService

        quality = DecisionQualityService(db_session).evaluate_job_decision(
            job, confirmed_profile, job_preferences
        )
        assert quality.hard_filter_failed is True
        assert quality.priority.value == "HARD_REJECT"

    @pytest.mark.asyncio
    async def test_unpaid_is_rejected_by_every_stage(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = self._persist_job(db_session, 52, "Unpaid", 0.0)

        engine = MatchEngine(db_session)
        decision = engine.evaluate_job_deterministic(
            job, confirmed_profile, job_preferences
        )
        assert decision.decision.value == "SKIP"
        assert "unpaid" in decision.reason.lower()

        from backend.services.applications.service import ApplicationService

        allowed, reason = ApplicationService(db_session).run_final_safety_gate(
            job, confirmed_profile, job_preferences, None
        )
        assert allowed is False
        assert "unpaid" in reason.lower()

        from backend.services.decision.quality import DecisionQualityService

        quality = DecisionQualityService(db_session).evaluate_job_decision(
            job, confirmed_profile, job_preferences
        )
        assert quality.hard_filter_failed is True


# ── Existing-job recovery stage ───────────────────────────────────────────


class TestRecoverySelectsEligibleUnattemptedJobs:
    @pytest.mark.asyncio
    async def test_native_job_outside_current_run_is_recovered(
        self, db_session, confirmed_profile, job_preferences
    ):
        """A job discovered earlier, never attempted, is selected."""
        current_job = _make_job(db_session, 1, title="Data Analyst")
        backlog = _make_job(db_session, 2, title="Data Analyst")
        cycle = _make_cycle(db_session, [current_job])  # only job 1 in current run
        db_session.add(backlog)  # job 2 exists but is not in the run

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert backlog.id in cycle._recovery_job_ids
        assert current_job.id not in cycle._recovery_job_ids
        assert stats["recovery_candidates"] == 1
        assert stats["recovery_native"] == 1

    @pytest.mark.asyncio
    async def test_current_run_jobs_are_never_recovery_candidates(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 3, title="Data Analyst")
        cycle = _make_cycle(db_session, [job])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert job.id not in cycle._recovery_job_ids
        assert stats["recovery_candidates"] == 0

    @pytest.mark.asyncio
    async def test_applied_job_is_protected_from_recovery(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 4, title="Data Analyst")
        cycle = _make_cycle(db_session, [_make_job(db_session, 5)])
        db_session.add(
            Application(
                job_id=job.id,
                status=ApplicationStatus.APPLIED.value,
                applied_at=utc_now(),
            )
        )
        db_session.commit()

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert job.id not in cycle._recovery_job_ids
        assert stats["recovery_candidates"] == 0

    @pytest.mark.asyncio
    async def test_externally_classified_job_is_never_recovered(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Stored EXTERNAL classification came from positive destination
        evidence; native-only recovery must not override it."""
        external = _make_job(db_session, 6, application_mode="EXTERNAL")
        cycle = _make_cycle(db_session, [_make_job(db_session, 7)])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert external.id not in cycle._recovery_job_ids
        assert stats["recovery_candidates"] == 0

    @pytest.mark.asyncio
    async def test_below_minimum_salary_is_filtered_out_of_recovery(
        self, db_session, confirmed_profile, job_preferences
    ):
        low = _make_job(db_session, 8, salary="2 LPA", salary_max=2.0)
        cycle = _make_cycle(db_session, [_make_job(db_session, 9)])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert low.id not in cycle._recovery_job_ids
        assert stats["recovery_filtered"] >= 1

    @pytest.mark.asyncio
    async def test_undisclosed_salary_job_is_recovered(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Job #503 ML Trainee / #527 Business Analyst: undisclosed salary
        must not keep an otherwise-eligible job out of recovery."""
        undisclosed = _make_job(
            db_session, 10, salary=None, salary_max=None
        )
        cycle = _make_cycle(db_session, [_make_job(db_session, 11)])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert undisclosed.id in cycle._recovery_job_ids
        assert stats["recovery_candidates"] == 1

    @pytest.mark.asyncio
    async def test_ambiguous_mode_job_goes_to_reverify_bucket(
        self, db_session, confirmed_profile, job_preferences
    ):
        """AMBIGUOUS / NULL-mode jobs are recovered only for a bounded live
        mode re-verification, not treated as native."""
        ambiguous = _make_job(db_session, 12, application_mode="AMBIGUOUS")
        null_mode = _make_job(db_session, 13, application_mode=None)
        cycle = _make_cycle(db_session, [_make_job(db_session, 14)])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert ambiguous.id in cycle._recovery_job_ids
        assert null_mode.id in cycle._recovery_job_ids
        assert stats["recovery_mode_reverify"] == 2
        assert stats["recovery_native"] == 0

    @pytest.mark.asyncio
    async def test_cooldown_prevents_revisiting_still_ambiguous_jobs(
        self, db_session, confirmed_profile, job_preferences
    ):
        """A job whose live page was already re-checked recently and stayed
        ambiguous is skipped so the budget reaches the rest of the backlog."""
        recent = _make_job(db_session, 15, application_mode="AMBIGUOUS")
        recent.mode_reverified_at = utc_now()
        expired = _make_job(db_session, 16, application_mode="AMBIGUOUS")
        expired.mode_reverified_at = utc_now() - RECOVERY_MODE_REVERIFY_COOLDOWN - timedelta(hours=1)
        never = _make_job(db_session, 17, application_mode=None)
        db_session.commit()
        cycle = _make_cycle(db_session, [_make_job(db_session, 18)])

        await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert recent.id not in cycle._recovery_job_ids
        assert expired.id in cycle._recovery_job_ids
        assert never.id in cycle._recovery_job_ids

    @pytest.mark.asyncio
    async def test_recovery_budget_is_bounded(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Per-run caps keep one Start action from visiting the whole backlog."""
        filler = _make_job(db_session, 99)
        jobs = [
            _make_job(db_session, 100 + i, title="Data Analyst")
            for i in range(MAX_RECOVERY_JOBS_PER_RUN + 5)
        ]
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert stats["recovery_native"] <= MAX_RECOVERY_JOBS_PER_RUN
        assert stats["recovery_candidates"] <= (
            MAX_RECOVERY_JOBS_PER_RUN + MAX_RECOVERY_MODE_REVERIFY_PER_RUN
        )
        assert len(cycle._recovery_job_ids) <= (
            MAX_RECOVERY_JOBS_PER_RUN + MAX_RECOVERY_MODE_REVERIFY_PER_RUN
        )

    @pytest.mark.asyncio
    async def test_apply_loop_includes_recovery_candidates(
        self, db_session, confirmed_profile, job_preferences
    ):
        """_run_applications merges recovery IDs into the candidate set."""
        current = _make_job(db_session, 30, title="Data Analyst")
        backlog = _make_job(db_session, 31, title="Data Analyst")
        cycle = _make_cycle(db_session, [current])  # backlog not in run
        _make_analysis(db_session, backlog.id)
        visited: list[int] = []

        async def _fake_process(db, job, profile, preferences):
            visited.append(job.id)
            cycle.tracker.add_decision(
                job.id, job.company, job.title, "NATIVE",
                True, True, True, "APPLY", "PASSED", "APPLIED",
            )
            return "APPLIED"

        # Recovery selected the backlog job.
        await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )
        assert backlog.id in cycle._recovery_job_ids

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert backlog.id in visited
        assert stats["candidates"] == 2
        assert stats["applied"] == 2

    @pytest.mark.asyncio
    async def test_enqueue_stage_merges_recovery_stats(
        self, db_session, confirmed_profile, job_preferences
    ):
        """_apply_hard_filters_and_enqueue surfaces recovery counters."""
        current = _make_job(db_session, 40, title="Data Analyst")
        backlog = _make_job(db_session, 41, title="Data Analyst")
        _make_analysis(db_session, current.id)
        _make_analysis(db_session, backlog.id)
        _make_run(db_session, [current])
        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        cycle.current_discovery_run = db_session.execute(
            select(DiscoveryRun)
        ).scalars().first()

        stats = await cycle._apply_hard_filters_and_enqueue(
            db_session, confirmed_profile, job_preferences
        )

        assert stats["recovery_candidates"] == 1
        assert backlog.id in cycle._recovery_job_ids


# ── Runner: evidence-based mode correction ────────────────────────────────


class TestRunnerModeCorrection:
    @staticmethod
    def _runner(db_session: Session) -> ApplicationRunner:
        return ApplicationRunner(db_session, AgentStateManager())

    @staticmethod
    def _prepare_job(
        db_session: Session,
        *,
        application_mode: str | None,
        salary: str = "5-7 LPA",
        salary_max: float = 7.0,
    ) -> Job:
        job = Job(
            platform="naukri",
            external_job_id="e5r25mode1",
            url="https://www.naukri.com/e5r25mode1",
            title="Data Analyst",
            company="Acme",
            description="Python developer role",
            location="Bengaluru",
            salary=salary,
            salary_max=salary_max,
            experience="0-2 years",
            employment_type="Full-time",
            status="DISCOVERED",
            application_mode=application_mode,
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        _make_analysis(db_session, job.id)
        return job

    @pytest.mark.asyncio
    async def test_ambiguous_job_upgraded_to_native_on_live_evidence(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = self._prepare_job(db_session, application_mode="AMBIGUOUS")
        runner = self._runner(db_session)

        with patch(
            "backend.services.applications.runner.NaukriAdapter.start_session",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.stop_session",
            new_callable=AsyncMock,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.open_job_page",
            new_callable=AsyncMock,
        ) as mock_open, patch(
            "backend.services.applications.runner.NaukriAdapter.detect_login_state",
            new_callable=AsyncMock, return_value={"authenticated": True},
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.detect_application_type",
            new_callable=AsyncMock, return_value="NAUKRI_NATIVE",
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.start_application",
            new_callable=AsyncMock,
        ) as mock_start, patch(
            "backend.services.applications.runner.NaukriAdapter.is_conversational_apply",
            new_callable=AsyncMock, return_value=False,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.detect_application_questions",
            new_callable=AsyncMock, return_value=[],
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.submit_application",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.confirm_submission",
            new_callable=AsyncMock, return_value=True,
        ):
            from backend.schemas.application import ApplicationStartResult

            mock_open.return_value = JobPageResult(page=MagicMock(), security_required=False)
            mock_start.return_value = ApplicationStartResult.FORM_OPENED
            await runner.run_applications([job.id])

        db_session.refresh(job)
        assert job.application_mode == "NAUKRI_NATIVE"
        assert job.mode_reverified_at is not None

    @pytest.mark.asyncio
    async def test_stored_native_mode_is_never_downgraded(
        self, db_session, confirmed_profile, job_preferences
    ):
        """A stored NAUKRI_NATIVE is authoritative; a transient AMBIGUOUS
        live read must not overwrite it."""
        job = self._prepare_job(db_session, application_mode="NAUKRI_NATIVE")
        runner = self._runner(db_session)

        with patch(
            "backend.services.applications.runner.NaukriAdapter.start_session",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.stop_session",
            new_callable=AsyncMock,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.open_job_page",
            new_callable=AsyncMock,
        ) as mock_open, patch(
            "backend.services.applications.runner.NaukriAdapter.detect_login_state",
            new_callable=AsyncMock, return_value={"authenticated": True},
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.detect_application_type",
            new_callable=AsyncMock, return_value="AMBIGUOUS",
        ):
            mock_open.return_value = JobPageResult(page=MagicMock(), security_required=False)
            await runner.run_applications([job.id])

        db_session.refresh(job)
        assert job.application_mode == "NAUKRI_NATIVE"

    @pytest.mark.asyncio
    async def test_ambiguous_outcome_stamps_cooldown_without_applying(
        self, db_session, confirmed_profile, job_preferences
    ):
        """AMBIGUOUS returns NEEDS_ATTENTION but stamps mode_reverified_at so
        the recovery cooldown stops re-visiting the same posting."""
        job = self._prepare_job(db_session, application_mode="AMBIGUOUS")
        runner = self._runner(db_session)

        with patch(
            "backend.services.applications.runner.NaukriAdapter.start_session",
            new_callable=AsyncMock, return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.stop_session",
            new_callable=AsyncMock,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.open_job_page",
            new_callable=AsyncMock,
        ) as mock_open, patch(
            "backend.services.applications.runner.NaukriAdapter.detect_login_state",
            new_callable=AsyncMock, return_value={"authenticated": True},
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.detect_application_type",
            new_callable=AsyncMock, return_value="AMBIGUOUS",
        ):
            mock_page = MagicMock()
            mock_page.close = AsyncMock()
            mock_open.return_value = JobPageResult(page=mock_page, security_required=False)
            stats = await runner.run_applications([job.id])

        db_session.refresh(job)
        assert stats.get("needs_attention", 0) == 1
        assert job.mode_reverified_at is not None
        # No application row was created on the ambiguous path.
        assert (
            db_session.execute(
                select(Application).where(Application.job_id == job.id)
            ).scalars().all()
            == []
        )
