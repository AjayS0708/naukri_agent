"""E5-R21: multi-job orchestration + human-in-the-loop screening answers.

All browser/adapter behavior is mocked: no live Naukri pages, no Apply
clicks, no real browser sessions, no database writes beyond the test DBs.
Covers: shared-runner multi-job runs, duplicate protection, stop between
jobs, waiting-for-user lifecycle, scoped answer memory and the dashboard
APIs.
"""
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.cycle_run import CycleRunControl
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.models.screening import PendingQuestion, ScreeningAnswer
from backend.schemas.agent import AgentState
from backend.schemas.ai import AIRecommendation, JobQuality
from backend.schemas.application import ApplicationStartResult
from backend.services.agent_state import AgentStateManager
from backend.services.applications.answer_memory import (
    ScreeningAnswerService,
    is_sensitive_question,
    profile_data_hash,
)
from backend.services.applications.runner import ApplicationRunner
from backend.services.autonomous_cycle.coordinator import CycleCoordinator
from backend.services.autonomous_cycle.service import AutonomousCycle
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
def state_manager():
    return AgentStateManager(initial_state=AgentState.IDLE)


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
    )
    db_session.add(preferences)
    db_session.commit()
    db_session.refresh(preferences)
    return preferences


def _make_analyzed_job(
    db_session: Session,
    index: int,
    *,
    match_score: int = 80,
    title: str = "Software Engineer",
    company: str | None = None,
    posted_at: datetime | None = None,
    discovered_at: datetime | None = None,
) -> Job:
    kwargs = {}
    if posted_at is not None:
        kwargs["posted_at"] = posted_at
    if discovered_at is not None:
        kwargs["discovered_at"] = discovered_at
    job = Job(
        platform="naukri",
        external_job_id=f"e5r21job{index}",
        url=f"https://www.naukri.com/e5r21job{index}",
        title=title,
        company=company or f"Company {index}",
        description="Python developer role",
        location="Bengaluru",
        salary="5-7 LPA",
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
        application_mode="NAUKRI_NATIVE",
        **kwargs,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    db_session.add(
        JobAnalysisModel(
            job_id=job.id,
            match_score=match_score,
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


def _make_cycle(db_session: Session, jobs, *, run_token: str | None = None) -> AutonomousCycle:
    cycle = AutonomousCycle(
        max_applications=None, dry_run=False, enable_cli_output=False, run_token=run_token
    )
    cycle.current_discovery_run = DiscoveryRun(
        status="COMPLETED",
        jobs_discovered=len(jobs),
        current_run_job_ids=",".join(str(job.id) for job in jobs),
    )
    return cycle


def _stats(applied: int = 0, skipped: int = 0) -> dict:
    return {
        "total": 1,
        "processed": 1,
        "applied": applied,
        "submitted_unconfirmed": 0,
        "skipped": skipped,
        "needs_attention": 0,
        "external": 0,
        "failed": 0,
        "errors": 0,
        "auth_required": 0,
        "dry_run": 0,
        "dry_run_mode": False,
    }


# ---------------------------------------------------------------------------
# Multi-job orchestration (mission cases 1-11)
# ---------------------------------------------------------------------------


class TestMultiJobOrchestration:
    @pytest.mark.asyncio
    async def test_multiple_jobs_processed_in_one_run(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(3)]
        cycle = _make_cycle(db_session, jobs)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["APPLIED", "SKIPPED", "APPLIED"],
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 3
        assert stats["applied"] == 2
        assert stats["skipped"] == 1
        assert stats["candidates"] == 3

    @pytest.mark.asyncio
    async def test_one_failed_job_does_not_end_run(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(2)]
        cycle = _make_cycle(db_session, jobs)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["FAILED", "APPLIED"],
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 2
        assert stats["failed"] == 1
        assert stats["applied"] == 1
        assert cycle.stop_reason is None

    @pytest.mark.asyncio
    async def test_stuck_job_does_not_block_remaining_candidates(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(3)]
        cycle = _make_cycle(db_session, jobs)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["NEEDS_ATTENTION", "SKIPPED", "APPLIED"],
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 3
        assert stats["needs_attention"] == 1
        assert stats["skipped"] == 1
        assert stats["applied"] == 1
        assert cycle.stop_reason is None

    @pytest.mark.asyncio
    async def test_jobs_processed_in_priority_order(
        self, db_session, confirmed_profile, job_preferences
    ):
        same_moment = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
        job_low = _make_analyzed_job(
            db_session, 0, match_score=70, posted_at=same_moment, discovered_at=same_moment
        )
        job_high = _make_analyzed_job(
            db_session, 1, match_score=90, posted_at=same_moment, discovered_at=same_moment
        )
        job_mid = _make_analyzed_job(
            db_session, 2, match_score=80, posted_at=same_moment, discovered_at=same_moment
        )
        cycle = _make_cycle(db_session, [job_low, job_high, job_mid])

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["APPLIED", "APPLIED", "APPLIED"],
        ) as mock_process:
            await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        processed_ids = [call.args[1].id for call in mock_process.await_args_list]
        assert processed_ids == [job_high.id, job_mid.id, job_low.id]

    @pytest.mark.asyncio
    async def test_already_applied_job_excluded_from_candidates(
        self, db_session, confirmed_profile, job_preferences
    ):
        job_applied = _make_analyzed_job(db_session, 0)
        job_fresh = _make_analyzed_job(db_session, 1)
        db_session.add(Application(job_id=job_applied.id, status="APPLIED"))
        db_session.commit()
        cycle = _make_cycle(db_session, [job_applied, job_fresh])

        with patch.object(
            cycle, "_process_single_job", new_callable=AsyncMock, return_value="APPLIED"
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["candidates"] == 1
        assert mock_process.await_count == 1
        processed_job = mock_process.await_args.args[1]
        assert processed_job.id == job_fresh.id

    @pytest.mark.asyncio
    async def test_dry_run_inspects_without_submitting(
        self, db_session, state_manager, confirmed_profile, job_preferences
    ):
        job = _make_analyzed_job(db_session, 0)
        runner = ApplicationRunner(db_session, state_manager, dry_run=True)
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
            return_value=JobPageResult(page=mock_page, security_required=False),
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.detect_login_state",
            new_callable=AsyncMock,
            return_value={"authenticated": True},
        ), patch(
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
        ) as mock_submit, patch(
            "backend.services.applications.runner.NaukriAdapter.confirm_submission",
            new_callable=AsyncMock,
            return_value=True,
        ):
            stats = await runner.run_applications([job.id], dry_run=True)

        assert stats["dry_run"] == 1
        assert stats["applied"] == 0
        mock_submit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stop_between_jobs_halts_remaining_candidates(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(3)]
        cycle = _make_cycle(db_session, jobs)
        cycle._cancellation_requested = Mock(side_effect=[False, True])

        with patch.object(
            cycle, "_process_single_job", new_callable=AsyncMock, return_value="APPLIED"
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert mock_process.await_count == 1
        assert cycle.stop_reason is not None
        assert "Cancellation requested" in cycle.stop_reason
        assert cycle.stop_is_normal is True
        assert stats["applied"] == 1

    @pytest.mark.asyncio
    async def test_combined_summary_counts_every_outcome(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(5)]
        cycle = _make_cycle(db_session, jobs)

        with patch.object(
            cycle,
            "_process_single_job",
            new_callable=AsyncMock,
            side_effect=["APPLIED", "EXTERNAL", "NEEDS_ATTENTION", "FAILED", "SKIPPED"],
        ):
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["applied"] == 1
        assert stats["external"] == 1
        assert stats["needs_attention"] == 1
        assert stats["failed"] == 1
        assert stats["skipped"] == 1
        assert cycle.applications_count == 1

    @pytest.mark.asyncio
    async def test_shared_runner_closed_exactly_once(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(3)]
        cycle = _make_cycle(db_session, jobs, run_token="test-token-close")

        with patch(
            "backend.services.autonomous_cycle.service.ApplicationRunner"
        ) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.reconcile_history = AsyncMock(return_value=None)
            instance.close_session = AsyncMock()
            instance.run_applications = AsyncMock(return_value=_stats(applied=1))
            await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        assert instance.run_applications.await_count == 3
        instance.close_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_runner_constructed_once_with_shared_session_options(
        self, db_session, confirmed_profile, job_preferences
    ):
        jobs = [_make_analyzed_job(db_session, i) for i in range(2)]
        cycle = _make_cycle(db_session, jobs, run_token="test-token-construct")

        with patch(
            "backend.services.autonomous_cycle.service.ApplicationRunner"
        ) as mock_runner_cls:
            instance = mock_runner_cls.return_value
            instance.reconcile_history = AsyncMock(return_value=None)
            instance.close_session = AsyncMock()
            instance.run_applications = AsyncMock(return_value=_stats(applied=1))
            await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        assert mock_runner_cls.call_count == 1
        kwargs = mock_runner_cls.call_args.kwargs
        assert kwargs["close_session_after_run"] is False
        assert kwargs["recover_stale_state"] is True
        assert kwargs["hitl"] is True
        assert kwargs["run_token"] == "test-token-construct"
        assert kwargs["cancel_check"] is not None
        assert kwargs["progress_hook"] is not None

    @pytest.mark.asyncio
    async def test_empty_run_leaves_state_idle(
        self, db_session, confirmed_profile, job_preferences
    ):
        cycle = _make_cycle(db_session, [])

        stats = await cycle._run_applications(
            db_session, confirmed_profile, job_preferences
        )

        assert stats["candidates"] == 0
        assert cycle.state_manager.current_state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_stale_critical_error_recovered_for_shared_run(
        self, db_session, state_manager
    ):
        state_manager.transition_to(AgentState.RUNNING)
        state_manager.transition_to(AgentState.CRITICAL_ERROR)
        runner = ApplicationRunner(
            db_session, state_manager, recover_stale_state=True
        )

        with patch(
            "backend.services.applications.runner.NaukriAdapter.start_session",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.stop_session",
            new_callable=AsyncMock,
        ):
            opened = await runner.open_session()
            assert opened is True
            assert state_manager.current_state == AgentState.APPLYING
            await runner.close_session()

    @pytest.mark.asyncio
    async def test_strict_mode_rejects_non_idle_state(
        self, db_session, confirmed_profile
    ):
        state_manager = AgentStateManager(initial_state=AgentState.RUNNING)
        runner = ApplicationRunner(db_session, state_manager)

        opened = await runner.open_session()
        assert opened is False
        assert runner._open_failure == "invalid_state"

        stats = await runner.run_applications([1])
        assert stats == {"error": "Invalid state"}

    @pytest.mark.asyncio
    async def test_browser_start_failure_returns_zeroed_stats(
        self, db_session, state_manager, confirmed_profile
    ):
        job = _make_analyzed_job(db_session, 0)
        runner = ApplicationRunner(db_session, state_manager)

        with patch(
            "backend.services.applications.runner.NaukriAdapter.start_session",
            new_callable=AsyncMock,
            return_value=False,
        ):
            stats = await runner.run_applications([job.id])

        assert stats["processed"] == 0
        assert stats["applied"] == 0
        assert stats["total"] == 1
        assert stats["dry_run"] == 0
        assert state_manager.current_state == AgentState.CRITICAL_ERROR


# ---------------------------------------------------------------------------
# Human-in-the-loop wait lifecycle (mission cases 12-18)
# ---------------------------------------------------------------------------


def _make_job_and_application(db_session: Session, index: int = 0):
    job = Job(
        platform="naukri",
        external_job_id=f"hitl{index}",
        url=f"https://www.naukri.com/hitl{index}",
        title="Data Analyst",
        company="Hitl Corp",
        description="Analyst role",
        location="Bengaluru",
        status="DISCOVERED",
        application_mode="NAUKRI_NATIVE",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    application = Application(job_id=job.id, status="APPLICATION_STARTED")
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return job, application


class TestHumanInTheLoop:
    @pytest.mark.asyncio
    async def test_await_user_answer_returns_human_answer_and_emits_events(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        events: list[dict] = []

        async def hook(payload: dict) -> None:
            events.append(payload)

        runner = ApplicationRunner(
            db_session,
            state_manager,
            run_token="hitl-token",
            hitl=True,
            progress_hook=hook,
        )
        runner._hitl_poll_interval = 0.05

        task = asyncio.create_task(
            runner._await_user_answer(
                job=job,
                application=application,
                question_text="Are you open to relocation?",
                options=None,
                question_type="TEXT",
            )
        )
        await asyncio.sleep(0.15)

        pending = db_session.execute(select(PendingQuestion)).scalars().one()
        assert pending.status == "WAITING"
        assert pending.run_token == "hitl-token"
        assert pending.question_fingerprint == "are you open to relocation"

        writer = Session(bind=db_session.get_bind())
        try:
            row = writer.get(PendingQuestion, pending.id)
            row.status = "ANSWERED"
            row.answer = "Yes"
            writer.commit()
        finally:
            writer.close()

        status, answer = await asyncio.wait_for(task, timeout=5)
        assert status == "ANSWERED"
        assert answer == "Yes"

        db_session.refresh(pending)
        assert pending.status == "ANSWERED"
        assert [e["event"] for e in events] == ["waiting", "answer_received"]
        assert events[0]["pending_question_id"] == pending.id
        assert events[1]["status"] == "ANSWERED"

    @pytest.mark.asyncio
    async def test_hitl_disabled_returns_unavailable_without_pending_row(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        runner = ApplicationRunner(db_session, state_manager, hitl=False)

        status, answer = await runner._await_user_answer(
            job=job,
            application=application,
            question_text="Notice period?",
        )

        assert status == "UNAVAILABLE"
        assert answer is None
        assert db_session.execute(select(PendingQuestion)).scalars().all() == []

    @pytest.mark.asyncio
    async def test_hitl_without_run_token_returns_unavailable(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        runner = ApplicationRunner(db_session, state_manager, hitl=True, run_token=None)

        status, _ = await runner._await_user_answer(
            job=job,
            application=application,
            question_text="Notice period?",
        )

        assert status == "UNAVAILABLE"
        assert db_session.execute(select(PendingQuestion)).scalars().all() == []

    @pytest.mark.asyncio
    async def test_skip_finalizes_pending_row(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        runner = ApplicationRunner(
            db_session, state_manager, run_token="tok-skip", hitl=True
        )
        runner._hitl_poll_interval = 0.05

        task = asyncio.create_task(
            runner._await_user_answer(
                job=job, application=application, question_text="Willing to work shifts?"
            )
        )
        await asyncio.sleep(0.15)
        pending = db_session.execute(select(PendingQuestion)).scalars().one()

        writer = Session(bind=db_session.get_bind())
        try:
            row = writer.get(PendingQuestion, pending.id)
            row.status = "SKIPPED"
            writer.commit()
        finally:
            writer.close()

        status, answer = await asyncio.wait_for(task, timeout=5)
        assert status == "SKIPPED"
        assert answer is None
        db_session.refresh(pending)
        assert pending.status == "SKIPPED"

    @pytest.mark.asyncio
    async def test_record_user_skip_marks_application_skipped(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        runner = ApplicationRunner(db_session, state_manager)

        outcome = runner._record_user_skip(application, job)

        assert outcome == "SKIPPED"
        db_session.refresh(application)
        assert application.status == "SKIPPED"
        # E5-R32: the USER_SKIPPED prefix marks user-initiated skips so
        # application-history protection excludes the job from later runs.
        assert application.skip_reason == (
            "USER_SKIPPED: user skipped the screening question"
        )

    @pytest.mark.asyncio
    async def test_cancel_check_finalizes_pending_row_cancelled(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        runner = ApplicationRunner(
            db_session, state_manager, run_token="tok-cancel", hitl=True
        )
        runner.cancel_check = lambda: True

        status, answer = await asyncio.wait_for(
            runner._await_user_answer(
                job=job, application=application, question_text="Remote only?"
            ),
            timeout=5,
        )

        assert status == "CANCELLED"
        assert answer is None
        pending = db_session.execute(select(PendingQuestion)).scalars().one()
        assert pending.status == "CANCELLED"

    @pytest.mark.asyncio
    async def test_record_stop_while_waiting_marks_needs_attention(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        runner = ApplicationRunner(db_session, state_manager)

        outcome = runner._record_stop_while_waiting(application, job)

        assert outcome == "NEEDS_ATTENTION"
        db_session.refresh(application)
        assert application.status == "NEEDS_ATTENTION"
        assert application.needs_attention is True

    @pytest.mark.asyncio
    async def test_wait_timeout_expires_pending_row(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        runner = ApplicationRunner(
            db_session, state_manager, run_token="tok-expire", hitl=True
        )
        runner._hitl_timeout_seconds = 0

        status, answer = await asyncio.wait_for(
            runner._await_user_answer(
                job=job, application=application, question_text="Joining timeline?"
            ),
            timeout=5,
        )

        assert status == "EXPIRED"
        assert answer is None
        pending = db_session.execute(select(PendingQuestion)).scalars().one()
        assert pending.status == "EXPIRED"

    @pytest.mark.asyncio
    async def test_auth_recheck_after_wait_stops_run_when_logged_out(
        self, db_session, state_manager
    ):
        job, application = _make_job_and_application(db_session)
        runner = ApplicationRunner(db_session, state_manager)
        # Production reaches the post-wait auth re-check from APPLYING.
        state_manager.transition_to(AgentState.RUNNING)
        state_manager.transition_to(AgentState.SEARCHING)
        state_manager.transition_to(AgentState.FILTERING)
        state_manager.transition_to(AgentState.APPLYING)

        with patch.object(
            runner.adapter,
            "detect_login_state",
            new_callable=AsyncMock,
            return_value={"authenticated": False},
        ):
            ok = await runner._auth_ok_after_wait(Mock(), job)

        assert ok is False
        assert state_manager.current_state == AgentState.AUTH_REQUIRED
        db_session.refresh(application)
        assert application.status == "NEEDS_ATTENTION"

    @pytest.mark.asyncio
    async def test_auth_recheck_after_wait_allows_authenticated_session(
        self, db_session, state_manager
    ):
        job, _ = _make_job_and_application(db_session)
        runner = ApplicationRunner(db_session, state_manager)

        with patch.object(
            runner.adapter,
            "detect_login_state",
            new_callable=AsyncMock,
            return_value={"authenticated": True},
        ):
            ok = await runner._auth_ok_after_wait(Mock(), job)

        assert ok is True
        assert state_manager.current_state == AgentState.IDLE

    def test_coordinator_waiting_flag_visible_in_snapshot(self, db_session):
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db_session)
        assert ok

        coord.set_waiting(token, 42, db=db_session)
        snap = coord.snapshot(db=db_session)
        active = snap["active_run"]
        assert active["waiting_for_user"] is True
        assert active["waiting_for_question_id"] == 42
        assert active["display_status"] == "WAITING_FOR_USER"
        assert active["status"] == "RUNNING"

        coord.clear_waiting(token, db=db_session)
        snap = coord.snapshot(db=db_session)
        active = snap["active_run"]
        assert active["waiting_for_user"] is False
        assert active["waiting_for_question_id"] is None
        assert active["display_status"] == "RUNNING"


# ---------------------------------------------------------------------------
# Screening-answer memory (mission cases 19-25)
# ---------------------------------------------------------------------------


class TestScreeningAnswerMemory:
    def test_global_answer_reused_across_jobs_with_reuse_count(self, db_session):
        service = ScreeningAnswerService(db_session)
        row = service.save_user_answer(
            "Are you willing to work overtime?",
            "Yes",
            scope="GLOBAL",
            options=["Yes", "No"],
            answer_type="SINGLE_CHOICE",
        )
        assert row.scope == "GLOBAL"

        found_a = service.find(
            "Are you willing to work overtime?",
            options=["Yes", "No"],
            employer="Acme",
            job_id=1,
        )
        found_b = service.find(
            "Are you willing to work overtime?",
            options=["Yes", "No"],
            employer="Globex",
            job_id=2,
        )
        assert found_a is not None and found_a.answer == "Yes"
        assert found_b is not None and found_b.answer == "Yes"

        service.mark_reused(found_a)
        service.mark_reused(found_a)
        db_session.refresh(found_a)
        assert found_a.reuse_count == 2
        assert found_a.last_used_at is not None

    def test_job_scope_answer_isolated_to_same_job(self, db_session):
        service = ScreeningAnswerService(db_session)
        service.save_user_answer(
            "Do you have 3+ years of Python?", "Yes", scope="JOB", job_id=10
        )

        same = service.find("Do you have 3+ years of Python?", job_id=10)
        other = service.find("Do you have 3+ years of Python?", job_id=11)
        assert same is not None
        assert other is None

    def test_employer_scope_answer_matches_same_employer_only(self, db_session):
        service = ScreeningAnswerService(db_session)
        service.save_user_answer(
            "Open to hybrid work?", "Yes", scope="EMPLOYER", employer="Acme"
        )

        same_employer = service.find("Open to hybrid work?", employer="Acme", job_id=99)
        other_employer = service.find("Open to hybrid work?", employer="Globex", job_id=7)
        assert same_employer is not None
        assert other_employer is None

    def test_sensitive_questions_never_stored_or_returned(self, db_session):
        service = ScreeningAnswerService(db_session)
        assert is_sensitive_question("What is your password?")
        assert is_sensitive_question("Enter the OTP sent to your phone")

        with pytest.raises(ValueError):
            service.save_user_answer("What is your password?", "hunter2", scope="GLOBAL")

        service.save_user_answer("Preferred timezone?", "IST", scope="GLOBAL")
        assert service.find("What is your password?") is None
        assert db_session.execute(select(ScreeningAnswer)).scalars().all() != []

    def test_context_sensitive_global_requires_authorisation(self, db_session):
        service = ScreeningAnswerService(db_session)
        with pytest.raises(ValueError):
            service.save_user_answer(
                "What is your expected CTC?", "12 LPA", scope="GLOBAL"
            )

        row = service.save_user_answer(
            "What is your expected CTC?",
            "12 LPA",
            scope="GLOBAL",
            allow_global_reuse=True,
        )
        assert row.scope == "GLOBAL"
        assert row.context_sensitive is True

        job_scoped = service.save_user_answer(
            "What is your expected CTC?", "10 LPA", scope="JOB", job_id=5
        )
        assert job_scoped.scope == "JOB"

    def test_profile_hash_change_makes_answer_stale(self, db_session):
        profile_a = SimpleNamespace(data={"name": "A", "skills": ["Python"]})
        profile_b = SimpleNamespace(data={"name": "A", "skills": ["COBOL"]})
        service = ScreeningAnswerService(db_session)
        service.save_user_answer(
            "How many years of experience do you have?",
            "2",
            scope="JOB",
            job_id=3,
            source="PROFILE",
            profile_hash=profile_data_hash(profile_a),
        )

        fresh = service.find(
            "How many years of experience do you have?",
            job_id=3,
            profile=profile_a,
        )
        stale = service.find(
            "How many years of experience do you have?",
            job_id=3,
            profile=profile_b,
        )
        assert fresh is not None
        assert stale is None

    def test_option_list_change_returns_none(self, db_session):
        service = ScreeningAnswerService(db_session)
        service.save_user_answer(
            "Are you an immediate joiner?",
            "Yes",
            scope="JOB",
            job_id=8,
            options=["Yes", "No"],
        )

        same_options = service.find(
            "Are you an immediate joiner?", options=["Yes", "No"], job_id=8
        )
        changed_options = service.find(
            "Are you an immediate joiner?", options=["No", "Maybe"], job_id=8
        )
        assert same_options is not None
        assert changed_options is None

    def test_upsert_replaces_existing_answer_for_same_scope(self, db_session):
        service = ScreeningAnswerService(db_session)
        service.save_user_answer("Notice period?", "30 days", scope="JOB", job_id=1)
        service.save_user_answer("Notice period?", "45 days", scope="JOB", job_id=1)

        rows = db_session.execute(
            select(ScreeningAnswer).where(ScreeningAnswer.scope == "JOB")
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].answer == "45 days"

    def test_delete_answer_prevents_reuse(self, db_session):
        service = ScreeningAnswerService(db_session)
        row = service.save_user_answer(
            "Willing to travel 50%?", "Yes", scope="GLOBAL"
        )

        assert service.delete_answer(row.id) is True
        assert service.find("Willing to travel 50%?") is None
        assert service.delete_answer(row.id) is False


# ---------------------------------------------------------------------------
# Dashboard APIs (mission cases 26-28)
# ---------------------------------------------------------------------------


def _seed_waiting_question(db: Session, coordinator, run_token: str, **kwargs) -> PendingQuestion:
    pending = PendingQuestion(
        run_token=run_token,
        question_text=kwargs.get("question_text", "Are you open to relocation?"),
        question_fingerprint=kwargs.get(
            "question_fingerprint", "are you open to relocation"
        ),
        question_type=kwargs.get("question_type", "TEXT"),
        options=kwargs.get("options"),
        employer=kwargs.get("employer", "Acme"),
        job_title=kwargs.get("job_title", "Data Analyst"),
        job_id=kwargs.get("job_id"),
        status="WAITING",
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)
    coordinator.set_waiting(run_token, pending.id, db=db)
    return pending


class TestDashboardAndAPI:
    def test_pending_question_answer_flow_via_api(self, db, client):
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db)
        assert ok

        job = Job(
            platform="naukri",
            external_job_id="api-flow-job",
            url="https://www.naukri.com/api-flow-job",
            title="Data Analyst",
            company="Acme",
            description="Analyst role",
            location="Bengaluru",
            status="DISCOVERED",
            application_mode="NAUKRI_NATIVE",
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        pending = _seed_waiting_question(db, coord, token, job_id=job.id)

        resp = client.get("/api/autonomous-cycle/pending-question")
        assert resp.status_code == 200
        body = resp.json()
        assert body["found"] is True
        assert body["pending_question_id"] == pending.id
        assert body["question_text"] == "Are you open to relocation?"
        assert body["job_title"] == "Data Analyst"

        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={
                "pending_question_id": pending.id,
                "run_token": token,
                "answer": "Yes",
                "remember": True,
                "scope": "JOB",
            },
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "ANSWERED"
        assert result["saved_to_memory"] is True
        assert result["answer_scope"] == "JOB"

        db.refresh(pending)
        assert pending.status == "ANSWERED"
        assert pending.answer == "Yes"
        assert pending.answered_via == "USER"

        snap = coord.snapshot(db=db)
        assert snap["active_run"]["waiting_for_user"] is False
        assert snap["active_run"]["waiting_for_question_id"] is None

        saved = ScreeningAnswerService(db).find(
            "Are you open to relocation?", job_id=pending.job_id
        )
        assert saved is not None
        assert saved.answer == "Yes"

        resp = client.get("/api/autonomous-cycle/pending-question")
        assert resp.json()["found"] is False

    def test_answer_endpoint_validation_errors(self, db, client):
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db)
        assert ok

        # 404 unknown id
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={"pending_question_id": 99999, "answer": "Yes"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PENDING_QUESTION_NOT_FOUND"

        # 409 foreign run_token
        pending = _seed_waiting_question(db, coord, token)
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={
                "pending_question_id": pending.id,
                "run_token": "some-other-token",
                "answer": "Yes",
            },
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "PENDING_QUESTION_STALE"

        # 400 missing answer
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={"pending_question_id": pending.id, "run_token": token, "answer": ""},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "ANSWER_REQUIRED"

        # 400 invalid option
        choice = _seed_waiting_question(
            db,
            coord,
            token,
            question_text="Preferred work mode?",
            question_fingerprint="preferred work mode",
            question_type="SINGLE_CHOICE",
            options=["Remote", "Hybrid"],
        )
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={
                "pending_question_id": choice.id,
                "run_token": token,
                "answer": "Onsite",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_OPTION"

        # 400 sensitive question
        sensitive = _seed_waiting_question(
            db,
            coord,
            token,
            question_text="What is your password?",
            question_fingerprint="what is your password",
        )
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={
                "pending_question_id": sensitive.id,
                "run_token": token,
                "answer": "hunter2",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "SENSITIVE_QUESTION"

        # 400 context-sensitive GLOBAL without authorisation
        ctc = _seed_waiting_question(
            db,
            coord,
            token,
            question_text="What is your expected CTC?",
            question_fingerprint="what is your expected ctc",
        )
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={
                "pending_question_id": ctc.id,
                "run_token": token,
                "answer": "12 LPA",
                "remember": True,
                "scope": "GLOBAL",
                "allow_global_reuse": False,
            },
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "MEMORY_SAVE_REFUSED"

    def test_skip_flow_via_api(self, db, client):
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db)
        assert ok

        pending = _seed_waiting_question(db, coord, token, question_text="Shift work?")
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={"pending_question_id": pending.id, "run_token": token, "skip": True},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "SKIPPED"

        db.refresh(pending)
        assert pending.status == "SKIPPED"
        snap = coord.snapshot(db=db)
        assert snap["active_run"]["waiting_for_user"] is False

        # Answering a handled question is a conflict.
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={"pending_question_id": pending.id, "run_token": token, "answer": "Yes"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "PENDING_QUESTION_NOT_WAITING"

    def test_screening_answers_crud_via_api(self, db, client):
        service = ScreeningAnswerService(db)
        row = service.save_user_answer(
            "Are you willing to relocate?",
            "Yes",
            scope="JOB",
            job_id=1,
            options=["Yes", "No"],
        )

        resp = client.get("/api/autonomous-cycle/screening-answers")
        assert resp.status_code == 200
        listed = resp.json()
        assert len(listed) == 1
        assert listed[0]["id"] == row.id
        assert listed[0]["answer"] == "Yes"

        resp = client.put(
            f"/api/autonomous-cycle/screening-answers/{row.id}",
            json={"answer": "No"},
        )
        assert resp.status_code == 200
        assert resp.json()["answer"] == "No"

        # Widening a context-sensitive answer to GLOBAL needs authorisation.
        ctc = service.save_user_answer(
            "What is your expected CTC?", "10 LPA", scope="JOB", job_id=2
        )
        resp = client.put(
            f"/api/autonomous-cycle/screening-answers/{ctc.id}",
            json={"scope": "GLOBAL", "allow_global_reuse": False},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "MEMORY_SAVE_REFUSED"

        resp = client.put(
            f"/api/autonomous-cycle/screening-answers/{ctc.id}",
            json={"scope": "GLOBAL", "allow_global_reuse": True},
        )
        assert resp.status_code == 200
        assert resp.json()["scope"] == "GLOBAL"

        resp = client.delete(f"/api/autonomous-cycle/screening-answers/{row.id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert service.find("Are you willing to relocate?", job_id=1) is None

        resp = client.delete("/api/autonomous-cycle/screening-answers/99999")
        assert resp.status_code == 404

    def test_progress_document_persisted_to_control_row(self, db):
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db)
        assert ok

        cycle = AutonomousCycle(
            max_applications=None,
            dry_run=False,
            enable_cli_output=False,
            run_token=token,
        )
        cycle._run_progress = {
            "candidates_total": 3,
            "processed": 2,
            "applied": 1,
            "remaining": 1,
            "current_step": "job_done",
        }
        cycle._persist_progress()

        row = db.get(CycleRunControl, 1)
        assert row is not None
        assert row.progress["processed"] == 2
        assert row.progress["applied"] == 1

        snap = coord.snapshot(db=db)
        assert snap["active_run"]["progress"]["processed"] == 2

    def test_stop_while_waiting_sets_cancellation_flag(self, db, client):
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db)
        assert ok
        _seed_waiting_question(db, coord, token)

        resp = client.post(
            "/api/autonomous-cycle/stop", json={"run_token": token}
        )
        assert resp.status_code == 200
        assert resp.json()["cancel_requested"] is True
        assert coord.is_cancellation_requested(token, db=db) is True

        snap = coord.snapshot(db=db)
        assert snap["active_run"]["status"] == "CANCELLING"
        assert snap["active_run"]["cancel_requested"] is True
