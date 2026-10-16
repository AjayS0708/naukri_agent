"""E5-R32: screening-answer lifecycle, per-job queue skips, apprenticeship
eligibility and batch reconciliation.

Evidence (stalled run 2026-10-16 09:06–09:17 UTC): job 422 waited 5m23s on a
recruiter intro misclassified as a question, the Apply Queue never fetched the
pending question (it told the operator to use the Overview page), the AMBIGUOUS
paths reported NEEDS_ATTENTION without creating rows (stats said 10, rows said
7), and an apprenticeship posting slipped through a NULL employment_type.

All browser/adapter behavior is mocked: no live Naukri pages, no Apply clicks,
no real browser sessions, no database writes beyond the test DBs.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.models.screening import PendingQuestion
from backend.schemas.ai import AIRecommendation, JobQuality
from backend.schemas.application import ApplicationStatus
from backend.services.agent_state import AgentStateManager
from backend.services.applications import ApplicationService
from backend.services.applications.protection import (
    USER_SKIP_PREFIX,
    is_protected_history,
    is_user_skip_reason,
    protected_from_candidate_selection,
    protected_job_ids,
    user_skipped_job_ids,
)
from backend.services.applications.runner import ApplicationRunner
from backend.services.autonomous_cycle.coordinator import CycleCoordinator
from backend.services.matching.engine import (
    MatchDecisionEnum,
    MatchEngine,
    apprenticeship_excluded_reason,
)
from backend.services.naukri.adapter import JobPageResult, NaukriAdapter

TEST_DATABASE_URL = "sqlite:///:memory:"


# ── Fixtures (own in-memory DB for runner/engine tests) ──────────────────────


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
    description: str = "Python and SQL reporting role",
    employment_type: str | None = "Full-time",
    application_mode: str | None = "NAUKRI_NATIVE",
    status: str = "DISCOVERED",
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"e5r32job{index}",
        url=f"https://www.naukri.com/e5r32job{index}",
        title=title,
        company=f"Company {index}",
        description=description,
        location="Bengaluru",
        salary="5-7 LPA",
        salary_max=7.0,
        experience="0-2 years",
        employment_type=employment_type,
        status=status,
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


def _rows_for(db_session: Session, job_id: int) -> list[Application]:
    return (
        db_session.execute(
            select(Application).where(Application.job_id == job_id).order_by(Application.id)
        )
        .scalars()
        .all()
    )


# ── 1. Recruiter intro classification ────────────────────────────────────────

INTRO_TEXT = (
    "Thank you for showing interest in our company. "
    "Kindly answer all the recruiter's questions below."
)


class TestRecruiterIntroIsNeverAQuestion:
    def test_intro_without_options_is_nudge_despite_composer(self):
        # The composer is present (a text question COULD be typed) but the
        # intro only announces the questionnaire — answering it re-renders.
        assert (
            NaukriAdapter.classify_conversational_message(INTRO_TEXT, False, True)
            == "nudge"
        )

    def test_intro_variants_are_nudges(self):
        for text in (
            INTRO_TEXT,
            "Please answer all the questions below to proceed.",
            "We request you to answer all the recruiter's questions.",
        ):
            assert (
                NaukriAdapter.classify_conversational_message(text, False, True)
                == "nudge"
            ), text

    def test_application_received_still_info(self):
        # Guard: the new intro patterns must not swallow plain info messages.
        assert (
            NaukriAdapter.classify_conversational_message(
                "Application received.", False, False
            )
            == "info"
        )

    def test_radio_options_still_win(self):
        # Ordering guard: genuine optioned questions are never nudges.
        assert (
            NaukriAdapter.classify_conversational_message(INTRO_TEXT, True, False)
            == "question"
        )


# ── 2. Last-visible bot message detection ────────────────────────────────────


class _BotElement:
    def __init__(self, text: str, visible: bool = True):
        self._text = text
        self._visible = visible

    async def is_visible(self) -> bool:
        return self._visible

    async def inner_text(self) -> str:
        return self._text


class _Drawer:
    """Minimal conversational drawer: bot messages + optional composer."""

    def __init__(self, bot_messages: list[_BotElement], composer=None, radios=None):
        self._bot_messages = bot_messages
        self._composer = composer
        self._radios = radios or []

    async def query_selector_all(self, sel: str):
        if sel in (".botMsg span", ".botMsg"):
            return self._bot_messages
        if sel == 'input[type="radio"]':
            return self._radios
        return []

    async def query_selector(self, sel: str):
        if sel == '[contenteditable="true"]':
            return self._composer
        return None


class TestLastBotMessageDetection:
    @pytest.mark.asyncio
    async def test_latest_message_wins_over_stale_intro(self):
        adapter = NaukriAdapter()
        drawer = _Drawer(
            [
                _BotElement(INTRO_TEXT),
                _BotElement("What is your notice period?"),
            ],
            composer=SimpleNamespace(is_visible=AsyncMock(return_value=True)),
        )
        conv = await adapter._detect_conversational_question(drawer)
        assert conv is not None
        assert conv["question"] == "What is your notice period?"
        assert conv["kind"] == "question"

    @pytest.mark.asyncio
    async def test_invisible_latest_message_is_ignored(self):
        adapter = NaukriAdapter()
        drawer = _Drawer(
            [
                _BotElement("Are you open to relocation?"),
                _BotElement("stale hidden prompt", visible=False),
            ],
            composer=SimpleNamespace(is_visible=AsyncMock(return_value=True)),
        )
        conv = await adapter._detect_conversational_question(drawer)
        assert conv["question"] == "Are you open to relocation?"

    @pytest.mark.asyncio
    async def test_no_bot_messages_returns_none(self):
        adapter = NaukriAdapter()
        assert await adapter._detect_conversational_question(_Drawer([])) is None


# ── 3. Apprenticeship eligibility (job 422) ──────────────────────────────────

APPRENTICE_DESCRIPTION = (
    "Python and SQL reporting role. Job Type: 1-Year Apprenticeship. "
    "Stipend: 21,500/month."
)


class TestApprenticeshipExclusion:
    def test_job422_shape_is_excluded(self, db_session, confirmed_profile, job_preferences):
        job = _make_job(
            db_session,
            1,
            employment_type=None,
            description=APPRENTICE_DESCRIPTION,
        )
        reason = apprenticeship_excluded_reason(job, job_preferences)
        assert reason is not None
        assert "Apprenticeship role excluded" in reason

    def test_no_marker_passes(self, db_session, confirmed_profile, job_preferences):
        job = _make_job(db_session, 2, title=".NET Developer",
                        description="C# and .NET API development")
        assert apprenticeship_excluded_reason(job, job_preferences) is None

    def test_preference_allowing_apprenticeship_passes(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 3, employment_type=None,
                        description=APPRENTICE_DESCRIPTION)
        job_preferences.employment_types = ["Full-time", "Apprenticeship"]
        db_session.commit()
        assert apprenticeship_excluded_reason(job, job_preferences) is None

    @staticmethod
    def _run_checks(engine, job, profile, preferences):
        """Run deterministic checks with the pre-apprenticeship rules pinned
        to PASS so the apprenticeship gate is the deciding rule."""
        from contextlib import ExitStack

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "backend.services.matching.engine.job_relevance_check",
                    return_value=(True, ""),
                )
            )
            stack.enter_context(
                patch(
                    "backend.services.matching.engine.experience_passes_fresher_rule",
                    return_value=(True, ""),
                )
            )
            stack.enter_context(
                patch(
                    "backend.services.matching.engine.is_strict_it_job",
                    return_value=True,
                )
            )
            stack.enter_context(
                patch(
                    "backend.services.matching.engine.evaluate_salary_gate",
                    return_value=(True, None),
                )
            )
            return engine._run_deterministic_checks(job, profile, preferences)

    def test_engine_deterministic_check_blocks_apprenticeship(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 4, employment_type=None,
                        description=APPRENTICE_DESCRIPTION)
        decision = self._run_checks(
            MatchEngine(db_session), job, confirmed_profile, job_preferences
        )
        assert decision.decision == MatchDecisionEnum.SKIP
        assert decision.failed_rules == ["APPRENTICESHIP"]
        assert "Apprenticeship role excluded" in decision.reason

    def test_engine_deterministic_check_allows_dotnet_regression(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 5, title=".NET Developer",
                        description="C# and .NET API development")
        decision = self._run_checks(
            MatchEngine(db_session), job, confirmed_profile, job_preferences
        )
        assert decision.decision == MatchDecisionEnum.APPLY
        assert "APPRENTICESHIP_CHECK" in decision.matched_rules

    def test_safety_gate_blocks_apprenticeship_with_shared_reason(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 6, employment_type=None,
                        description=APPRENTICE_DESCRIPTION)
        allowed, reason = ApplicationService(db_session).run_final_safety_gate(
            job, confirmed_profile, job_preferences
        )
        assert allowed is False
        assert reason == apprenticeship_excluded_reason(job, job_preferences)

    def test_safety_gate_dotnet_regression_allowed(
        self, db_session, confirmed_profile, job_preferences
    ):
        job_preferences.job_titles = [*job_preferences.job_titles, ".NET Developer"]
        db_session.commit()
        job = _make_job(db_session, 7, title=".NET Developer",
                        description="C# and .NET API development")
        allowed, reason = ApplicationService(db_session).run_final_safety_gate(
            job, confirmed_profile, job_preferences
        )
        assert allowed is True, reason

    def test_safety_gate_allows_when_preference_lists_apprenticeship(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 8, employment_type=None,
                        description=APPRENTICE_DESCRIPTION)
        job_preferences.employment_types = ["Full-time", "Apprenticeship"]
        db_session.commit()
        allowed, reason = ApplicationService(db_session).run_final_safety_gate(
            job, confirmed_profile, job_preferences
        )
        assert allowed is True, reason


# ── 4. User-skip protection semantics ────────────────────────────────────────


class TestUserSkipProtection:
    def test_is_user_skip_reason(self):
        assert is_user_skip_reason(f"{USER_SKIP_PREFIX}: skipped by the user")
        assert not is_user_skip_reason("Duplicate application")
        assert not is_user_skip_reason(None)

    def test_is_protected_history_semantics(self):
        user_row = ("SKIPPED", f"{USER_SKIP_PREFIX}: skipped by the user")
        auto_row = ("SKIPPED", "Duplicate application")
        assert is_protected_history([]) is False
        # An operator skip protects; an automated skip stays re-processable.
        assert is_protected_history([user_row]) is True
        assert is_protected_history([auto_row]) is False
        # Blocking rows always protect.
        assert is_protected_history([("APPLIED", None)]) is True
        assert is_protected_history([auto_row, ("NEEDS_ATTENTION", None)]) is True

    def test_bulk_helpers_and_sql_predicate(self, db_session):
        user_job = _make_job(db_session, 10)
        auto_job = _make_job(db_session, 11)
        applied_job = _make_job(db_session, 12)
        service = ApplicationService(db_session)
        service.record_application_skip(
            user_job, f"{USER_SKIP_PREFIX}: skipped by the user in the apply queue"
        )
        service.record_application_skip(auto_job, "No AI analysis available")
        db_session.add(
            Application(job_id=applied_job.id, status=ApplicationStatus.APPLIED.value)
        )
        db_session.commit()

        ids = [user_job.id, auto_job.id, applied_job.id]
        assert protected_job_ids(db_session, ids) == {user_job.id, applied_job.id}
        assert user_skipped_job_ids(db_session, ids) == {user_job.id}

        sql_protected = set(
            db_session.execute(
                select(Job.id).where(protected_from_candidate_selection())
            )
            .scalars()
            .all()
        )
        assert sql_protected == {user_job.id, applied_job.id}

    def test_eligibility_reports_user_skipped_before_history(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 13)
        service = ApplicationService(db_session)
        service.record_application_skip(
            job, f"{USER_SKIP_PREFIX}: skipped by the user in the apply queue"
        )
        from backend.services.manual_apply import ManualApplyService

        eligible, reason = ManualApplyService(db_session)._eligibility(
            job,
            protected_ids=set(),
            profile=None,
            preferences=None,
            match_engine=None,
            user_skipped_ids={job.id},
        )
        assert eligible is False
        assert reason == "user_skipped"
        # Control: without user-skip knowledge the later gates decide.
        _, fallback = ManualApplyService(db_session)._eligibility(
            job,
            protected_ids=set(),
            profile=None,
            preferences=None,
            match_engine=None,
            user_skipped_ids=set(),
        )
        assert fallback != "user_skipped"


# ── 5. Runner: user skip at the job boundary, batch continues ────────────────


class TestRunnerUserSkipBoundary:
    @staticmethod
    def _patches_session():
        return (
            patch(
                "backend.services.applications.runner.NaukriAdapter.start_session",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "backend.services.applications.runner.NaukriAdapter.stop_session",
                new_callable=AsyncMock,
            ),
        )

    @pytest.mark.asyncio
    async def test_skip_request_recorded_and_batch_continues(
        self, db_session, confirmed_profile, job_preferences
    ):
        requested = _make_job(db_session, 20)
        untouched = _make_job(db_session, 21)
        runner = ApplicationRunner(
            db_session,
            AgentStateManager(),
            skip_request_check=lambda job_id: job_id == requested.id,
        )
        start, stop = self._patches_session()
        with start, stop:
            stats = await runner.run_applications([requested.id, untouched.id])

        assert stats["processed"] == 2
        assert stats["skipped"] == 2
        assert stats["outcome_total"] == stats["processed"]
        req_rows = _rows_for(db_session, requested.id)
        assert len(req_rows) == 1
        assert (req_rows[0].skip_reason or "").startswith(USER_SKIP_PREFIX)
        # The other job keeps its real (non-user) outcome and stays
        # re-processable — only user skips are protected.
        other_rows = _rows_for(db_session, untouched.id)
        assert len(other_rows) == 1
        assert other_rows[0].skip_reason == "No AI analysis available"
        assert protected_job_ids(db_session, [requested.id, untouched.id]) == {
            requested.id
        }

    @pytest.mark.asyncio
    async def test_faulty_skip_callback_does_not_break_run(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 22)

        def broken(_job_id: int) -> bool:
            raise RuntimeError("callback exploded")

        runner = ApplicationRunner(db_session, AgentStateManager(), skip_request_check=broken)
        start, stop = self._patches_session()
        with start, stop:
            stats = await runner.run_applications([job.id])

        assert stats["processed"] == 1
        assert stats["skipped"] == 1
        rows = _rows_for(db_session, job.id)
        assert rows[0].skip_reason == "No AI analysis available"

    @pytest.mark.asyncio
    async def test_user_skipped_job_is_protected_without_callback(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 23)
        _make_analysis(db_session, job.id)
        ApplicationService(db_session).record_application_skip(
            job, f"{USER_SKIP_PREFIX}: skipped by the user in the apply queue"
        )

        runner = ApplicationRunner(db_session, AgentStateManager())
        start, stop = self._patches_session()
        with start as mock_start, stop:
            with patch(
                "backend.services.applications.runner.NaukriAdapter.open_job_page",
                new_callable=AsyncMock,
            ) as mock_open:
                stats = await runner.run_applications([job.id])

        assert stats["skipped"] == 1
        mock_start.assert_awaited()  # session opened…
        mock_open.assert_not_awaited()  # …but no page was ever opened
        # No second row: the guard skips silently.
        assert len(_rows_for(db_session, job.id)) == 1


# ── 6. Queue skip request: idle / queued / processed / refused ───────────────


class TestQueueSkipRequest:
    def test_skip_records_immediately_when_idle_and_is_idempotent(self, db, client):
        job = _make_job(db, 30)

        resp = client.post("/api/manual-apply/skip", json={"job_id": job.id})
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "RECORDED"
        assert body["job_id"] == job.id

        db.expire_all()
        rows = _rows_for(db, job.id)
        assert len(rows) == 1
        assert (rows[0].skip_reason or "").startswith(USER_SKIP_PREFIX)

        # Second request is honestly refused.
        resp = client.post("/api/manual-apply/skip", json={"job_id": job.id})
        assert resp.json()["mode"] == "ALREADY_SKIPPED"
        db.expire_all()
        assert len(_rows_for(db, job.id)) == 1

    def test_queue_listing_excludes_user_skipped_job(self, db, client):
        job = _make_job(db, 31)
        client.post("/api/manual-apply/skip", json={"job_id": job.id})

        data = client.get("/api/manual-apply/eligible").json()
        by_id = {item["job_id"]: item for item in data["items"]}
        assert by_id[job.id]["eligible"] is False
        assert by_id[job.id]["exclusion_reason"] == "user_skipped"
        assert (by_id[job.id]["skip_reason"] or "").startswith(USER_SKIP_PREFIX)

    def test_skip_refused_over_blocking_history(self, db, client):
        job = _make_job(db, 32)
        db.add(
            Application(job_id=job.id, status=ApplicationStatus.APPLIED.value)
        )
        db.commit()

        resp = client.post("/api/manual-apply/skip", json={"job_id": job.id})
        assert resp.json()["mode"] == "NOT_ELIGIBLE"
        db.expire_all()
        rows = _rows_for(db, job.id)
        assert len(rows) == 1, "no fake skip row over a real attempt"
        assert rows[0].status == ApplicationStatus.APPLIED.value

    def test_skip_queued_while_batch_is_active(self, db, client):
        import backend.services.manual_apply.service as manual_service

        job = _make_job(db, 33)
        processed = _make_job(db, 34)
        stub = SimpleNamespace(
            _run_token="active-token",
            _processed_job_ids={processed.id},
            _skip_requests=set(),
        )
        previous = manual_service._active_manual_service
        manual_service._active_manual_service = stub
        try:
            resp = client.post("/api/manual-apply/skip", json={"job_id": job.id})
            assert resp.json()["mode"] == "QUEUED"
            assert job.id in stub._skip_requests

            resp = client.post(
                "/api/manual-apply/skip", json={"job_id": processed.id}
            )
            assert resp.json()["mode"] == "ALREADY_PROCESSED"
        finally:
            manual_service._active_manual_service = previous

        # Nothing was written while the batch was live.
        db.expire_all()
        assert _rows_for(db, job.id) == []

    def test_drain_records_only_unprocessed_requests(self, db_session):
        from backend.services.manual_apply import ManualApplyService

        pending_job = _make_job(db_session, 35)
        processed_job = _make_job(db_session, 36)
        service = ManualApplyService(db_session)
        service._run_token = "tok"
        service._skip_requests = {pending_job.id, processed_job.id}
        service._processed_job_ids = {processed_job.id}

        service._drain_skip_requests(db_session)

        assert service._skip_requests == set()
        pending_rows = _rows_for(db_session, pending_job.id)
        assert len(pending_rows) == 1
        assert (pending_rows[0].skip_reason or "").startswith(USER_SKIP_PREFIX)
        # The processed job keeps its real outcome — the drain drops its request.
        assert _rows_for(db_session, processed_job.id) == []

    def test_unknown_job_is_not_eligible(self, client):
        resp = client.post("/api/manual-apply/skip", json={"job_id": 999999})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "NOT_ELIGIBLE"


# ── 7. Screening wait timeout: explicit reason, batch continues ──────────────


class TestWaitTimeoutLifecycle:
    def test_record_wait_timeout_marks_needs_attention(
        self, db_session, confirmed_profile, job_preferences
    ):
        job = _make_job(db_session, 40)
        application = Application(job_id=job.id, status="APPLICATION_STARTED")
        db_session.add(application)
        db_session.commit()
        db_session.refresh(application)

        runner = ApplicationRunner(db_session, AgentStateManager())
        outcome = runner._record_wait_timeout(application, job)

        assert outcome == "NEEDS_ATTENTION"
        db_session.refresh(application)
        assert application.status == ApplicationStatus.NEEDS_ATTENTION.value
        assert application.needs_attention is True
        assert "Screening question timed out" in (application.skip_reason or "")

    @pytest.mark.asyncio
    async def test_expired_human_only_wait_continues_batch(
        self, db_session, confirmed_profile, job_preferences
    ):
        """End to end: an apprenticeship-willingness question never reaches
        profile/AI, the wait expires, the job is recorded NEEDS_ATTENTION with
        the timeout reason, and the NEXT job in the batch still runs."""
        timed_out = _make_job(db_session, 41)
        _make_analysis(db_session, timed_out.id)
        next_job = _make_job(db_session, 42)

        runner = ApplicationRunner(
            db_session,
            AgentStateManager(),
            run_token="r32-timeout",
            hitl=True,
        )
        runner._hitl_timeout_seconds = 0
        runner._hitl_poll_interval = 0.01

        question = {"question": "Are you okay with a 1-year apprenticeship?", "required": True}
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
            new_callable=AsyncMock, return_value=[question],
        ), patch(
            "backend.services.applications.runner.NaukriAdapter.answer_question",
            new_callable=AsyncMock,
        ) as mock_answer, patch.object(
            ApplicationRunner, "_get_answer_from_profile", return_value=None
        ) as profile_mock, patch.object(
            ApplicationRunner, "_get_ai_answer", return_value=None
        ) as ai_mock:
            from backend.schemas.application import ApplicationStartResult

            mock_page = MagicMock()
            mock_page.close = AsyncMock()
            mock_open.return_value = JobPageResult(page=mock_page, security_required=False)
            mock_start.return_value = ApplicationStartResult.FORM_OPENED
            stats = await runner.run_applications([timed_out.id, next_job.id])

        # E5-R32: profile/AI never touch a human-only question.
        profile_mock.assert_not_called()
        ai_mock.assert_not_called()
        mock_answer.assert_not_called()

        assert stats["processed"] == 2
        assert stats["needs_attention"] == 1
        assert stats["skipped"] == 1  # next job still ran (no analysis → skip)
        assert stats["outcome_total"] == stats["processed"]

        rows = _rows_for(db_session, timed_out.id)
        assert len(rows) == 1
        assert rows[0].status == ApplicationStatus.NEEDS_ATTENTION.value
        assert "Screening question timed out" in (rows[0].skip_reason or "")


# ── 8. Human-only guard ──────────────────────────────────────────────────────


class TestHumanOnlyGuard:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Are you okay with a 1-year apprenticeship?", True),
            ("Willingness to do an apprenticeship role?", True),
            ("Are you open to relocation?", False),
            ("What is your notice period?", False),
            ("", False),
        ],
    )
    def test_is_human_only_question(self, text, expected):
        runner = ApplicationRunner.__new__(ApplicationRunner)
        assert runner._is_human_only_question(text) is expected


# ── 9. Answer API staleness (question-id mismatch) ───────────────────────────


class TestAnswerQuestionStaleGuard:
    def test_answer_for_non_active_question_is_409(self, db, client):
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db)
        assert ok

        active = PendingQuestion(
            run_token=token,
            question_text="Are you open to relocation?",
            question_fingerprint="are you open to relocation",
            question_type="TEXT",
            employer="Acme",
            job_title="Data Analyst",
            status="WAITING",
        )
        db.add(active)
        db.commit()
        db.refresh(active)
        coord.set_waiting(token, active.id, db=db)

        # A second WAITING row for the same run that is no longer active.
        stale = PendingQuestion(
            run_token=token,
            question_text="Notice period?",
            question_fingerprint="notice period",
            question_type="TEXT",
            employer="Acme",
            job_title="Data Analyst",
            status="WAITING",
        )
        db.add(stale)
        db.commit()
        db.refresh(stale)

        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={"pending_question_id": stale.id, "run_token": token, "answer": "30 days"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "PENDING_QUESTION_STALE"

        # The active question still answers normally.
        resp = client.post(
            "/api/autonomous-cycle/answer-question",
            json={"pending_question_id": active.id, "run_token": token, "answer": "Yes"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ANSWERED"


# ── 10. Post-Apply detection: single round-trip JS walk ──────────────────────


class _WalkElement:
    def __init__(self, text: str, visible: bool = True):
        self._text = text
        self._visible = visible

    async def is_visible(self) -> bool:
        return self._visible

    async def inner_text(self) -> str:
        return self._text


class _WalkPage:
    def __init__(self, js_result=None, js_error: bool = False, star_elements=None):
        self._js_result = js_result
        self._js_error = js_error
        self._star_elements = star_elements or []
        self.evaluate_calls = 0
        self.star_queries = 0

    async def query_selector_all(self, sel: str):
        if sel == "*":
            self.star_queries += 1
            return self._star_elements
        return []

    async def evaluate(self, script):
        self.evaluate_calls += 1
        if self._js_error:
            raise RuntimeError("evaluate unavailable")
        return self._js_result


class TestAppliedStateJsWalk:
    @pytest.mark.asyncio
    async def test_js_hit_returns_evidence_without_legacy_walk(self):
        page = _WalkPage(js_result='Applied to "Acme"')
        found, text = await NaukriAdapter().detect_applied_state(page)
        assert found is True
        assert text == 'Applied to "Acme"'
        assert page.evaluate_calls == 1
        assert page.star_queries == 0, "the browser walk must replace the per-element scan"

    @pytest.mark.asyncio
    async def test_js_miss_returns_false_without_legacy_walk(self):
        page = _WalkPage(js_result="")
        found, text = await NaukriAdapter().detect_applied_state(page)
        assert (found, text) == (False, "")
        assert page.evaluate_calls == 1
        assert page.star_queries == 0

    @pytest.mark.asyncio
    async def test_js_failure_falls_back_to_legacy_walk(self):
        page = _WalkPage(js_error=True, star_elements=[_WalkElement("Applied")])
        found, text = await NaukriAdapter().detect_applied_state(page)
        assert found is True
        assert text == "Applied"
        assert page.star_queries == 1

    @pytest.mark.asyncio
    async def test_mocked_non_string_result_falls_back_to_legacy_walk(self):
        page = _WalkPage(js_result=MagicMock(), star_elements=[])
        found, text = await NaukriAdapter().detect_applied_state(page)
        assert (found, text) == (False, "")
        assert page.star_queries == 1

    @pytest.mark.asyncio
    async def test_bounded_window_skips_page_walk_entirely(self):
        page = _WalkPage(js_result='Applied"')
        found, _ = await NaukriAdapter().detect_applied_state(
            page, scan_whole_page=False
        )
        assert found is False
        assert page.evaluate_calls == 0
        assert page.star_queries == 0
