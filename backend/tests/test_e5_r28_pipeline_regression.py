"""E5-R28: end-to-end candidate pipeline regression tests.

Run 88 findings fixed by this change (four defects, one coherent pipeline):

A. Recovery caps were applied to the freshness-sorted RAW pool before the
   relevance and deterministic gates, so ineligible fresher rows consumed
   the 40/12 budgets (job #503 ranked 65th and never entered recovery).
B. AMBIGUOUS / NULL-mode jobs — including rows discovered by the *current*
   run — were stranded: excluded from both the recovery stage and the
   NAUKRI_NATIVE-only candidate query, so no path ever re-verified them.
C. Application-history protection used a *per-row* outer-join predicate, so
   a job with a SKIPPED row and an unresolved NEEDS_ATTENTION row (job #81)
   still became a candidate. The shared job-level predicate now protects
   enqueue, recovery, candidate selection, and the runner itself.
D. Runs reported candidates but not funnel truth: how many candidates
   actually reached the runner, how many real (non-dry-run) application
   attempts started, what the live mode re-verification produced, and why a
   zero-candidate run happened.

Browser behavior is mocked: no live Naukri pages, no apply clicks, no
credential or application-record changes beyond in-memory fixtures.
"""
import json
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
from backend.services.agent_state import AgentStateManager
from backend.services.applications.runner import ApplicationRunner
from backend.services.autonomous_cycle.service import (
    AutonomousCycle,
    MAX_RECOVERY_JOBS_PER_RUN,
    MAX_RECOVERY_MODE_REVERIFY_PER_RUN,
    RECOVERY_MODE_REVERIFY_COOLDOWN,
)
from backend.schemas.ai import AIRecommendation, JobQuality
from backend.schemas.application import ApplicationStartResult, ApplicationStatus
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
    url: str | None = None,
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"e5r28job{index}",
        url=url or f"https://www.naukri.com/e5r28job{index}",
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


def _add_app(
    db_session: Session, job: Job, status: str, **fields
) -> Application:
    row = Application(job_id=job.id, status=status, **fields)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _eligible_job(db_session: Session, index: int) -> Job:
    """Runner-grade eligible job (mirrors the pinned E5 runner fixture)."""
    job = Job(
        platform="naukri",
        external_job_id=f"e5r28elig{index}",
        url=f"https://www.naukri.com/e5r28elig{index}",
        title="Software Engineer",
        company=f"Tech Company {index}",
        description="Python developer role",
        location="Bengaluru",
        salary="5-7 LPA",
        experience="2-4 years",
        employment_type="Full-time",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    _make_analysis(db_session, job.id)
    return job


# ── Run 88 defect A: eligibility gates before the recovery budget ────────


class TestRecoveryEligibilityBeforeBudget:
    @pytest.mark.asyncio
    async def test_recovery_caps_apply_after_all_eligibility_gates(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Ineligible fresher rows must not consume the per-run cap.

        The old order sliced the raw freshness-sorted pool first: 15 freshly
        discovered but below-minimum-salary rows occupied the head of the
        slice, so only 25 of the 35 eligible jobs entered recovery. With the
        gates first, every eligible job fits under the cap.
        """
        filler = _make_job(db_session, 1)
        eligible = [_make_job(db_session, 100 + i) for i in range(35)]
        # Inserted last → freshest by discovery time.
        ineligible = [
            _make_job(db_session, 200 + i, salary="2 LPA", salary_max=2.0)
            for i in range(15)
        ]
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        recovery_ids = set(cycle._recovery_job_ids)
        assert stats["recovery_hard_filtered"] == 15
        assert stats["recovery_relevance_rejected"] == 0
        assert stats["recovery_eligible_before_cap"] == 35
        assert stats["recovery_selected_after_cap"] == 35
        assert stats["recovery_native"] == 35
        assert not recovery_ids & {job.id for job in ineligible}
        assert {job.id for job in eligible} <= recovery_ids

    @pytest.mark.asyncio
    async def test_recovery_native_budget_still_bounded_at_max(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Gates before caps never removes the per-run cap itself."""
        filler = _make_job(db_session, 1)
        jobs = [
            _make_job(db_session, 300 + i)
            for i in range(MAX_RECOVERY_JOBS_PER_RUN + 5)
        ]
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert stats["recovery_eligible_before_cap"] == MAX_RECOVERY_JOBS_PER_RUN + 5
        assert stats["recovery_selected_after_cap"] == MAX_RECOVERY_JOBS_PER_RUN
        assert stats["recovery_native"] == MAX_RECOVERY_JOBS_PER_RUN
        assert len(cycle._recovery_job_ids) == MAX_RECOVERY_JOBS_PER_RUN

    @pytest.mark.asyncio
    async def test_fresher_ineligible_rows_never_consume_recovery_budget(
        self, db_session, confirmed_profile, job_preferences
    ):
        """45 eligible + 5 fresher ineligible → the full 40-slot native cap
        is spent on eligible jobs (the old order selected only 35)."""
        filler = _make_job(db_session, 1)
        eligible = [_make_job(db_session, 400 + i) for i in range(45)]
        ineligible = [
            _make_job(db_session, 500 + i, salary="2 LPA", salary_max=2.0)
            for i in range(5)
        ]
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        recovery_ids = set(cycle._recovery_job_ids)
        assert stats["recovery_hard_filtered"] == 5
        assert stats["recovery_eligible_before_cap"] == 45
        assert stats["recovery_native"] == MAX_RECOVERY_JOBS_PER_RUN
        assert stats["recovery_selected_after_cap"] == MAX_RECOVERY_JOBS_PER_RUN
        assert not recovery_ids & {job.id for job in ineligible}
        assert stats["recovery_candidates"] == MAX_RECOVERY_JOBS_PER_RUN


# ── Run 88 defect B: ambiguous / null mode has one bounded entry path ────


class TestAmbiguousModeReverifyScope:
    @pytest.mark.asyncio
    async def test_current_run_ambiguous_job_enters_reverify_and_candidates(
        self, db_session, confirmed_profile, job_preferences
    ):
        """A current-run AMBIGUOUS job used to be unreachable: excluded from
        recovery (current-run ids) *and* from the native-only candidate
        query. It now enters the re-verify pool and the apply loop."""
        ambiguous = _make_job(db_session, 2, application_mode="AMBIGUOUS")
        cycle = _make_cycle(db_session, [ambiguous])

        rec_stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert ambiguous.id in cycle._recovery_reverify_job_ids
        assert rec_stats["recovery_mode_reverify"] == 1
        assert rec_stats["recovery_native"] == 0

        visited: list[int] = []

        async def _fake_process(db, job, profile, preferences):
            visited.append(job.id)
            return "SKIPPED"

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            app_stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert app_stats["candidates"] == 1
        assert visited == [ambiguous.id]

    @pytest.mark.asyncio
    async def test_null_empty_and_literal_null_modes_are_recoverable(
        self, db_session, confirmed_profile, job_preferences
    ):
        """NULL, empty-string, and literal "NULL" rows are unclassified and
        recoverable for a bounded mode re-verification — none of them is
        treated as native."""
        filler = _make_job(db_session, 1)
        null_mode = _make_job(db_session, 2, application_mode=None)
        empty_mode = _make_job(db_session, 3, application_mode="")
        literal_null = _make_job(db_session, 4, application_mode="NULL")
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert set(cycle._recovery_reverify_job_ids) == {
            null_mode.id,
            empty_mode.id,
            literal_null.id,
        }
        assert stats["recovery_mode_reverify"] == 3
        assert stats["recovery_native"] == 0
        assert stats["recovery_candidates"] == 3

    @pytest.mark.asyncio
    async def test_reverify_budget_is_separate_from_native_cap(
        self, db_session, confirmed_profile, job_preferences
    ):
        """40 native + 12 re-verify slots are independent: the combined
        selection may exceed the native cap."""
        filler = _make_job(db_session, 1)
        for i in range(MAX_RECOVERY_JOBS_PER_RUN + 5):
            _make_job(db_session, 600 + i)
        for i in range(MAX_RECOVERY_MODE_REVERIFY_PER_RUN + 3):
            _make_job(db_session, 700 + i, application_mode="AMBIGUOUS")
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert stats["recovery_native"] == MAX_RECOVERY_JOBS_PER_RUN
        assert stats["recovery_mode_reverify"] == MAX_RECOVERY_MODE_REVERIFY_PER_RUN
        assert (
            stats["recovery_candidates"]
            == MAX_RECOVERY_JOBS_PER_RUN + MAX_RECOVERY_MODE_REVERIFY_PER_RUN
        )
        assert stats["recovery_candidates"] > MAX_RECOVERY_JOBS_PER_RUN
        assert len(cycle._recovery_reverify_job_ids) == (
            MAX_RECOVERY_MODE_REVERIFY_PER_RUN
        )
        assert len(cycle._recovery_job_ids) == (
            MAX_RECOVERY_JOBS_PER_RUN + MAX_RECOVERY_MODE_REVERIFY_PER_RUN
        )

    @pytest.mark.asyncio
    async def test_external_mode_job_is_never_recovered_alongside_native(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Stored EXTERNAL classification came from positive destination
        evidence; native-only recovery never overrides it."""
        filler = _make_job(db_session, 1)
        external = _make_job(db_session, 2, application_mode="EXTERNAL")
        native = _make_job(db_session, 3)
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert external.id not in cycle._recovery_job_ids
        assert native.id in cycle._recovery_job_ids
        assert stats["recovery_candidates"] == 1
        assert stats["recovery_native"] == 1

    @pytest.mark.asyncio
    async def test_cooldown_gates_only_the_reverify_pool_never_native(
        self, db_session, confirmed_profile, job_preferences
    ):
        """The 72-hour cooldown skips recently re-verified ambiguous jobs but
        never applies to native jobs (they were never re-verified)."""
        filler = _make_job(db_session, 1)
        native_recent = _make_job(db_session, 2)
        native_recent.mode_reverified_at = utc_now()
        ambiguous_recent = _make_job(db_session, 3, application_mode="AMBIGUOUS")
        ambiguous_recent.mode_reverified_at = utc_now()
        ambiguous_expired = _make_job(db_session, 4, application_mode="AMBIGUOUS")
        ambiguous_expired.mode_reverified_at = (
            utc_now() - RECOVERY_MODE_REVERIFY_COOLDOWN - timedelta(hours=1)
        )
        ambiguous_never = _make_job(db_session, 5, application_mode=None)
        db_session.commit()
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        assert native_recent.id in cycle._recovery_job_ids
        assert ambiguous_recent.id not in cycle._recovery_reverify_job_ids
        assert ambiguous_expired.id in cycle._recovery_reverify_job_ids
        assert ambiguous_never.id in cycle._recovery_reverify_job_ids
        assert stats["recovery_excluded_cooldown"] == 1
        assert stats["recovery_mode_reverify"] == 2

    @pytest.mark.asyncio
    async def test_canonical_duplicate_urls_count_once_in_recovery(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Duplicate postings collapse before any budget is spent: one row
        survives per canonical URL across both pools.

        The twins differ by a trailing slash (raw-different, canonically
        equal — the normalizer's canonical form). After dedup the survivor
        still passes the deterministic raw-URL DUPLICATE_CHECK, so exactly
        one candidate remains for the posting."""
        filler = _make_job(db_session, 1)
        url = "https://www.naukri.com/data-analyst-jobs"
        twin_a = _make_job(db_session, 2, url=url)
        twin_b = _make_job(db_session, 3, url=f"{url}/")
        twin_c = _make_job(db_session, 4, url=url, application_mode="AMBIGUOUS")
        cycle = _make_cycle(db_session, [filler])

        stats = await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )

        recovery_ids = set(cycle._recovery_job_ids)
        assert stats["recovery_pool_raw"] == 3
        assert stats["recovery_excluded_duplicate"] == 2
        assert stats["recovery_hard_filtered"] == 0
        assert len(recovery_ids & {twin_a.id, twin_b.id}) == 1
        assert twin_c.id not in recovery_ids
        assert stats["recovery_candidates"] == 1
        assert stats["recovery_native"] == 1


# ── Run 88 defect C: shared job-level application-history protection ─────


class TestSharedApplicationProtection:
    @pytest.mark.asyncio
    async def test_skipped_plus_needs_attention_job_is_not_a_candidate(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Run 88 job #81: a SKIPPED row must not launder an unresolved
        NEEDS_ATTENTION row into the candidate list (per-row predicate)."""
        job = _make_job(db_session, 1)
        cycle = _make_cycle(db_session, [job])
        _add_app(
            db_session, job, ApplicationStatus.SKIPPED.value, skip_reason="old skip"
        )
        _add_app(
            db_session,
            job,
            ApplicationStatus.NEEDS_ATTENTION.value,
            needs_attention=True,
        )

        with patch.object(
            cycle, "_process_single_job", new_callable=AsyncMock, return_value="APPLIED"
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["candidates"] == 0
        assert stats["protected_excluded"] == 1
        assert stats["zero_candidate_reason"] == (
            "0 candidates: 1 blocked by application history"
        )
        assert mock_process.await_count == 0
        decisions = cycle._candidate_stage_decisions()
        assert [d["outcome"] for d in decisions] == ["PROTECTED"]
        assert decisions[0]["job_id"] == job.id

    @pytest.mark.asyncio
    async def test_skipped_plus_external_job_still_a_candidate(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Pinned E5-R6 semantics: SKIPPED + EXTERNAL_APPLICATION rows keep
        the job eligible — protection never over-blocks."""
        job = _make_job(db_session, 1)
        cycle = _make_cycle(db_session, [job])
        _add_app(
            db_session, job, ApplicationStatus.SKIPPED.value, skip_reason="old skip"
        )
        _add_app(
            db_session,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=job.url,
            needs_attention=True,
        )

        with patch.object(
            cycle, "_process_single_job", new_callable=AsyncMock, return_value="SKIPPED"
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["candidates"] == 1
        assert stats["protected_excluded"] == 0
        assert mock_process.await_count == 1
        assert "zero_candidate_reason" not in stats

    @pytest.mark.asyncio
    async def test_external_only_job_is_excluded_with_zero_reason(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Rows without a deliberate SKIPPED row stay protected, and the
        zero-candidate run states why."""
        job = _make_job(db_session, 1)
        cycle = _make_cycle(db_session, [job])
        _add_app(
            db_session,
            job,
            ApplicationStatus.EXTERNAL_APPLICATION.value,
            external_url=job.url,
            needs_attention=True,
        )

        with patch.object(
            cycle, "_process_single_job", new_callable=AsyncMock, return_value="APPLIED"
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["candidates"] == 0
        assert stats["protected_excluded"] == 1
        assert stats["zero_candidate_reason"] == (
            "0 candidates: 1 blocked by application history"
        )
        assert mock_process.await_count == 0

    @pytest.mark.asyncio
    async def test_enqueue_stage_excludes_protected_jobs(
        self, db_session, confirmed_profile, job_preferences
    ):
        """A protected job never reaches the AI queue (no Gemini quota is
        spent on it) and is reported by name in the enqueue stats."""
        protected = _make_job(db_session, 1)
        fresh = _make_job(db_session, 2)
        _make_analysis(db_session, fresh.id)
        _make_run(db_session, [protected, fresh])
        _add_app(
            db_session, protected, ApplicationStatus.SKIPPED.value, skip_reason="old skip"
        )
        _add_app(
            db_session,
            protected,
            ApplicationStatus.NEEDS_ATTENTION.value,
            needs_attention=True,
        )
        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        cycle.current_discovery_run = db_session.execute(
            select(DiscoveryRun)
        ).scalars().first()

        stats = await cycle._apply_hard_filters_and_enqueue(
            db_session, confirmed_profile, job_preferences
        )

        assert stats["discovered"] == 2
        assert stats["protected_excluded"] == 1
        assert stats["pre_analyzed"] == 1
        assert stats["queued"] == 0
        protected_rows = [
            d for d in cycle.tracker.decisions if d["job_id"] == protected.id
        ]
        assert [d["outcome"] for d in protected_rows] == ["PROTECTED"]

    @pytest.mark.asyncio
    async def test_runner_blocks_protected_job_before_opening_page(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Defense in depth: even a direct runner call on a job with an
        in-flight attempt (APPLICATION_STARTED) plus a deliberate SKIPPED
        row never opens the job page and never starts an attempt."""
        job = _eligible_job(db_session, 9)
        _add_app(
            db_session, job, ApplicationStatus.SKIPPED.value, skip_reason="old skip"
        )
        _add_app(db_session, job, ApplicationStatus.APPLICATION_STARTED.value)
        runner = ApplicationRunner(db_session, AgentStateManager())
        mock_page = MagicMock()
        mock_page.close = AsyncMock()

        with patch(
            "backend.services.applications.runner.NaukriAdapter.start_session",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.stop_session",
            new_callable=AsyncMock,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.open_job_page",
            new_callable=AsyncMock,
        ) as mock_open_page:
            mock_open_page.return_value = JobPageResult(
                page=mock_page, security_required=False
            )
            stats = await runner.run_applications([job.id])

        assert stats["skipped"] == 1
        assert stats["attempts_started"] == 0
        assert stats["applied"] == 0
        mock_open_page.assert_not_awaited()
        rows = db_session.execute(
            select(Application).where(Application.job_id == job.id)
        ).scalars().all()
        assert len(rows) == 2, "the guard must not write another row"


# ── Run 88 defect D: run diagnostics ─────────────────────────────────────


class TestRunDiagnostics:
    @pytest.mark.asyncio
    async def test_zero_candidate_reason_explains_empty_runs(
        self, db_session, confirmed_profile, job_preferences
    ):
        """A zero-candidate run always states where the pool went."""
        # (a) No scope at all.
        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        stats = await cycle._run_applications(
            db_session, confirmed_profile, job_preferences
        )
        assert stats["candidates"] == 0
        assert stats["zero_candidate_reason"] == (
            "0 candidates: no current discovery run and no recovery backlog"
        )

        # (b) In scope, but the relevance gate rejected everything in it.
        job = _make_job(
            db_session,
            1,
            title="BPO Voice Process Executive",
            description="BPO voice process for UK clients.",
        )
        cycle_b = _make_cycle(db_session, [job])
        with patch.object(
            cycle_b, "_process_single_job", new_callable=AsyncMock, return_value="APPLIED"
        ):
            stats_b = await cycle_b._run_applications(
                db_session, confirmed_profile, job_preferences
            )
        assert stats_b["candidates"] == 0
        assert stats_b["relevance_rejected"] == 1
        assert stats_b["zero_candidate_reason"] == (
            "0 candidates: 1 rejected by relevance"
        )

    @pytest.mark.asyncio
    async def test_run_diagnostics_keys_present_and_json_serializable(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Every E5-R28 funnel key exists and the stats payload stays
        JSON-serializable for cycle_run_control.last_result."""
        current = _make_job(db_session, 1)
        backlog = _make_job(db_session, 2, application_mode="AMBIGUOUS")
        cycle = _make_cycle(db_session, [current])
        _make_analysis(db_session, backlog.id)

        await cycle._select_recovery_jobs(
            db_session, confirmed_profile, job_preferences
        )
        assert backlog.id in cycle._recovery_reverify_job_ids

        visited: list[int] = []

        async def _fake_process(db, job, profile, preferences):
            visited.append(job.id)
            cycle._last_runner_results[job.id] = {"attempts_started": 1}
            return "SKIPPED"

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        for key in (
            "protected_excluded",
            "runner_entries",
            "attempted_applications",
            "mode_reverify_attempted",
            "mode_reverify_upgraded_native",
            "mode_reverify_external_evidence",
            "mode_reverify_remaining_ambiguous",
        ):
            assert key in stats, key

        assert stats["candidates"] == 2
        assert set(visited) == {current.id, backlog.id}
        assert stats["protected_excluded"] == 0
        assert stats["runner_entries"] == 2
        assert stats["attempted_applications"] == 2
        assert stats["mode_reverify_attempted"] == 1
        assert stats["mode_reverify_upgraded_native"] == 0
        assert stats["mode_reverify_external_evidence"] == 0
        assert stats["mode_reverify_remaining_ambiguous"] == 1
        assert "zero_candidate_reason" not in stats
        json.dumps(stats)

    @pytest.mark.asyncio
    async def test_attempts_started_counts_only_real_non_dry_run_attempts(
        self, db_session, confirmed_profile, job_preferences
    ):
        """attempts_started is 0 for a dry-run inspection and 1 for a real
        non-dry-run native application; the counter resets per call."""
        dry_job = _eligible_job(db_session, 1)
        dry_runner = ApplicationRunner(db_session, AgentStateManager())
        dry_page = MagicMock()
        dry_page.close = AsyncMock()

        with patch(
            "backend.services.applications.runner.NaukriAdapter.start_session",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.stop_session",
            new_callable=AsyncMock,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.open_job_page",
            new_callable=AsyncMock,
        ) as mock_open_page, patch(
            "backend.services.applications.runner.NaukriAdapter.detect_application_type",
            new_callable=AsyncMock,
            return_value="NAUKRI_NATIVE",
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.start_application",
            new_callable=AsyncMock,
        ) as mock_start, patch(
            "backend.services.applications.runner.NaukriAdapter.detect_application_questions",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.answer_question",
            new_callable=AsyncMock,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.submit_application",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_submit:
            mock_open_page.return_value = JobPageResult(
                page=dry_page, security_required=False
            )
            dry_stats = await dry_runner.run_applications([dry_job.id], dry_run=True)

        assert dry_stats["dry_run"] == 1
        assert dry_stats["attempts_started"] == 0
        mock_start.assert_not_called()
        mock_submit.assert_not_called()

        real_job = _eligible_job(db_session, 2)
        real_runner = ApplicationRunner(db_session, AgentStateManager())
        real_page = MagicMock()
        real_page.close = AsyncMock()

        with patch(
            "backend.services.applications.runner.NaukriAdapter.start_session",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.stop_session",
            new_callable=AsyncMock,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.open_job_page",
            new_callable=AsyncMock,
        ) as mock_open_page, patch(
            "backend.services.applications.runner.NaukriAdapter.detect_application_type",
            new_callable=AsyncMock,
            return_value="NAUKRI_NATIVE",
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.start_application",
            new_callable=AsyncMock,
            return_value=ApplicationStartResult.FORM_OPENED,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.is_conversational_apply",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.detect_application_questions",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.submit_application",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.confirm_submission",
            new_callable=AsyncMock,
            return_value=True,
        ):
            mock_open_page.return_value = JobPageResult(
                page=real_page, security_required=False
            )
            real_stats = await real_runner.run_applications([real_job.id])

        assert real_stats["applied"] == 1
        assert real_stats["attempts_started"] == 1
        assert real_stats["attempts_started"] == real_stats["applied"]
