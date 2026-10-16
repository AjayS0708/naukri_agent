"""E5-R30: runner boundary, browser-tab, and lock-view tests.

Covers the four Phase 3/4 behaviors with a fully mocked browser (no live
Naukri pages, no apply clicks):

- EXTERNAL jobs are excluded *before any page opens* (stored mode never
  downgraded, exclusion reason recorded).
- An expired listing is detected from positive visible evidence, marks the
  job row EXPIRED (removing it from every candidate stage), and is skipped
  with the matched phrase as the reason — a transient browser error never
  reaches that check (``open_job_page`` raises instead).
- A failure before any attempt started is recorded as a retryable SKIPPED
  row (never a blocking NEEDS_ATTENTION row), while a failure after this run
  began an attempt resolves that attempt to NEEDS_ATTENTION; one failing job
  never aborts the batch.
- Unused about:blank tabs are closed but never the last page, never the page
  in use, and never a content tab; observed Apply popups are closed after
  recording.
- A control row whose owning process is dead is reported IDLE (view-only) so
  the dashboard never shows an indefinitely RUNNING run.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.cycle_run import CycleRunControl
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.schemas.application import ApplicationStatus
from backend.services.agent_state import AgentStateManager
from backend.services.applications.runner import ApplicationRunner
from backend.services.autonomous_cycle.coordinator import (
    CONTROL_ROW_ID,
    CycleCoordinator,
)
from backend.services.naukri.adapter import NaukriAdapter

TEST_DATABASE_URL = "sqlite:///:memory:"
# Far above any plausible live pid; guaranteed dead on POSIX and Windows.
PID_GONE = 4194881


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
        external_job_id=f"e5r30job{index}",
        url=f"https://www.naukri.com/e5r30job{index}",
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


def _make_runner(db_session: Session) -> ApplicationRunner:
    runner = ApplicationRunner(
        db_session,
        AgentStateManager(),
        dry_run=False,
        close_session_after_run=False,
        recover_stale_state=False,
    )
    opened = SimpleNamespace(page=_FakeJobPage(), security_required=False, security_reason=None)
    runner.adapter = SimpleNamespace(
        open_job_page=AsyncMock(return_value=opened),
        detect_login_state=AsyncMock(return_value={"authenticated": True}),
        detect_expired_listing=AsyncMock(return_value=None),
        detect_application_type=AsyncMock(return_value="NAUKRI_NATIVE"),
        get_external_redirect_url=AsyncMock(return_value=None),
        detect_applied_state=AsyncMock(return_value=(True, "clicked apply")),
        start_application=AsyncMock(),
    )
    return runner


def _latest_row(db_session: Session, job: Job) -> Application | None:
    return (
        db_session.execute(
            select(Application)
            .where(Application.job_id == job.id)
            .order_by(Application.id.desc())
        )
        .scalars()
        .first()
    )


def _run(runner: ApplicationRunner, job: Job, profile, preferences) -> str:
    return asyncio.run(runner._execute_single_job(job.id, profile, preferences))


class TestExternalPreOpenGate:
    def test_external_job_excluded_before_page_open(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1, application_mode="EXTERNAL")
        _seed_analysis(db_session, job)
        runner = _make_runner(db_session)

        outcome = _run(runner, job, confirmed_profile, job_preferences)

        assert outcome == "EXTERNAL"
        runner.adapter.open_job_page.assert_not_awaited()
        row = _latest_row(db_session, job)
        assert row is not None
        assert row.status == ApplicationStatus.SKIPPED.value
        assert "excluded before opening the job page" in (row.skip_reason or "")
        # The stored classification is never changed by the exclusion.
        db_session.refresh(job)
        assert job.application_mode == "EXTERNAL"

    def test_native_job_still_opens_page(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """Control: the gate must not block the normal native path."""
        job = _make_job(db_session, 1, application_mode="NAUKRI_NATIVE")
        _seed_analysis(db_session, job)
        runner = _make_runner(db_session)
        runner.adapter.open_job_page.side_effect = Exception("stop-here")

        outcome = _run(runner, job, confirmed_profile, job_preferences)

        runner.adapter.open_job_page.assert_awaited_once()
        # E5-R31: a failure before any attempt records a SKIPPED row (see
        # TestFailureBeforeAttempt), so the outcome now matches that row —
        # counting FAILED here was the counter/row mismatch.
        assert outcome == "SKIPPED"


class TestExpiredListingDetection:
    def test_expired_listing_marks_job_and_skips(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)
        runner = _make_runner(db_session)
        runner.adapter.detect_expired_listing = AsyncMock(return_value="job has expired")

        outcome = _run(runner, job, confirmed_profile, job_preferences)

        assert outcome == "SKIPPED"
        # Detection happens before any application-type/attempt logic.
        runner.adapter.detect_application_type.assert_not_awaited()
        db_session.refresh(job)
        assert job.status == "EXPIRED"
        row = _latest_row(db_session, job)
        assert row is not None
        assert row.status == ApplicationStatus.SKIPPED.value
        assert "Listing expired - job has expired" in (row.skip_reason or "")

    def test_live_listing_continues(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)
        runner = _make_runner(db_session)
        runner.adapter.detect_expired_listing = AsyncMock(return_value=None)
        runner.adapter.detect_application_type = AsyncMock(side_effect=Exception("stop-here"))

        outcome = _run(runner, job, confirmed_profile, job_preferences)

        runner.adapter.detect_expired_listing.assert_awaited_once()
        db_session.refresh(job)
        assert job.status == "DISCOVERED"

    def test_expired_scan_matches_phrase_not_bare_word(self) -> None:
        adapter = NaukriAdapter(browser_type="chromium")
        # No bare single-word indicator: "expired" inside a transient error
        # message must never classify a listing as expired.
        assert adapter.expired_listing_indicators
        for phrase in adapter.expired_listing_indicators:
            assert phrase.strip().lower() != "expired"

        class _Page:
            def __init__(self, text: str | None, fails: bool = False) -> None:
                self._text = text
                self._fails = fails

            async def inner_text(self, _selector: str) -> str:
                if self._fails:
                    raise RuntimeError("Execution context was destroyed")
                return self._text or ""

        # Positive evidence, case-insensitive.
        hit = asyncio.run(
            adapter.detect_expired_listing(_Page("Sorry, this Job Has Expired"))
        )
        assert hit is not None
        # Ordinary live listing text never matches.
        miss = asyncio.run(
            adapter.detect_expired_listing(_Page("Apply to 5,000+ open jobs today"))
        )
        assert miss is None
        # A broken/unfinished page is NOT expiry evidence (transient error).
        transient = asyncio.run(adapter.detect_expired_listing(_Page(None, fails=True)))
        assert transient is None


class TestFailureBeforeAttempt:
    def test_nav_failure_records_retryable_skip_not_needs_attention(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)
        runner = _make_runner(db_session)
        runner.adapter.open_job_page.side_effect = Exception("connection reset")

        outcome = _run(runner, job, confirmed_profile, job_preferences)

        # E5-R31: the recorded row is SKIPPED, so the outcome is too (the
        # run-level counters must reconcile with the rows they summarize).
        assert outcome == "SKIPPED"
        row = _latest_row(db_session, job)
        assert row is not None
        assert row.status == ApplicationStatus.SKIPPED.value
        assert "Page failed before any attempt started" in (row.skip_reason or "")
        assert row.needs_attention in (False, None)

    def test_mid_flow_failure_resolves_attempt_to_needs_attention(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """A failure after this run opened an attempt row must resolve that
        row to NEEDS_ATTENTION (its true state is unknown — never retried
        blindly), while a failure before any attempt stays a retryable skip.
        """
        job = _make_job(db_session, 1)
        _seed_analysis(db_session, job)
        runner = _make_runner(db_session)
        runner.adapter.start_application.side_effect = Exception("mid-flow boom")

        outcome = _run(runner, job, confirmed_profile, job_preferences)

        # E5-R31: the attempt row is NEEDS_ATTENTION, so the outcome reports
        # NEEDS_ATTENTION (never FAILED) — counters and rows must agree.
        assert outcome == "NEEDS_ATTENTION"
        rows = (
            db_session.execute(
                select(Application).where(Application.job_id == job.id)
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1, "one open attempt must be reused, not duplicated"
        row = rows[0]
        assert row.status == ApplicationStatus.NEEDS_ATTENTION.value
        assert row.needs_attention is True
        assert "mid-flow boom" in (row.failure_reason or "")

    def test_one_failing_job_does_not_abort_the_batch(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        failing = _make_job(db_session, 1)
        _seed_analysis(db_session, failing)
        analysis_less = _make_job(db_session, 2)

        runner = _make_runner(db_session)
        runner.adapter.open_job_page.side_effect = Exception("connection reset")
        runner.open_session = AsyncMock(return_value=True)

        stats = asyncio.run(runner.run_applications([failing.id, analysis_less.id]))

        # E5-R31: the failing job's row is SKIPPED, so it counts as skipped
        # (not failed); the analysis-less job is skipped for missing analysis.
        assert stats["processed"] == 2
        assert stats["skipped"] == 2
        assert stats["failed"] == 0
        assert stats["cancelled_remaining"] == 0
        assert stats["outcome_total"] == stats["processed"]
        assert stats["errors"] == 0


class TestBlankTabCleanup:
    class _FakePage:
        def __init__(self, url: str) -> None:
            self.url = url
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _FakeContext:
        def __init__(self, pages) -> None:
            self.pages = list(pages)

    def test_blank_tabs_closed_but_never_the_last_page(self) -> None:
        adapter = NaukriAdapter(browser_type="chromium")
        blank = self._FakePage("about:blank")
        content = self._FakePage("https://www.naukri.com/job-1")
        adapter.browser = self._FakeContext([blank, content])

        closed = asyncio.run(adapter._close_blank_starter_tabs())

        assert closed == 1
        assert blank.closed is True
        assert content.closed is False

    def test_single_starter_tab_is_kept(self) -> None:
        adapter = NaukriAdapter(browser_type="chromium")
        only = self._FakePage("about:blank")
        adapter.browser = self._FakeContext([only])

        closed = asyncio.run(adapter._close_blank_starter_tabs())

        assert closed == 0
        assert only.closed is False

    def test_keep_page_never_closed(self) -> None:
        adapter = NaukriAdapter(browser_type="chromium")
        keep = self._FakePage("about:blank")  # even a blank keep is protected
        other_blank = self._FakePage("about:blank")
        adapter.browser = self._FakeContext([keep, other_blank])

        closed = asyncio.run(adapter._close_blank_starter_tabs(keep=keep))

        assert closed == 1
        assert keep.closed is False
        assert other_blank.closed is True

    def test_content_tabs_never_closed(self) -> None:
        adapter = NaukriAdapter(browser_type="chromium")
        a = self._FakePage("https://www.naukri.com/a")
        b = self._FakePage("https://www.naukri.com/b")
        adapter.browser = self._FakeContext([a, b])

        closed = asyncio.run(adapter._close_blank_starter_tabs())

        assert closed == 0
        assert a.closed is False and b.closed is False

    def test_record_new_tab_closes_observed_popup(self) -> None:
        adapter = NaukriAdapter(browser_type="chromium")
        main = self._FakePage("https://www.naukri.com/job-1")
        popup = self._FakePage("about:blank")
        main.context = self._FakeContext([main, popup])

        async def produce():
            return popup

        async def scenario():
            task = asyncio.create_task(produce())
            await task  # already done; _record_new_tab must not cancel/await-loop
            await adapter._record_new_tab(main, task)

        asyncio.run(scenario())
        assert popup.closed is True

    def test_record_new_tab_never_closes_last_page(self) -> None:
        adapter = NaukriAdapter(browser_type="chromium")
        main = self._FakePage("https://www.naukri.com/job-1")
        popup = self._FakePage("about:blank")
        main.context = self._FakeContext([main])  # popup not listed as a context page

        async def produce():
            return popup

        async def scenario():
            task = asyncio.create_task(produce())
            await task
            await adapter._record_new_tab(main, task)

        asyncio.run(scenario())
        assert popup.closed is False


class TestDeadPidSnapshot:
    def test_dead_owner_reported_idle_without_writing(self, db_session) -> None:
        coordinator = CycleCoordinator()
        acquired, token, _ = coordinator.try_acquire(db=db_session)
        assert acquired
        try:
            # Alive pid (pytest) reports RUNNING.
            live = coordinator.snapshot(db=db_session)
            assert live["active_state"] == "RUNNING"
            assert live["lock_held"] is True

            # Simulate a crashed/restarted owner.
            row = db_session.get(CycleRunControl, CONTROL_ROW_ID)
            row.pid = PID_GONE
            db_session.commit()

            view = coordinator.snapshot(db=db_session)
            assert view["active_state"] == "IDLE"
            assert view["lock_held"] is False
            assert view["active_run"] is None
            # View-only: the durable row is untouched by the snapshot.
            db_session.refresh(row)
            assert row.status == "RUNNING"
        finally:
            # The orphan is adopted exactly like try_acquire would adopt it.
            db_session.get(CycleRunControl, CONTROL_ROW_ID).pid = PID_GONE
            db_session.commit()
            coordinator.complete(
                token, {"status": "CANCELLED", "run_id": None, "stats": {}}, db=db_session
            )

    def test_next_acquire_adopts_dead_owner(self, db_session) -> None:
        coordinator = CycleCoordinator()
        acquired, token, _ = coordinator.try_acquire(db=db_session)
        assert acquired
        row = db_session.get(CycleRunControl, CONTROL_ROW_ID)
        row.pid = PID_GONE
        db_session.commit()

        second = CycleCoordinator()
        acquired2, token2, snap = second.try_acquire(db=db_session)

        assert acquired2 is True
        assert token2 != token
        assert snap["active_state"] == "RUNNING"
        second.complete(
            token2, {"status": "COMPLETED", "run_id": None, "stats": {}}, db=db_session
        )
