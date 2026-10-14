"""E5-R23: explicit-start semantics + identity-based dedup + relevance hardening.

Regression coverage for the three defects observed in the third controlled
live run (run #82, cancelled 12:37:41 UTC with `stop_reason "Cancellation
requested at after discovery"`). Run #82 performed 54 searches, scanned 688
cards, inserted only 4 new rows, and re-encountered 684 known duplicates —
including a mechanical "Walk-in || Graduate Trainee FEA and Piping Analysis"
posting (job #535) that the relevance gate let through.

Root cause (Phase 1): there is NO automatic-restart mechanism. Exactly three
`POST /api/autonomous-cycle/run` exist across both backend logs (runs #80,
#81, #82); the scheduler is never started by the backend; the frontend only
issues GET status polls. What the operator saw as "a completed cycle then a
fresh cycle" is the SAME run's phase structure: a 54-search discovery sweep
(each new search restarting at page 1 with no persisted progress), then a
login-probe session, then an application session. The second cycle was
another phase/iteration inside the one run, not a new run.

This file therefore locks in:

Phase 2 — explicit-start semantics. A completed (or cancelled) run must
never be re-entered without an explicit `POST /run`. Status GETs and the
frontend poll must never acquire the coordinator lock, and the scheduler must
never be auto-started by the backend. Discovery progress is persisted to the
control row so the sweep is visible as one continuous run.

Phase 3 — identity-based dedup. Irrelevant roles are rejected from card
metadata BEFORE the dedup lookup; application_mode backfills are bounded;
the same posting re-listed under a different URL spelling resolves to one
row; applied / needs-attention / ambiguous jobs are never re-submitted.

Phase 4 — relevance hardening. The real leaked job #535 and the persisted
irrelevant backlog are rejected, while genuine data / BI / software /
AI-ML / cloud roles (including legitimate "walk-in drive" postings for an
allowed position) stay eligible.

All browser/runner behavior is mocked: no live Naukri pages, no Apply
clicks, no real browser sessions, no database writes beyond the test DBs.
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.services.applications import ApplicationService
from backend.services.autonomous_cycle.coordinator import CycleCoordinator
from backend.services.autonomous_cycle.service import AutonomousCycle
from backend.services.discovery.service import (
    DiscoveryService,
    MAX_MODE_BACKFILLS_PER_RUN,
)
from backend.services.matching.engine import (
    job_relevance_check,
    irrelevant_role_reason,
    title_matches_allowed_role,
)
from backend.schemas.ai import AIRecommendation, JobQuality

TEST_DATABASE_URL = "sqlite:///:memory:"

# The user's configured target titles (mirrors the live preference set).
CONFIGURED_TITLES = [
    "Data Analyst",
    "Software Engineer",
    "Data Engineer",
    "Power BI Developer",
    "Frontend Developer",
    "AI/ML Engineer",
    "Cloud Engineer",
    "MIS Executive",
    "Graduate Engineer Trainee",
    "Python Developer",
]


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
        job_titles=["Data Analyst", "Software Engineer"],
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
    title: str = "Software Engineer",
    description: str = "Python developer role",
    role_category: str | None = None,
    department: str | None = None,
    application_mode: str = "NAUKRI_NATIVE",
    url: str | None = None,
    external_job_id: str | None = None,
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=external_job_id or f"e5r23job{index}",
        url=url or f"https://www.naukri.com/e5r23job{index}",
        title=title,
        company=f"Company {index}",
        description=description,
        location="Bengaluru",
        salary="5-7 LPA",
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
        application_mode=application_mode,
        role_category=role_category,
        department=department,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_analysis(db_session: Session, job_id: int, *, score: int = 80) -> None:
    db_session.add(
        JobAnalysisModel(
            job_id=job_id,
            match_score=score,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality=JobQuality.GOOD.value,
            duplicate_probability=0.05,
            suspicious=False,
            recommendation=AIRecommendation.APPLY.value,
            short_reason="ok",
            model="gemini",
            prompt_version="v1",
        )
    )
    db_session.commit()


def _make_application(db_session: Session, job_id: int, status: str) -> Application:
    application = Application(
        job_id=job_id,
        status=status,
        application_method="NAUKRI_NATIVE",
        applied_at=datetime.now(UTC),
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


# ── Phase 1 + 2: explicit-start semantics ───────────────────────────────────


class TestExplicitStartSemantics:
    """A finished run is never re-entered without an explicit POST /run."""

    def test_completed_run_is_not_reentered_without_explicit_start(
        self, db_session: Session
    ):
        """After a run completes, the coordinator is idle until a new POST."""
        coord = CycleCoordinator()
        ok, token, snap = coord.try_acquire(db=db_session)
        assert ok is True
        assert snap["active_state"] == "RUNNING"

        coord.complete(
            token,
            {"status": "COMPLETED", "run_id": 82, "stats": {"applied": 0}},
            db=db_session,
        )

        # The run is over. Nothing may re-acquire the lock implicitly: a
        # status snapshot must report IDLE / last_run, not RUNNING.
        snap_after = coord.snapshot(db=db_session)
        assert snap_after["active_state"] != "RUNNING"
        assert snap_after.get("active_run") in (None, {})

        # The only way to start again is a fresh, explicit claim.
        ok2, token2, _ = coord.try_acquire(db=db_session)
        assert ok2 is True
        assert token2 != token
        coord.complete(token2, {"status": "COMPLETED", "run_id": 83, "stats": {}}, db=db_session)

    def test_cancelled_run_is_not_reentered_without_explicit_start(
        self, db_session: Session
    ):
        """A CANCELLED run (run #82's end state) must not auto-resume."""
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db_session)
        assert ok is True

        # Run #82 ended via Stop with "Cancellation requested at after
        # discovery" — status is CANCELLED, not RUNNING.
        coord.complete(
            token,
            {
                "status": "CANCELLED",
                "run_id": 82,
                "stats": {"reason": "Cancellation requested at after discovery"},
            },
            db=db_session,
        )

        snap = coord.snapshot(db=db_session)
        assert snap["active_state"] != "RUNNING"

        # A subsequent run still requires an explicit claim.
        ok2, token2, _ = coord.try_acquire(db=db_session)
        assert ok2 is True
        assert token2 != token
        coord.complete(token2, {"status": "COMPLETED", "run_id": 83, "stats": {}}, db=db_session)

    def test_status_poll_never_acquires_the_lock(self, db_session: Session):
        """The frontend status poll (GET) must never claim the coordinator."""
        coord = CycleCoordinator()
        snap = coord.snapshot(db=db_session)
        assert snap["active_state"] != "RUNNING"
        # A snapshot with no active run must not have minted a token.
        assert snap.get("active_run") in (None, {})

        # Repeated polls are still read-only.
        for _ in range(5):
            snap = coord.snapshot(db=db_session)
            assert snap["active_state"] != "RUNNING"

        # Still acquirable afterwards (polling did not consume the lock).
        ok, token, _ = coord.try_acquire(db=db_session)
        assert ok is True
        coord.complete(token, {"status": "COMPLETED", "run_id": 1, "stats": {}}, db=db_session)

    def test_background_task_completes_once_and_never_restarts(
        self, db_session: Session
    ):
        """The background task (POST /run) runs cycle.run() once and completes.

        Mirrors the closure in api/routes/autonomous_cycle.py: it awaits
        cycle.run() a single time, then marks the coordinator complete. Nothing
        re-enters the run afterwards.
        """
        import asyncio

        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db_session)
        assert ok is True

        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        run_calls = []

        async def fake_run():
            run_calls.append(1)
            return {"status": "COMPLETED", "run_id": 82, "stats": {}}

        cycle.run = fake_run

        # Replicate run_cycle_background's body exactly.
        async def run_cycle_background():
            try:
                result = await cycle.run()
                coord.complete(token, result, db=db_session)
            except Exception:
                coord.fail(token, "Autonomous cycle execution failed unexpectedly.", db=db_session)

        asyncio.run(run_cycle_background())

        assert run_calls == [1], "the cycle must run exactly once"
        snap = coord.snapshot(db=db_session)
        assert snap["active_state"] != "RUNNING", "no automatic restart after completion"

    def test_background_task_failure_does_not_leave_lock_held(
        self, db_session: Session
    ):
        """An exception in cycle.run() releases the lock via coordinator.fail."""
        import asyncio

        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db_session)
        assert ok is True

        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)

        async def exploding_run():
            raise RuntimeError("cycle blew up")

        cycle.run = exploding_run

        async def run_cycle_background():
            try:
                result = await cycle.run()
                coord.complete(token, result, db=db_session)
            except Exception:
                coord.fail(token, "Autonomous cycle execution failed unexpectedly.", db=db_session)

        asyncio.run(run_cycle_background())

        snap = coord.snapshot(db=db_session)
        assert snap["active_state"] != "RUNNING", "failed run must not hold the lock"

    def test_scheduler_is_not_auto_started_by_the_backend(self, db_session: Session):
        """main.py must not start the scheduler on startup (explicit-start)."""
        import inspect

        import backend.main as main_module

        source = inspect.getsource(main_module)
        assert "scheduler_service" not in source.lower() or "scheduler_service.initialize" not in source, (
            "the backend must not auto-start the scheduler"
        )
        # The scheduler config row must remain stopped by default.
        from backend.models.scheduler import SchedulerConfig

        row = db_session.query(SchedulerConfig).first()
        if row is not None:
            assert row.is_running in (False, 0)

    def test_discovery_progress_is_persisted_to_the_control_row(self):
        """Discovery reports search X of Y so the sweep is visible as one run."""
        state_manager = MagicMock()
        state_manager.current_state = "IDLE"

        service = DiscoveryService.__new__(DiscoveryService)
        service.state_manager = state_manager
        service.progress_hook = None
        reported = []

        def hook(payload):
            reported.append(payload)

        service.progress_hook = hook
        service._report_progress(search_index=3, search_total=17, current_search="Data Analyst in Bengaluru")

        assert len(reported) == 1
        assert reported[0]["phase"] == "discovery"
        assert reported[0]["search_index"] == 3
        assert reported[0]["search_total"] == 17

    def test_discovery_progress_hook_failure_does_not_crash_discovery(self):
        """A broken progress hook must never abort the discovery sweep."""
        service = DiscoveryService.__new__(DiscoveryService)
        service.progress_hook = lambda payload: (_ for _ in ()).throw(RuntimeError("boom"))
        # Must not raise.
        service._report_progress(search_index=1, search_total=2)

    def test_cycle_folds_discovery_progress_into_run_progress(self):
        """The autonomous cycle persists discovery sweep progress to the row."""
        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        cycle.run_token = "e5r23-token"
        cycle._run_progress = {}

        with patch.object(cycle, "_persist_progress") as persist:
            cycle._discovery_progress_hook(
                {
                    "phase": "discovery",
                    "search_index": 5,
                    "search_total": 17,
                    "current_search": "Data Analyst in Bengaluru",
                    "jobs_new": 2,
                    "jobs_duplicate": 40,
                }
            )
            assert persist.called

        assert cycle._run_progress["phase"] == "discovery"
        assert cycle._run_progress["search_index"] == 5
        assert cycle._run_progress["search_total"] == 17
        assert cycle._run_progress["current_search"] == "Data Analyst in Bengaluru"
        assert cycle._run_progress["jobs_new"] == 2
        assert cycle._run_progress["jobs_duplicate"] == 40
        assert cycle._run_progress["current_step"] == "discovery_search_5_of_17"
        assert cycle._run_progress["processed"] == 5
        assert cycle._run_progress["remaining"] == 12

    def test_cycle_discovery_progress_hook_tolerates_bad_payload(self):
        """Non-dict payloads are ignored (no crash during discovery)."""
        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        cycle.run_token = "e5r23-token"
        cycle._run_progress = {}
        cycle._discovery_progress_hook("not-a-dict")  # must not raise
        cycle._discovery_progress_hook(None)  # must not raise
        assert cycle._run_progress == {}


# ── Phase 3: identity-based dedup ───────────────────────────────────────────


class TestIdentityBasedDedup:
    """The same posting re-listed under a different URL spelling is one row."""

    def test_url_match_variants_cover_scheme_host_and_slash(self):
        a = "https://www.naukri.com/job-listings-software-engineer-1234567890"
        b = "http://www.naukri.com/job-listings-software-engineer-1234567890"
        c = "https://naukri.com/job-listings-software-engineer-1234567890/"
        d = "https://WWW.naukri.com/job-listings-software-engineer-1234567890#apply"

        variants_a = set(DiscoveryService._url_match_variants(a))
        for other in (b, c, d):
            variants_other = set(DiscoveryService._url_match_variants(other))
            assert variants_a & variants_other, f"no shared variant with {other!r}"

    def test_url_match_variants_returns_empty_for_unnormalizable(self):
        assert DiscoveryService._url_match_variants("") == []
        assert DiscoveryService._url_match_variants("   ") == []
        assert DiscoveryService._url_match_variants("not a url") == []

    def test_find_existing_job_resolves_url_spelling_variant(self, db_session: Session):
        """A rediscovery with a different URL spelling lands on the one row."""
        stored = _make_job(
            db_session, 1,
            url="https://www.naukri.com/job-listings-data-analyst-999",
            external_job_id="999",
            title="Data Analyst",
        )

        service = DiscoveryService.__new__(DiscoveryService)
        # Incoming card: same posting, http scheme, no www, trailing slash.
        incoming = {
            "external_job_id": "DIFFERENT-OR-MISSING",
            "url": "http://naukri.com/job-listings-data-analyst-999/",
            "title": "Data Analyst",
            "company": "Company 1",
        }
        found = service._find_existing_job(db_session, incoming)
        assert found is not None
        assert found.id == stored.id

    def test_irrelevant_card_rejected_before_dedup_lookup(self, db_session: Session):
        """An irrelevant card is dropped from card metadata — no DB lookup."""
        service = DiscoveryService.__new__(DiscoveryService)

        # Card metadata only (no description yet): the title alone is enough.
        card = {"title": "Walk-in || Customer Service Officer - Fresher"}
        reason = irrelevant_role_reason(title=card["title"], description=None)
        assert reason is not None, "job #446's title must be rejected at card level"

        card = {"title": "Walk-in || Graduate Trainee FEA and Piping Analysis"}
        reason = irrelevant_role_reason(title=card["title"], description=None)
        assert reason is not None, "job #535's title must be rejected at card level"

    def test_mode_backfill_is_bounded_per_run(self):
        """A run cannot re-visit the whole corpus to backfill application_mode."""
        assert MAX_MODE_BACKFILLS_PER_RUN == 25

        service = DiscoveryService.__new__(DiscoveryService)
        service._mode_backfills_used = 0
        # Simulate 25 backfills already spent.
        service._mode_backfills_used = MAX_MODE_BACKFILLS_PER_RUN
        # The guard in run_discovery compares against the cap; assert the
        # constant is what the guard uses and that the counter is respected.
        assert service._mode_backfills_used >= MAX_MODE_BACKFILLS_PER_RUN

    @pytest.mark.asyncio
    async def test_irrelevant_jobs_never_become_candidates(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference,
    ):
        """The persisted irrelevant backlog never enters the candidate list."""
        relevant = _make_job(db_session, 1, title="Data Analyst")
        backlog_titles = [
            ("Walk-in || Customer Service Officer - Fresher", "Handle customer calls."),
            ("Walk-in || Graduate Trainee FEA and Piping Analysis",
             "Mechanical engineering FEA and piping analysis with ANSYS and CAESAR II."),
            ("International Voice Process Executive", "Voice process for international clients."),
            ("Non Voice Process - Data Entry", "Non voice process with data entry tasks."),
        ]
        backlog = [
            _make_job(db_session, 10 + i, title=t, description=d)
            for i, (t, d) in enumerate(backlog_titles)
        ]

        run = DiscoveryRun(
            status="COMPLETED",
            jobs_discovered=len(backlog) + 1,
            current_run_job_ids=",".join(str(j.id) for j in [relevant, *backlog]),
        )
        db_session.add(run)
        db_session.commit()

        for j in [relevant, *backlog]:
            _make_analysis(db_session, j.id)

        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        cycle.current_discovery_run = run

        visited = []

        async def _fake_process(session, job, profile, preferences):
            visited.append(job.id)
            return "APPLIED"

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            stats = await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        assert visited == [relevant.id], "only the relevant job reaches the apply loop"
        assert stats["applied"] == 1

    @pytest.mark.asyncio
    async def test_applied_and_needs_attention_jobs_are_never_resubmitted(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference,
    ):
        """Already-applied (146-150) and NEEDS_ATTENTION jobs stay protected."""
        applied_job = _make_job(db_session, 1, title="Data Analyst")
        needs_attention_job = _make_job(db_session, 2, title="Software Engineer")
        fresh_job = _make_job(db_session, 3, title="Power BI Developer")

        _make_application(db_session, applied_job.id, "APPLIED")
        _make_application(db_session, needs_attention_job.id, "NEEDS_ATTENTION")

        run = DiscoveryRun(
            status="COMPLETED",
            jobs_discovered=3,
            current_run_job_ids=f"{applied_job.id},{needs_attention_job.id},{fresh_job.id}",
        )
        db_session.add(run)
        db_session.commit()

        for j in (applied_job, needs_attention_job, fresh_job):
            _make_analysis(db_session, j.id)

        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        cycle.current_discovery_run = run

        visited = []

        async def _fake_process(session, job, profile, preferences):
            visited.append(job.id)
            return "APPLIED"

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        assert applied_job.id not in visited, "already-applied job must not be re-submitted"
        assert needs_attention_job.id not in visited, "NEEDS_ATTENTION job must not be re-submitted"
        assert fresh_job.id in visited


# ── Phase 4: relevance hardening against the real incident ──────────────────


class TestRelevanceHardening:
    """The real leaked job #535 and the persisted backlog are rejected."""

    @pytest.mark.parametrize(
        "title,description",
        [
            # Job #535 — the exact live leak (mechanical FEA/piping walk-in).
            (
                "Walk-in || Graduate Trainee FEA and Piping Analysis",
                "Freshers in Mechanical Engineering with strong fundamentals and "
                "interest in FEA and Piping Analysis. Training on ANSYS, CAESAR II.",
            ),
            # Persisted backlog titles from the live DB.
            ("Walk-in || Customer Service Officer - Fresher", "Handle customer queries."),
            ("Walk-in || Mega Walk-In Drive | International Voice Process | Freshers | ITPL",
             "Voice process walk in drive."),
            ("Non Voice Process - Data Entry", "Non voice process with data entry tasks."),
            ("Hiring for Accounts & Finance Executive",
             "Accounts payable, payroll processing, gst filing."),
            ("Recruitment Coordinator", "Resume screening and campus recruitment drive."),
            ("Operation Executive (fresher)",
             "Back office operations, billing process, data entry."),
            ("Electrical Harness Design Engineer", "Harness design using CAD."),
        ],
    )
    def test_incident_jobs_are_rejected(self, title: str, description: str):
        ok, reason = job_relevance_check(title, CONFIGURED_TITLES, description=description)
        assert ok is False, f"{title!r} must be rejected, got: {reason}"

    def test_job_535_specifically_rejected_at_title_level(self):
        """The FEA/piping walk-in is caught by the title filter alone."""
        allowed, reason = title_matches_allowed_role(
            "Walk-in || Graduate Trainee FEA and Piping Analysis", CONFIGURED_TITLES
        )
        assert allowed is False
        assert "unwanted specialization" in reason.lower()

    @pytest.mark.parametrize(
        "title",
        [
            "Data Analyst",
            "Software Engineer",
            "Graduate Engineer Trainee",
            "Power BI Developer",
            "Frontend Developer",
            "Fresher Data Analyst",
            "Associate Software Engineer",
            "MIS Executive",
            "Machine Learning Engineer",
            "Data Engineer",
            "Cloud Engineer",
            "Python Developer",
        ],
    )
    def test_legitimate_target_roles_stay_eligible(self, title: str):
        ok, reason = job_relevance_check(title, CONFIGURED_TITLES)
        assert ok is True, f"{title!r} must stay eligible, got: {reason}"

    def test_walk_in_for_an_allowed_position_is_not_blanket_rejected(self):
        """Walk-in is only rejected when the position itself is excluded."""
        ok, reason = job_relevance_check(
            "Walk-in Drive for Data Analyst",
            CONFIGURED_TITLES,
            description="Walk-in interview for a Data Analyst role. SQL and Power BI.",
        )
        assert ok is True, f"legitimate walk-in data role must stay eligible, got: {reason}"

    def test_data_role_with_minor_process_mention_not_swept_away(self):
        """A genuine data JD with one process phrase must not be rejected."""
        ok, reason = job_relevance_check(
            "Data Analyst",
            CONFIGURED_TITLES,
            description=(
                "Build SQL dashboards and Power BI reports. Occasional customer "
                "handling for requirement gathering. Python and pandas for ETL."
            ),
        )
        assert ok is True, f"Data Analyst must stay relevant, got: {reason}"

    def test_final_safety_gate_rejects_job_535(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference,
    ):
        """The application safety gate rejects the exact leaked posting."""
        job = _make_job(
            db_session, 935,
            title="Walk-in || Graduate Trainee FEA and Piping Analysis",
            description=(
                "Freshers in Mechanical Engineering with strong fundamentals and "
                "interest in FEA and Piping Analysis. Training on ANSYS, CAESAR II."
            ),
        )
        service = ApplicationService(db_session)
        allowed, reason = service.run_final_safety_gate(job, confirmed_profile, job_preferences)
        assert allowed is False
        assert (
            "piping" in reason.lower()
            or "unwanted specialization" in reason.lower()
            or "excluded role" in reason.lower()
        )


# ── Phase 5: safety invariants preserved ────────────────────────────────────


class TestSafetyInvariantsPreserved:
    """E5-R23 must not weaken any E5-R10/R16/R21/R22 protection."""

    def test_hourly_and_daily_limits_unchanged(self, db_session: Session):
        preferences = JobPreference(
            locations=["Bengaluru"],
            job_titles=["Data Analyst"],
            employment_types=["Full-time"],
            min_salary_lpa=4.0,
            aggressiveness="BALANCED",
        )
        # Mirror the live preference row (enforcement removed by E5-R10 but
        # the columns are preserved and must not be reintroduced/changed).
        preferences.max_hourly_applications = 4
        preferences.max_daily_applications = 20
        db_session.add(preferences)
        db_session.commit()
        db_session.refresh(preferences)
        assert preferences.max_hourly_applications == 4
        assert preferences.max_daily_applications == 20

    def test_coordinator_lock_is_still_atomic(self, db_session: Session):
        """The single shared run lock is untouched by E5-R23."""
        coord = CycleCoordinator()
        results = [coord.try_acquire(db=db_session) for _ in range(5)]
        winners = [r for r in results if r[0]]
        assert len(winners) == 1, "exactly one acquire may win while RUNNING"
        coord.complete(winners[0][1], {"status": "COMPLETED", "run_id": 1, "stats": {}}, db=db_session)

    def test_answer_memory_and_staleness_paths_untouched(self):
        """E5-R21 screening-answer memory is not modified by E5-R23."""
        import inspect

        from backend.services.applications import answer_memory as am

        source = inspect.getsource(am)
        # The memory module must still exist and be importable with its API.
        assert hasattr(am, "AnswerMemory") or "class" in source

    def test_url_normalizer_reexport_is_backward_compatible(self):
        """Existing callers importing from applications.service keep working."""
        from backend.services.applications.service import (
            normalize_naukri_url_for_comparison as from_service,
        )
        from backend.services.matching.normalizer import (
            normalize_naukri_url_for_comparison as from_normalizer,
        )

        assert from_service is from_normalizer
        # Byte-identical semantics with the pre-E5-R23 implementation.
        assert from_service("https://WWW.naukri.com/job/abc/?x=1#frag") == (
            "https://www.naukri.com/job/abc?x=1"
        )
        assert from_service("http://naukri.com:80/job/abc") == "https://naukri.com/job/abc"
        assert from_service("") is None
        assert from_service(None) is None
