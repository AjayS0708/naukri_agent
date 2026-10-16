"""E5-R31: batch processing, session-loss recovery and outcome truthfulness.

Covers the failure mode of manual run ``cycle-1792130015478-27824`` (61
requested, 1 applied + 1 skipped shown, 59 jobs silently dead) with a fully
mocked browser (no live Naukri pages, no apply clicks, no discovery):

- A browser session that dies **before any attempt** is restarted mid-run and
  the same job is retried once; the rest of the batch keeps processing. The
  restart budget is bounded per run, and exhaustion/failure records truthful
  SKIPPED rows (never fabricated outcomes, never an ambiguous retry).
- A session death **after an attempt row exists** is ambiguous: NEEDS_ATTENTION,
  no restart, no retry.
- Every accepted job lands in exactly one terminal bucket
  (``outcome_total == processed``, ``requested = processed +
  cancelled_remaining``) and counters agree with the rows they summarize
  (SKIPPED row -> SKIPPED outcome, NEEDS_ATTENTION row -> NEEDS_ATTENTION or
  SECURITY_REQUIRED, never FAILED).
- Stop is honored at the job boundary: remaining jobs stay unstarted and are
  reported as ``cancelled_remaining`` with no rows written.
- The inter-job pacing delay is applied only after a job that actually used
  the browser (pre-attempt rejections no longer pay 2s each), stage timings
  are reported in ``stage_seconds``, and ``job_started`` carries the job
  title for the dashboard.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.schemas.application import ApplicationStartResult, ApplicationStatus
from backend.services.agent_state import AgentStateManager
from backend.services.applications.runner import ApplicationRunner
from backend.services.naukri.adapter import NaukriAdapter

TEST_DATABASE_URL = "sqlite:///:memory:"

SESSION_LOST_MESSAGE = (
    "BrowserContext.new_page: Target page, context or browser has been closed"
)


class _FakeJobPage:
    """Minimal stand-in for the Playwright page the runner closes in `finally`."""

    async def close(self) -> None:
        return None


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
        data={"name": "Test User", "skills": ["Python", "SQL"], "location": "Bengaluru"},
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def job_preferences(db_session: Session):
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


def _make_job(
    db_session: Session,
    index: int,
    *,
    application_mode: str | None = "NAUKRI_NATIVE",
    status: str = "DISCOVERED",
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"e5r31job{index}",
        url=f"https://www.naukri.com/e5r31job{index}",
        title="Data Analyst",
        company=f"Company {index}",
        description="Python and SQL reporting role",
        location="Bengaluru",
        salary="5-7 LPA",
        salary_max=7.0,
        experience="0-2 years",
        employment_type="Full-time",
        status=status,
        application_mode=application_mode,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _seed_analysis(db_session: Session, job: Job) -> None:
    """Same conservative deterministic-fallback row the cycle writes."""
    db_session.add(
        JobAnalysisModel(
            job_id=job.id,
            match_score=50,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality="GOOD",
            duplicate_probability=0.0,
            suspicious=False,
            recommendation="APPLY",
            short_reason="Deterministic filter pass (no AI analysis)",
            model="deterministic_fallback",
            prompt_version="n/a",
        )
    )
    db_session.commit()


def _applied_adapter() -> SimpleNamespace:
    """Adapter double whose happy path ends in a confirmed APPLIED."""
    page = _FakeJobPage()
    opened = SimpleNamespace(page=page, security_required=False, security_reason=None)
    return SimpleNamespace(
        open_job_page=AsyncMock(return_value=opened),
        detect_login_state=AsyncMock(return_value={"authenticated": True}),
        detect_expired_listing=AsyncMock(return_value=None),
        detect_application_type=AsyncMock(return_value="NAUKRI_NATIVE"),
        get_external_redirect_url=AsyncMock(return_value=None),
        detect_applied_state=AsyncMock(return_value=(True, "clicked apply")),
        start_application=AsyncMock(return_value=ApplicationStartResult.APPLIED),
        close_page=AsyncMock(),
        stop_session=AsyncMock(return_value=None),
        start_session=AsyncMock(return_value=True),
        last_startup_error=None,
    )


def _make_runner(
    db_session: Session,
    *,
    progress_hook=None,
    cancel_check=None,
) -> ApplicationRunner:
    runner = ApplicationRunner(
        db_session,
        AgentStateManager(),
        dry_run=False,
        close_session_after_run=False,
        recover_stale_state=False,
        progress_hook=progress_hook,
        cancel_check=cancel_check,
    )
    runner.adapter = _applied_adapter()
    # Never notify (SMTP) inside unit tests.
    runner._notify_safely = lambda callback: None
    return runner


def _rows(db_session: Session, job: Job) -> list[Application]:
    return (
        db_session.execute(
            select(Application).where(Application.job_id == job.id)
        )
        .scalars()
        .all()
    )


def _run(
    runner: ApplicationRunner,
    job_ids: list[int],
    *,
    mock_sleep: AsyncMock | None = None,
) -> dict:
    """run_applications with the inter-job pacing sleep mocked out.

    Tests that care about pacing pass their own mock and assert on it; the
    default keeps every other test from paying real 2s pauses.
    """
    sleep_mock = mock_sleep if mock_sleep is not None else AsyncMock()
    with patch(
        "backend.services.applications.runner.asyncio.sleep",
        new=sleep_mock,
    ):
        return asyncio.run(runner.run_applications(job_ids))


class TestSessionLossRecovery:
    def test_dead_session_before_attempt_restarts_and_batch_continues(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """The exact R31 incident: the session dies after job 1 opens its
        page; the batch must restart the session, retry that job, and keep
        processing the rest (59 jobs were lost to this before)."""
        job1 = _make_job(db_session, 1)
        job2 = _make_job(db_session, 2)
        _seed_analysis(db_session, job1)
        _seed_analysis(db_session, job2)

        runner = _make_runner(db_session)
        opened = runner.adapter.open_job_page.return_value
        runner.adapter.open_job_page.side_effect = [
            Exception(SESSION_LOST_MESSAGE),
            opened,
            opened,
        ]

        stats = _run(runner, [job1.id, job2.id])

        assert stats["processed"] == 2
        assert stats["applied"] == 2
        assert stats["failed"] == 0
        assert stats["skipped"] == 0
        assert stats["errors"] == 0
        assert stats["cancelled_remaining"] == 0
        assert stats["outcome_total"] == stats["processed"]
        # One mid-run session restart: stop stale + start fresh. The initial
        # open_session() already consumed one start_session, so the total is
        # two (open + restart) and exactly one stop (the restart's).
        runner.adapter.stop_session.assert_awaited_once()
        assert runner.adapter.start_session.await_count == 2
        for job in (job1, job2):
            rows = _rows(db_session, job)
            assert len(rows) == 1
            assert rows[0].status == ApplicationStatus.APPLIED.value

    def test_ambiguous_mid_attempt_death_is_needs_attention_and_never_retried(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """A session death AFTER the attempt row exists is ambiguous: record
        NEEDS_ATTENTION, never restart, never retry (ambiguous submissions
        must not be replayed)."""
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)

        runner = _make_runner(db_session)
        runner.adapter.start_application.side_effect = Exception(SESSION_LOST_MESSAGE)

        stats = _run(runner, [job.id])

        assert stats["processed"] == 1
        assert stats["needs_attention"] == 1
        assert stats["failed"] == 0
        assert stats["skipped"] == 0
        # No restart: only the initial session start happened; the stale
        # session was never stopped/replaced mid-run.
        runner.adapter.stop_session.assert_not_awaited()
        assert runner.adapter.start_session.await_count == 1
        runner.adapter.start_application.assert_awaited_once()
        rows = _rows(db_session, job)
        assert len(rows) == 1, "the open attempt must be reused, not duplicated"
        assert rows[0].status == ApplicationStatus.NEEDS_ATTENTION.value

    def test_restart_budget_is_bounded_and_exhaustion_records_truthful_skips(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """A browser that keeps dying restarts at most _SESSION_RESTART_LIMIT
        times per run; every job still gets a terminal SKIPPED row."""
        jobs = [_make_job(db_session, i) for i in range(1, 5)]
        for job in jobs:
            _seed_analysis(db_session, job)

        runner = _make_runner(db_session)
        runner.adapter.open_job_page.side_effect = Exception(SESSION_LOST_MESSAGE)
        runner._restart_browser_session = AsyncMock(return_value=True)

        stats = _run(runner, [job.id for job in jobs])

        assert stats["processed"] == 4
        assert stats["skipped"] == 4
        assert stats["failed"] == 0
        assert stats["errors"] == 0
        assert stats["outcome_total"] == stats["processed"]
        assert runner._restart_browser_session.await_count == (
            ApplicationRunner._SESSION_RESTART_LIMIT
        )
        for job in jobs:
            rows = _rows(db_session, job)
            assert len(rows) == 1
            assert rows[0].status == ApplicationStatus.SKIPPED.value
            assert "session unavailable" in (rows[0].skip_reason or "").lower()

    def test_restart_failure_records_skip_row_not_error(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """When the session cannot come back (profile lock conflict, launch
        failure), the job is recorded as a skip — no fake outcomes, no crash."""
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)

        runner = _make_runner(db_session)
        runner.adapter.open_job_page.side_effect = Exception(SESSION_LOST_MESSAGE)
        runner._restart_browser_session = AsyncMock(return_value=False)

        stats = _run(runner, [job.id])

        assert stats["processed"] == 1
        assert stats["skipped"] == 1
        assert stats["failed"] == 0
        assert stats["errors"] == 0
        rows = _rows(db_session, job)
        assert len(rows) == 1
        assert rows[0].status == ApplicationStatus.SKIPPED.value
        assert "session unavailable" in (rows[0].skip_reason or "").lower()

    def test_stop_before_restart_does_not_restart_the_session(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """A pending Stop wins over session recovery: the job is recorded as
        never attempted and no restart happens."""
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)

        # Loop-top boundary check says run; the post-loss recovery check says
        # stop — the Stop must win and no restart may happen.
        checks = iter([False, True])
        runner = _make_runner(db_session, cancel_check=lambda: next(checks))
        runner.adapter.open_job_page.side_effect = Exception(SESSION_LOST_MESSAGE)
        runner._restart_browser_session = AsyncMock(return_value=True)

        stats = _run(runner, [job.id])

        assert stats["processed"] == 1
        assert stats["skipped"] == 1
        runner._restart_browser_session.assert_not_awaited()
        rows = _rows(db_session, job)
        assert len(rows) == 1
        assert "run stopped" in (rows[0].skip_reason or "").lower()


class TestOutcomeReconciliation:
    def test_every_accepted_job_lands_in_exactly_one_bucket(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        applied_job = _make_job(db_session, 1)
        _seed_analysis(db_session, applied_job)
        no_analysis_job = _make_job(db_session, 2)  # skipped: no AI analysis

        runner = _make_runner(db_session)

        stats = _run(runner, [applied_job.id, no_analysis_job.id])

        assert stats["total"] == 2
        assert stats["processed"] == 2
        assert stats["applied"] == 1
        assert stats["skipped"] == 1
        assert stats["outcome_total"] == 2 == stats["processed"]
        assert stats["cancelled_remaining"] == 0

    def test_security_challenge_counts_as_needs_attention_matching_its_row(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """SECURITY_REQUIRED used to be counted nowhere while its row said
        NEEDS_ATTENTION — counters and rows must agree."""
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)

        runner = _make_runner(db_session)
        runner.adapter.open_job_page.return_value = SimpleNamespace(
            page=_FakeJobPage(), security_required=True, security_reason="captcha wall"
        )

        stats = _run(runner, [job.id])

        assert stats["processed"] == 1
        assert stats["needs_attention"] == 1
        assert stats["failed"] == 0
        assert stats["outcome_total"] == 1
        rows = _rows(db_session, job)
        assert len(rows) == 1
        assert rows[0].status == ApplicationStatus.NEEDS_ATTENTION.value

    def test_auth_required_halts_and_reports_remaining_as_never_started(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job1 = _make_job(db_session, 1)
        job2 = _make_job(db_session, 2)
        _seed_analysis(db_session, job1)
        _seed_analysis(db_session, job2)

        runner = _make_runner(db_session)
        runner.adapter.detect_login_state.return_value = {
            "authenticated": False,
            "evidence": "login form",
        }

        stats = _run(runner, [job1.id, job2.id])

        assert stats["auth_required"] == 1
        assert stats["processed"] == 1
        assert stats["cancelled_remaining"] == 1
        assert stats["outcome_total"] == stats["processed"]
        # Session-level halt: no application row for job 1, none for job 2.
        assert _rows(db_session, job1) == []
        assert _rows(db_session, job2) == []

    def test_external_job_never_opens_a_page_in_the_batch(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1, application_mode="EXTERNAL")
        _seed_analysis(db_session, job)

        runner = _make_runner(db_session)

        stats = _run(runner, [job.id])

        assert stats["external"] == 1
        assert stats["failed"] == 0
        runner.adapter.open_job_page.assert_not_awaited()


class TestCancellationAtBatchBoundary:
    def test_stop_between_jobs_leaves_remaining_jobs_unstarted(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        jobs = [_make_job(db_session, i) for i in range(1, 4)]
        for job in jobs:
            _seed_analysis(db_session, job)

        # Call sequence: job 1 loop boundary (run), job 1 pre-attempt
        # boundary (run), job 2 loop boundary (stop).
        checks = iter([False, False, True])
        runner = _make_runner(db_session, cancel_check=lambda: next(checks))

        stats = _run(runner, [job.id for job in jobs])

        assert stats["processed"] == 1
        assert stats["applied"] == 1
        assert stats["cancelled_remaining"] == 2
        assert stats["outcome_total"] == stats["processed"]
        assert _rows(db_session, jobs[0])  # only job 1 has a row
        assert _rows(db_session, jobs[1]) == []
        assert _rows(db_session, jobs[2]) == []

    def test_stop_before_the_first_job_processes_nothing(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        jobs = [_make_job(db_session, i) for i in range(1, 4)]
        for job in jobs:
            _seed_analysis(db_session, job)

        runner = _make_runner(db_session, cancel_check=lambda: True)

        stats = _run(runner, [job.id for job in jobs])

        assert stats["processed"] == 0
        assert stats["cancelled_remaining"] == 3
        for job in jobs:
            assert _rows(db_session, job) == []


class TestPacingAndInstrumentation:
    def test_no_inter_job_sleep_when_the_browser_was_never_used(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """Pre-attempt rejections (no analysis here) open no page, so the
        fixed 2s inter-job pause must not be paid 59 times in a row."""
        jobs = [_make_job(db_session, i) for i in range(1, 4)]  # no analysis

        runner = _make_runner(db_session)
        mock_sleep = AsyncMock()

        stats = _run(runner, [job.id for job in jobs], mock_sleep=mock_sleep)

        assert stats["processed"] == 3
        assert stats["skipped"] == 3
        mock_sleep.assert_not_awaited()

    def test_inter_job_sleep_applied_after_browser_uses_only(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        jobs = [_make_job(db_session, i) for i in range(1, 3)]
        for job in jobs:
            _seed_analysis(db_session, job)

        runner = _make_runner(db_session)
        mock_sleep = AsyncMock()

        stats = _run(runner, [job.id for job in jobs], mock_sleep=mock_sleep)

        assert stats["applied"] == 2
        # One pacing pause after each browser-using job.
        assert mock_sleep.await_count == 2

    def test_stage_timings_are_reported_in_stats(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)

        runner = _make_runner(db_session)

        stats = _run(runner, [job.id])

        stages = stats["stage_seconds"]
        assert isinstance(stages, dict)
        for expected in ("open_job_page", "page_detection", "start_application"):
            assert expected in stages, f"missing stage: {expected}"
            assert stages[expected] >= 0.0
        assert sum(stages.values()) > 0.0

    def test_job_started_event_carries_the_job_title(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)

        events: list[dict] = []

        async def hook(payload: dict) -> None:
            events.append(payload)

        runner = _make_runner(db_session, progress_hook=hook)

        _run(runner, [job.id])

        started = [e for e in events if e.get("event") == "job_started"]
        finished = [e for e in events if e.get("event") == "job_finished"]
        assert started and started[0].get("job_id") == job.id
        assert started[0].get("job_title") == job.title
        assert finished and finished[0].get("outcome") == "APPLIED"

    def test_session_restart_limit_and_adapter_timeouts_are_bounded(self) -> None:
        assert ApplicationRunner._SESSION_RESTART_LIMIT == 3
        assert NaukriAdapter.post_apply_timeout_seconds <= 10
        assert NaukriAdapter.post_apply_reload_settle_seconds <= 10
        assert NaukriAdapter.application_type_settle_seconds <= 5


class TestServiceStatsForwarding:
    """The manual-run summary must carry the new R31 counters (the dashboard
    renders them; the int-cast copy loop must never mangle the dict)."""

    @pytest.fixture
    def reset_cycle_control(self, db):
        from backend.models.cycle_run import CycleRunControl
        from backend.services.autonomous_cycle.coordinator import CONTROL_ROW_ID

        row = db.get(CycleRunControl, CONTROL_ROW_ID)
        if row is not None:
            db.delete(row)
            db.commit()

    def test_manual_summary_carries_r31_counters(
        self, client, db, reset_cycle_control
    ) -> None:
        import time as time_mod
        from unittest.mock import patch as patch_ctx

        from backend.models.cycle_run import CycleRunControl  # noqa: F401
        from backend.models.profile import Profile, Resume as ResumeModel
        from backend.models.matching import JobPreference as JobPreferenceModel

        resume = ResumeModel(
            stored_filename="test_resume.pdf",
            original_filename="resume.pdf",
            sha256="abc123",
            file_size=1000,
            text_length=5000,
            is_current=True,
        )
        db.add(resume)
        db.commit()
        db.add(
            Profile(
                resume_id=resume.id,
                status="CONFIRMED",
                confirmed=True,
                data={
                    "name": "Test User",
                    "skills": ["Python", "SQL"],
                    "location": "Bengaluru",
                },
            )
        )
        db.add(
            JobPreferenceModel(
                locations=["Bengaluru", "Remote"],
                job_titles=["Data Analyst", "Software Engineer"],
                employment_types=["Full-time"],
                min_salary_lpa=4.0,
                aggressiveness="BALANCED",
            )
        )
        db.commit()
        job = _make_job(db, 91)

        async def fake_run_applications(job_ids, dry_run=False):
            return {
                "total": len(job_ids),
                "processed": len(job_ids),
                "applied": 1,
                "submitted_unconfirmed": 0,
                "skipped": 2,
                "needs_attention": 0,
                "external": 0,
                "failed": 4,
                "errors": 0,
                "auth_required": 0,
                "dry_run": 0,
                "dry_run_mode": dry_run,
                "attempts_started": 1,
                "cancelled_remaining": 7,
                "outcome_total": len(job_ids),
                "stage_seconds": {"open_job_page": 1.25, "submit": 3.5},
            }

        with patch_ctx(
            "backend.services.manual_apply.service.ApplicationRunner"
        ) as mock_runner, patch_ctx(
            "backend.services.discovery.service.DiscoveryService"
        ) as mock_discovery:
            mock_instance = AsyncMock()
            mock_instance.run_applications = AsyncMock(side_effect=fake_run_applications)
            mock_instance.reconcile_history = AsyncMock(return_value=None)
            mock_instance.close_session = AsyncMock(return_value=None)
            mock_runner.return_value = mock_instance

            response = client.post(
                "/api/manual-apply/start", json={"job_ids": [job.id]}
            )
            assert response.status_code == 200
            assert response.json()["status"] == "RUNNING"
            mock_discovery.assert_not_called()

            deadline = time_mod.time() + 5
            while time_mod.time() < deadline:
                status = client.get("/api/manual-apply/status").json()
                if status["active_state"] == "IDLE":
                    break
                time_mod.sleep(0.05)

        status = client.get("/api/manual-apply/status").json()
        last_run = status["last_manual_run"]
        assert last_run is not None
        stats = last_run["stats"]
        assert stats["cancelled_remaining"] == 7
        assert stats["outcome_total"] == 1
        assert stats["failed"] == 4
        assert stats["dropped"] == 0
        # stage_seconds must survive as a dict (never int-cast).
        assert stats["stage_seconds"] == {"open_job_page": 1.25, "submit": 3.5}
