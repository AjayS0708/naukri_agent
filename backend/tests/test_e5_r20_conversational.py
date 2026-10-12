"""E5-R20: conversational apply — no nudge loops, bounded prompts, and
history-authoritative reconciliation for ambiguous submissions.

Covers (all offline — no browser, no network, no live DB writes):
1. prompt classification: nudges ("update your profile") are identified and
   never answered; questions stay answerable;
2. the runner answers each distinct prompt at most twice and stops with a
   specific NEEDS_ATTENTION reason instead of repeating 12 times;
3. nudges get no answer, at most one supported dismissal click;
4. occluded/timeout submit clicks never raise — they report AMBIGUOUS;
5. every unconfirmed ending is reconciled against Naukri application
   history BEFORE NEEDS_ATTENTION is recorded; history confirmation wins;
6. reconciliation leaves earlier attempt rows untouched, is idempotent,
   reports ambiguous matches without merging, and never downgrades APPLIED;
7. the dashboard distinguishes confirmed applications from attempts that
   remain unresolved (added in test_dashboard.py).
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.application import Application
from backend.models.job import Job
from backend.models.profile import Profile
from backend.schemas.application import ApplicationStatus
from backend.services.agent_state import AgentStateManager
from backend.services.applications import ApplicationRunner
from backend.services.applications.service import ApplicationService
from backend.services.naukri.adapter import NaukriAdapter


# ── Offline fakes for adapter-level tests ─────────────────────────────────────

class FakeElement:
    def __init__(
        self,
        *,
        text: str = "",
        visible: bool = True,
        enabled: bool = True,
        hits: bool = True,
        click_error: Exception | None = None,
        evaluate_error: Exception | None = None,
        attributes: dict | None = None,
    ):
        self.text = text
        self.visible = visible
        self.enabled = enabled
        self.hits = hits
        self.click_error = click_error
        self.evaluate_error = evaluate_error
        self.attributes = attributes or {}
        self.clicks = 0
        self.filled = None

    async def is_visible(self) -> bool:
        return self.visible

    async def is_enabled(self) -> bool:
        return self.enabled

    async def inner_text(self) -> str:
        return self.text

    async def get_attribute(self, name: str):
        return self.attributes.get(name)

    async def evaluate(self, script: str):
        if self.evaluate_error is not None:
            raise self.evaluate_error
        return self.hits

    async def click(self, timeout: int | None = None) -> None:
        self.clicks += 1
        if self.click_error is not None:
            raise self.click_error

    async def fill(self, value: str) -> None:
        self.filled = value

    async def bounding_box(self):
        return {"x": 0, "y": 0, "width": 10, "height": 10} if self.visible else None


class FakeContainer:
    def __init__(
        self,
        *,
        cls: str = "chatbot_Drawer",
        bot_text: str | None = None,
        radios: list | None = None,
        labels: dict | None = None,
        composer: FakeElement | None = None,
        buttons: list | None = None,
    ):
        self.cls = cls
        self.bot_text = bot_text
        self.radios = radios or []
        self.labels = labels or {}
        self.composer = composer
        self.buttons = buttons or []

    async def get_attribute(self, name: str):
        return self.cls if name == "class" else None

    async def query_selector(self, sel: str):
        if sel in (".botMsg span", ".botMsg"):
            if not self.bot_text:
                return None
            return FakeElement(text=self.bot_text)
        if sel == '[contenteditable="true"]':
            return self.composer
        if sel.startswith('label[for="') and sel.endswith('"]'):
            return self.labels.get(sel[len('label[for="'):-2])
        return None

    async def query_selector_all(self, sel: str):
        if sel == 'input[type="radio"]':
            return self.radios
        if sel in (
            "button, [role='button'], a, div, span",
            "button, [role='button'], input[type='submit'], a",
        ):
            return self.buttons
        return []


class FakePage:
    def __init__(self, selector_map: dict | None = None):
        self.selector_map = selector_map or {}
        self.url = "https://www.naukri.com/job-listings-some-job"

    async def query_selector(self, sel: str):
        return self.selector_map.get(sel)

    async def query_selector_all(self, sel: str):
        return self.selector_map.get(sel) or []

    async def wait_for_selector(self, *args, **kwargs) -> None:
        return None

    async def inner_text(self, sel: str) -> str:
        return ""

    async def wait_for_timeout(self, ms: int) -> None:
        return None


NUDGE_TEXT = "We request you to take a couple of minutes to update your profile."
NOTICE_QUESTION = "What is your notice period?"
LOCATION_QUESTION = "What is your location?"


# ── 1. Classification ─────────────────────────────────────────────────────────

class TestClassifyConversationalMessage:
    def test_nudge_text_without_options_is_nudge(self):
        assert (
            NaukriAdapter.classify_conversational_message(NUDGE_TEXT, False, False)
            == "nudge"
        )

    def test_nudge_text_with_composer_is_still_nudge(self):
        # E5-R19: the nudge re-rendered while a composer was present; typing
        # an answer into it only re-triggered the same nudge.
        assert (
            NaukriAdapter.classify_conversational_message(NUDGE_TEXT, False, True)
            == "nudge"
        )

    def test_options_are_always_a_question(self):
        assert (
            NaukriAdapter.classify_conversational_message(
                "Are you open to contract roles?", True, False
            )
            == "question"
        )

    def test_free_text_with_composer_is_question(self):
        assert (
            NaukriAdapter.classify_conversational_message(
                "Mention your notice period", False, True
            )
            == "question"
        )

    def test_question_mark_is_question_even_without_composer(self):
        assert (
            NaukriAdapter.classify_conversational_message(
                "Are you open to contract roles?", False, False
            )
            == "question"
        )

    def test_plain_message_without_composer_is_info(self):
        assert (
            NaukriAdapter.classify_conversational_message(
                "Application received.", False, False
            )
            == "info"
        )

    def test_empty_text_is_info(self):
        assert NaukriAdapter.classify_conversational_message("", False, True) == "info"


class TestDetectConversationalQuestionKind:
    @pytest.mark.asyncio
    async def test_nudge_detection_carries_nudge_kind(self):
        adapter = NaukriAdapter()
        container = FakeContainer(bot_text=NUDGE_TEXT)
        conv = await adapter._detect_conversational_question(container)
        assert conv is not None
        assert conv["kind"] == "nudge"
        assert conv["options"] == []

    @pytest.mark.asyncio
    async def test_nudge_with_composer_stays_nudge(self):
        adapter = NaukriAdapter()
        container = FakeContainer(bot_text=NUDGE_TEXT, composer=FakeElement())
        conv = await adapter._detect_conversational_question(container)
        assert conv["kind"] == "nudge"

    @pytest.mark.asyncio
    async def test_text_question_with_composer_is_question(self):
        adapter = NaukriAdapter()
        container = FakeContainer(bot_text=NOTICE_QUESTION, composer=FakeElement())
        conv = await adapter._detect_conversational_question(container)
        assert conv["kind"] == "question"

    @pytest.mark.asyncio
    async def test_radio_question_is_question_with_options(self):
        adapter = NaukriAdapter()
        radio = FakeElement(attributes={"id": "reloc-1", "value": "Yes"})
        container = FakeContainer(
            bot_text="Are you willing to relocate?",
            radios=[radio],
            labels={"reloc-1": FakeElement(text="Yes")},
        )
        conv = await adapter._detect_conversational_question(container)
        assert conv["kind"] == "question"
        assert conv["options"] == ["Yes"]

    @pytest.mark.asyncio
    async def test_info_message_without_composer_is_info(self):
        adapter = NaukriAdapter()
        container = FakeContainer(bot_text="Application received.")
        conv = await adapter._detect_conversational_question(container)
        assert conv["kind"] == "info"


# ── 2. Hit-tested clicking ────────────────────────────────────────────────────

class TestPointerSafeClick:
    @pytest.mark.asyncio
    async def test_occluded_element_is_skipped_without_click(self):
        adapter = NaukriAdapter()
        el = FakeElement(hits=False)
        assert await adapter._pointer_safe_click(el) == "occluded"
        assert el.clicks == 0

    @pytest.mark.asyncio
    async def test_click_timeout_reports_timeout_without_raising(self):
        adapter = NaukriAdapter()
        el = FakeElement(click_error=RuntimeError("Timeout 30000ms exceeded."))
        assert await adapter._pointer_safe_click(el) == "timeout"
        assert el.clicks == 1

    @pytest.mark.asyncio
    async def test_stale_element_reports_stale(self):
        adapter = NaukriAdapter()
        el = FakeElement(evaluate_error=RuntimeError("Execution context was destroyed"))
        assert await adapter._pointer_safe_click(el) == "stale"
        assert el.clicks == 0

    @pytest.mark.asyncio
    async def test_disabled_element_is_not_clicked(self):
        adapter = NaukriAdapter()
        el = FakeElement(enabled=False)
        assert await adapter._pointer_safe_click(el) == "not_enabled"
        assert el.clicks == 0

    @pytest.mark.asyncio
    async def test_visible_hit_element_is_clicked(self):
        adapter = NaukriAdapter()
        el = FakeElement()
        assert await adapter._pointer_safe_click(el) == "clicked"
        assert el.clicks == 1


# ── 3. Submit outcomes ────────────────────────────────────────────────────────

class TestSubmitApplicationNeverRaises:
    @pytest.mark.asyncio
    async def test_occluded_background_submit_is_skipped_then_next_wins(self):
        # E5-R19: the background button[type="submit"] was covered by the
        # chat drawer and its click timed out, killing the whole attempt.
        adapter = NaukriAdapter()
        occluded = FakeElement(hits=False)
        fallback = FakeElement()
        page = FakePage(
            {'button[type="submit"]': occluded, ".submit-btn": fallback}
        )
        with patch("asyncio.sleep", new_callable=AsyncMock):
            submitted = await adapter.submit_application(page)
        assert submitted is True
        assert adapter.last_submit_outcome == "SUBMITTED"
        assert occluded.clicks == 0
        assert fallback.clicks == 1

    @pytest.mark.asyncio
    async def test_intercepted_click_reports_ambiguous_without_raising(self):
        adapter = NaukriAdapter()
        blocked = FakeElement(click_error=RuntimeError("Timeout 30000ms exceeded."))
        page = FakePage({'button[type="submit"]': blocked})
        with patch("asyncio.sleep", new_callable=AsyncMock):
            submitted = await adapter.submit_application(page)
        assert submitted is False
        assert adapter.last_submit_outcome == "AMBIGUOUS"

    @pytest.mark.asyncio
    async def test_no_submit_control_reports_not_submitted(self):
        adapter = NaukriAdapter()
        page = FakePage()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            submitted = await adapter.submit_application(page)
        assert submitted is False
        assert adapter.last_submit_outcome == "NOT_SUBMITTED"


class TestSubmitConversationalApplication:
    @pytest.mark.asyncio
    async def test_clicks_supported_drawer_control_only(self):
        adapter = NaukriAdapter()
        occluded_apply = FakeElement(text="Apply", hits=False)
        apply_now = FakeElement(text="Apply Now")
        send_control = FakeElement(text="Send")
        container = FakeContainer(buttons=[occluded_apply, apply_now, send_control])
        adapter._get_visible_application_container = AsyncMock(return_value=container)

        outcome = await adapter.submit_conversational_application(FakePage())

        assert outcome == "SUBMITTED"
        assert adapter.last_submit_outcome == "SUBMITTED"
        assert occluded_apply.clicks == 0
        assert apply_now.clicks == 1
        # .sendMsg-style answer controls are never treated as submit.
        assert send_control.clicks == 0

    @pytest.mark.asyncio
    async def test_no_supported_control_reports_not_submitted(self):
        adapter = NaukriAdapter()
        container = FakeContainer(buttons=[FakeElement(text="Maybe later")])
        adapter._get_visible_application_container = AsyncMock(return_value=container)

        outcome = await adapter.submit_conversational_application(FakePage())

        assert outcome == "NOT_SUBMITTED"
        assert adapter.last_submit_outcome == "NOT_SUBMITTED"

    @pytest.mark.asyncio
    async def test_timeout_reports_ambiguous_without_raising(self):
        adapter = NaukriAdapter()
        blocked = FakeElement(
            text="Submit", click_error=RuntimeError("Timeout 30000ms exceeded.")
        )
        container = FakeContainer(buttons=[blocked])
        adapter._get_visible_application_container = AsyncMock(return_value=container)

        outcome = await adapter.submit_conversational_application(FakePage())

        assert outcome == "AMBIGUOUS"
        assert adapter.last_submit_outcome == "AMBIGUOUS"


# ── 4. Nudge dismissal ────────────────────────────────────────────────────────

class TestDismissConversationalNudge:
    @pytest.mark.asyncio
    async def test_visible_supported_dismissal_is_clicked(self):
        adapter = NaukriAdapter()
        dismiss = FakeElement(text=" Not now ")
        container = FakeContainer(buttons=[FakeElement(text="Learn more"), dismiss])
        adapter._get_visible_application_container = AsyncMock(return_value=container)

        assert await adapter.dismiss_conversational_nudge(FakePage()) is True
        assert dismiss.clicks == 1

    @pytest.mark.asyncio
    async def test_unrelated_buttons_are_not_clicked(self):
        adapter = NaukriAdapter()
        unrelated = FakeElement(text="Learn more")
        container = FakeContainer(buttons=[unrelated])
        adapter._get_visible_application_container = AsyncMock(return_value=container)

        assert await adapter.dismiss_conversational_nudge(FakePage()) is False
        assert unrelated.clicks == 0

    @pytest.mark.asyncio
    async def test_disabled_dismissal_is_not_clicked(self):
        adapter = NaukriAdapter()
        disabled = FakeElement(text="Skip", enabled=False)
        container = FakeContainer(buttons=[disabled])
        adapter._get_visible_application_container = AsyncMock(return_value=container)

        assert await adapter.dismiss_conversational_nudge(FakePage()) is False
        assert disabled.clicks == 0

    @pytest.mark.asyncio
    async def test_missing_container_is_not_an_error(self):
        adapter = NaukriAdapter()
        adapter._get_visible_application_container = AsyncMock(return_value=None)
        assert await adapter.dismiss_conversational_nudge(FakePage()) is False


# ── 5. Stale prompt guard ─────────────────────────────────────────────────────

class TestAnswerStalePrompt:
    @pytest.mark.asyncio
    async def test_changed_prompt_is_not_answered(self):
        adapter = NaukriAdapter()
        composer = FakeElement()
        container = FakeContainer(bot_text="A completely different prompt", composer=composer)
        adapter._get_visible_application_container = AsyncMock(return_value=container)

        answered = await adapter.answer_conversational_question(
            FakePage(), "30 days", expected_question=NOTICE_QUESTION
        )

        assert answered is False
        assert composer.filled is None

    @pytest.mark.asyncio
    async def test_matching_prompt_is_answered(self):
        adapter = NaukriAdapter()
        composer = FakeElement()
        container = FakeContainer(bot_text=NOTICE_QUESTION, composer=composer)
        adapter._get_visible_application_container = AsyncMock(return_value=container)
        page = FakePage({".sendMsg": FakeElement(text="Send")})

        answered = await adapter.answer_conversational_question(
            page, "30 days", expected_question=NOTICE_QUESTION
        )

        assert answered is True
        assert composer.filled == "30 days"


# ── 6. Runner loop: bounded, never answers nudges ─────────────────────────────

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(autocommit=False, autoflush=False, bind=engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def conv_runner(db_session):
    runner = ApplicationRunner(db_session, AgentStateManager())

    adapter = MagicMock()
    adapter._normalize_choice = NaukriAdapter._normalize_choice
    adapter.detect_applied_state = AsyncMock(return_value=(False, ""))
    adapter.detect_application_questions = AsyncMock(return_value=[])
    adapter.answer_conversational_question = AsyncMock(return_value=True)
    adapter.dismiss_conversational_nudge = AsyncMock(return_value=False)
    adapter.submit_conversational_application = AsyncMock(return_value="NOT_SUBMITTED")
    adapter.fetch_application_history = AsyncMock(return_value=[])
    runner.adapter = adapter

    service = MagicMock()
    service.update_application = MagicMock()
    service.reconcile_from_history = MagicMock(
        return_value={
            "history_entries": 0,
            "confirmed_local_job_ids": [],
            "reconciled_count": 0,
            "reconciled_application_ids": [],
            "reconciled_job_ids": [],
            "local_applied_without_history_evidence": [],
            "ambiguous": [],
            "unmatched": [],
            "protected_job_ids": [],
        }
    )
    runner.application_service = service
    runner._get_ai_answer = MagicMock(return_value=None)
    return runner


@pytest.fixture
def conv_job():
    return Job(
        id=462,
        platform="naukri",
        external_job_id="121026034917",
        url="https://www.naukri.com/job-listings-recruito-data-analyst-462",
        title="Data Analyst",
        company="Recruito",
    )


@pytest.fixture
def conv_profile():
    return Profile(
        status="CONFIRMED",
        confirmed=True,
        data={
            "notice_period": "30 days",
            "location": "Bengaluru",
            "current_ctc": "6 LPA",
        },
    )


@pytest.fixture
def attempt():
    return SimpleNamespace(id=7)


@pytest.fixture
def no_sleep():
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


def _nudge_question():
    return {
        "question": NUDGE_TEXT,
        "type": "text",
        "options": [],
        "required": True,
        "kind": "nudge",
    }


def _text_question(text):
    return {
        "question": text,
        "type": "text",
        "options": [],
        "required": True,
        "kind": "question",
    }


def _last_update(runner):
    assert runner.application_service.update_application.call_count >= 1
    call = runner.application_service.update_application.call_args
    return call.args[1]


class TestConversationalLoopBounded:
    @pytest.mark.asyncio
    async def test_persistent_nudge_is_never_answered(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        """The E5-R19 failure: the same nudge was answered 12 times."""
        conv_runner.adapter.detect_application_questions.return_value = [
            _nudge_question()
        ]

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        assert outcome == "NEEDS_ATTENTION"
        # Never typed an answer for a prompt with no answer options.
        conv_runner.adapter.answer_conversational_question.assert_not_awaited()
        conv_runner._get_ai_answer.assert_not_called()
        # Observed exactly twice, then stopped — never a 12-step loop.
        assert conv_runner.adapter.detect_application_questions.await_count == 2
        assert conv_runner.adapter.detect_applied_state.await_count == 2
        # At most one supported dismissal attempt.
        assert conv_runner.adapter.dismiss_conversational_nudge.await_count == 1

        update = _last_update(conv_runner)
        assert update.status == ApplicationStatus.NEEDS_ATTENTION
        assert "Persistent conversational nudge with no answer options" in update.skip_reason

    @pytest.mark.asyncio
    async def test_nudge_dismissal_is_attempted_exactly_once(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        conv_runner.adapter.detect_application_questions.return_value = [
            _nudge_question()
        ]
        conv_runner.adapter.dismiss_conversational_nudge.return_value = True

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        assert outcome == "NEEDS_ATTENTION"
        assert conv_runner.adapter.dismiss_conversational_nudge.await_count == 1
        conv_runner.adapter.answer_conversational_question.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_question_is_answered_bounded_times_then_stops(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        question = _text_question(NOTICE_QUESTION)
        conv_runner.adapter.detect_application_questions.return_value = [question]

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        assert outcome == "NEEDS_ATTENTION"
        # Initial answer plus exactly one retry — never 12.
        assert conv_runner.adapter.answer_conversational_question.await_count == 2
        assert conv_runner.adapter.detect_application_questions.await_count == 3
        for call in conv_runner.adapter.answer_conversational_question.call_args_list:
            assert call.kwargs.get("expected_question") == NOTICE_QUESTION
            assert call.args[1] == "30 days"

        update = _last_update(conv_runner)
        assert update.status == ApplicationStatus.NEEDS_ATTENTION
        assert "unchanged after answering" in update.skip_reason

    @pytest.mark.asyncio
    async def test_unanswerable_question_stops_with_specific_reason(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        conv_runner.adapter.detect_application_questions.return_value = [
            _text_question("What is your expected CTC?")
        ]

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        assert outcome == "NEEDS_ATTENTION"
        conv_runner.adapter.answer_conversational_question.assert_not_awaited()
        update = _last_update(conv_runner)
        assert "Could not answer question: What is your expected CTC?" in update.skip_reason

    @pytest.mark.asyncio
    async def test_distinct_questions_each_answered_once(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        q1 = _text_question(NOTICE_QUESTION)
        q2 = _text_question(LOCATION_QUESTION)
        conv_runner.adapter.detect_application_questions.side_effect = [[q1], [q2], []]

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        # Both real questions answered from profile, then a bounded submit
        # attempt, then history reconciliation (empty history -> attention).
        assert outcome == "NEEDS_ATTENTION"
        assert conv_runner.adapter.answer_conversational_question.await_count == 2
        answered = [
            (c.args[1], c.kwargs.get("expected_question"))
            for c in conv_runner.adapter.answer_conversational_question.call_args_list
        ]
        assert answered == [("30 days", NOTICE_QUESTION), ("Bengaluru", LOCATION_QUESTION)]
        conv_runner.adapter.submit_conversational_application.assert_awaited_once()


class TestConversationalEndingsReconcileFirst:
    @pytest.mark.asyncio
    async def test_history_confirmation_wins_over_unconfirmed_submit(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        conv_runner.adapter.submit_conversational_application.return_value = "NOT_SUBMITTED"
        conv_runner.adapter.fetch_application_history.return_value = [
            {"url": conv_job.url, "title": conv_job.title, "company": conv_job.company}
        ]
        conv_runner.application_service.reconcile_from_history.return_value = {
            "history_entries": 1,
            "confirmed_local_job_ids": [],
            "reconciled_count": 1,
            "reconciled_application_ids": [99],
            "reconciled_job_ids": [conv_job.id],
            "local_applied_without_history_evidence": [],
            "ambiguous": [],
            "unmatched": [],
            "protected_job_ids": [],
        }

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        # Naukri history is authoritative: the application is confirmed.
        assert outcome == "APPLIED"
        conv_runner.application_service.reconcile_from_history.assert_called_once()
        update = _last_update(conv_runner)
        # The attempt row stays auditable — never rewritten to APPLIED.
        assert update.status == ApplicationStatus.NEEDS_ATTENTION
        assert "confirmed via Naukri application history" in update.skip_reason

    @pytest.mark.asyncio
    async def test_ambiguous_submit_without_history_confirmation_needs_attention(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        conv_runner.adapter.submit_conversational_application.return_value = "AMBIGUOUS"

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        assert outcome == "NEEDS_ATTENTION"
        # Exactly one submit attempt — no blind retry after a timeout.
        conv_runner.adapter.submit_conversational_application.assert_awaited_once()
        update = _last_update(conv_runner)
        assert "timed out or was intercepted (ambiguous)" in update.skip_reason
        assert "not confirmed in Naukri application history" in update.skip_reason

    @pytest.mark.asyncio
    async def test_submitted_without_confirmation_reconciles_before_attention(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        conv_runner.adapter.submit_conversational_application.return_value = "SUBMITTED"

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        assert outcome == "NEEDS_ATTENTION"
        conv_runner.application_service.reconcile_from_history.assert_called_once()
        update = _last_update(conv_runner)
        assert "without Applied confirmation" in update.skip_reason

    @pytest.mark.asyncio
    async def test_history_fetch_failure_still_records_specific_reason(
        self, conv_runner, conv_job, conv_profile, attempt, no_sleep
    ):
        conv_runner.adapter.submit_conversational_application.return_value = "AMBIGUOUS"
        conv_runner.adapter.fetch_application_history.side_effect = Exception(
            "Browser session not started"
        )

        outcome = await conv_runner._complete_conversational_application(
            MagicMock(), attempt, conv_job, conv_profile
        )

        assert outcome == "NEEDS_ATTENTION"
        conv_runner.application_service.reconcile_from_history.assert_not_called()
        update = _last_update(conv_runner)
        assert "application history unavailable for verification" in update.skip_reason


# ── 7. Reconciliation record integrity for attempt rows ───────────────────────

def _make_job(db, external_job_id: str, *, title="Data Analyst", company="Acme Corp") -> Job:
    job = Job(
        platform="naukri",
        external_job_id=external_job_id,
        url=f"https://www.naukri.com/job-listings-{external_job_id}",
        title=title,
        company=company,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _rows(db, job_id: int) -> list[Application]:
    return list(
        db.execute(select(Application).where(Application.job_id == job_id))
        .scalars()
        .all()
    )


class TestAttemptRowsPreservedByReconciliation:
    def test_reconcile_creates_applied_row_but_leaves_attempt_untouched(self, db):
        job = _make_job(db, "r20-462")
        skip_reason = "Conversational submit click timed out or was intercepted (ambiguous)"
        attempt = Application(
            job_id=job.id,
            status=ApplicationStatus.NEEDS_ATTENTION.value,
            needs_attention=True,
            skip_reason=skip_reason,
            applied_at=None,
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)

        service = ApplicationService(db)
        entry = {
            "url": job.url,
            "title": job.title,
            "company": job.company,
            "external_job_id": job.external_job_id,
        }
        first = service.reconcile_from_history([entry])
        second = service.reconcile_from_history([entry])

        assert job.id in first["reconciled_job_ids"]
        assert second["reconciled_count"] == 0  # idempotent

        rows = _rows(db, job.id)
        assert len(rows) == 2
        applied_rows = [r for r in rows if r.status == ApplicationStatus.APPLIED.value]
        attempt_rows = [r for r in rows if r.status == ApplicationStatus.NEEDS_ATTENTION.value]
        assert len(applied_rows) == 1
        assert len(attempt_rows) == 1

        # #147-style record: the attempt row is never rewritten to APPLIED.
        preserved = attempt_rows[0]
        assert preserved.id == attempt.id
        assert preserved.skip_reason == skip_reason
        assert preserved.applied_at is None
        assert preserved.needs_attention is True

    def test_reconcile_never_downgrades_applied_row(self, db):
        job = _make_job(db, "r20-applied")
        applied_at = datetime(2026, 10, 12, 15, 11, 11, tzinfo=UTC)
        row = Application(
            job_id=job.id,
            status=ApplicationStatus.APPLIED.value,
            applied_at=applied_at,
            confirmation_evidence="naukri_form_submitted",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        service = ApplicationService(db)
        result = service.reconcile_from_history([])  # history no longer lists it

        assert job.id in result["local_applied_without_history_evidence"]
        rows = _rows(db, job.id)
        assert len(rows) == 1
        assert rows[0].status == ApplicationStatus.APPLIED.value
        # SQLite returns naive UTC datetimes; compare on the same footing.
        assert rows[0].applied_at.replace(tzinfo=None) == applied_at.replace(tzinfo=None)
        assert rows[0].confirmation_evidence == "naukri_form_submitted"

    def test_ambiguous_multi_candidate_entry_is_reported_not_merged(self, db):
        _make_job(db, "r20-amb-a", title="Data Analyst", company="Twin Corp")
        _make_job(db, "r20-amb-b", title="Data Analyst", company="Twin Corp")
        service = ApplicationService(db)

        result = service.reconcile_from_history(
            [{"url": None, "title": "Data Analyst", "company": "Twin Corp"}]
        )

        assert result["reconciled_count"] == 0
        assert len(result["ambiguous"]) == 1
        # Neither twin job receives a fabricated APPLIED row.
        for job in (
            db.execute(select(Job).where(Job.external_job_id == "r20-amb-a"))
            .scalars()
            .one(),
            db.execute(select(Job).where(Job.external_job_id == "r20-amb-b"))
            .scalars()
            .one(),
        ):
            assert _rows(db, job.id) == []
