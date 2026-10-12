"""E5-R4.3: optional offline DOM validation of the apply-flow detection logic.

Runs the real ``NaukriAdapter`` read-only methods against real Chromium DOM
semantics using ``page.set_content()`` only:

- the saved historical Naukri job-page snapshot (``data/job_page_snapshot.html``,
  a gitignored local artifact - skipped when absent), and
- a controlled synthetic page carrying applied/form/external-CTA structures.

Offline guarantees: headless Chromium, no persistent profile, no login, and
``context.route("**/*")`` aborts every request so no network egress occurs.
No live Naukri URL is loaded and no Apply control is clicked: the popup-observer
probe clicks a neutral local button that opens ``about:blank``.

Prerequisite (optional): ``playwright`` importable and a Chromium browser
installed (``playwright install chromium``). When either is unavailable these
tests skip with a clear reason, so the normal backend suite does not depend on
Chromium.
"""
import asyncio
import logging
from pathlib import Path

import pytest
import pytest_asyncio

pytest.importorskip("playwright", reason="E5-R4.3 offline DOM tests need playwright")

from backend.services.naukri.adapter import NaukriAdapter  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = REPO_ROOT / "data" / "job_page_snapshot.html"

SYNTHETIC_HTML = """<!doctype html>
<html><body>
  <div id="job_header">
    <span class="already-applied">Applied to "Synthetic Role"</span>
    <form><input placeholder="Why do you want this role?" type="text"></form>
    <a href="https://example.com/apply?id=1">Apply on company site</a>
    <a href="https://www.naukri.com/jobs">More jobs</a>
  </div>
  <footer>
    <a href="https://www.facebook.com/naukri">Naukri on Facebook</a>
  </footer>
  <button id="neutral-opener">Open note</button>
  <script>
    document.getElementById('neutral-opener').addEventListener('click', function () {
      window.open('about:blank', '_blank');
    });
  </script>
</body></html>
"""

# E5-R5.4: a native Naukri Apply button is visible while unrelated
# job-description prose contains an external-apply phrase. The visible native
# control must win; the prose must not reclassify the page as EXTERNAL.
NATIVE_WITH_PROSE_HTML = """<!doctype html>
<html><body>
  <div id="job_header">
    <button id="apply-button">Apply</button>
  </div>
  <section class="job-description">
    <p>
      In this role you may be redirecting to an external application portal
      for onboarding, and we handle external application paperwork on your
      behalf.
    </p>
  </section>
</body></html>
"""

# E5-R14: Conversational form with radio buttons
CONVERSATIONAL_RADIO_HTML = """<!doctype html>
<html><body>
  <div class="chatbot_Drawer" id="application_drawer">
    <div class="question">Do you have experience in Data Cleaning and EDA?</div>
    <div class="options">
      <label><input type="radio" name="exp" value="yes" id="radio_yes">Yes</label>
      <label><input type="radio" name="exp" value="no" id="radio_no">No</label>
    </div>
    <div class="send sendMsg">Save</div>
  </div>
</body></html>
"""

# E5-R14: Conversational form with dropdown
CONVERSATIONAL_DROPDOWN_HTML = """<!doctype html>
<html><body>
  <div class="chatbot_Drawer" id="application_drawer">
    <div class="question">What is your highest education?</div>
    <select name="education">
      <option value="bachelor">Bachelor's Degree</option>
      <option value="master">Master's Degree</option>
      <option value="phd">PhD</option>
    </select>
    <div class="send sendMsg">Save</div>
  </div>
</body></html>
"""


async def _abort_all_requests(route):
    await route.abort()


@pytest_asyncio.fixture
async def offline_browser(tmp_path):
    """Headless Chromium context with all network requests aborted."""
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:  # browser binaries missing / blocked
            await playwright.stop()
            pytest.skip(f"Chromium unavailable for E5-R4.3 offline tests: {exc}")
        context = await browser.new_context()
        await context.route("**/*", _abort_all_requests)
        adapter = NaukriAdapter()
        adapter.evidence_dir = str(tmp_path)
        yield context, adapter
        await browser.close()
    finally:
        await playwright.stop()


def _require_snapshot():
    if not SNAPSHOT_PATH.exists():
        pytest.skip(
            "Saved Naukri snapshot data/job_page_snapshot.html is a local "
            "gitignored artifact and is not present"
        )


async def _open_snapshot(context):
    page = await context.new_page()
    await page.set_content(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return page


class TestSnapshotRealPage:
    """Saved real Naukri job page (pre-click, 2026-10-02 capture)."""

    @pytest.mark.asyncio
    async def test_classifies_native_without_external_false_positive(
        self, offline_browser, caplog
    ):
        _require_snapshot()
        caplog.set_level(logging.INFO)
        context, adapter = offline_browser
        page = await _open_snapshot(context)

        assert await adapter._observe_application_type(page) == "NAUKRI_NATIVE"
        assert not any(
            "External apply indicator matched" in message for message in caplog.messages
        ), caplog.messages

    @pytest.mark.asyncio
    async def test_header_apply_button_beats_duplicate_id(self, offline_browser):
        _require_snapshot()
        context, adapter = offline_browser
        page = await _open_snapshot(context)

        duplicate_ids = await page.query_selector_all("button#apply-button")
        assert len(duplicate_ids) == 2, "snapshot must retain the duplicate-ID ambiguity"

        button, source = await adapter._find_scoped_apply_button(page)
        assert button is not None
        assert source == "job_header"

    @pytest.mark.asyncio
    async def test_reports_no_applied_evidence_and_no_container(self, offline_browser):
        _require_snapshot()
        context, adapter = offline_browser
        page = await _open_snapshot(context)

        assert await adapter.detect_applied_state(page, scan_whole_page=False) == (
            False,
            "",
        )
        assert await adapter.detect_applied_state(page, scan_whole_page=True) == (
            False,
            "",
        )
        assert await adapter._has_visible_application_container(page) is False

    @pytest.mark.asyncio
    async def test_external_url_not_grounded_on_page_chrome_links(
        self, offline_browser, caplog
    ):
        _require_snapshot()
        caplog.set_level(logging.INFO)
        context, adapter = offline_browser
        page = await _open_snapshot(context)

        all_links = await page.query_selector_all('a[href^="http"]')
        hrefs = [await link.get_attribute("href") for link in all_links]
        assert sum(1 for href in hrefs if href and "facebook.com" in href) >= 1
        assert sum(1 for href in hrefs if href and "naukri.com" in href) >= 50

        assert await adapter.get_external_redirect_url(page) is None
        assert any(
            "falls back" in message for message in caplog.messages
        ), caplog.messages

    @pytest.mark.asyncio
    async def test_normal_job_page_passes_security_gate(self, offline_browser):
        _require_snapshot()
        context, adapter = offline_browser
        page = await _open_snapshot(context)

        await adapter._check_security(page)


class TestSyntheticControlledPage:
    """Local controlled structures: applied badge, form, external CTA, popup."""

    @pytest.mark.asyncio
    async def test_external_classification_and_cta_grounding(
        self, offline_browser, caplog
    ):
        caplog.set_level(logging.INFO)
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(SYNTHETIC_HTML)

        assert await adapter._observe_application_type(page) == "EXTERNAL"
        assert any(
            "External apply indicator matched" in message
            and "'apply on company site'" in message
            for message in caplog.messages
        ), caplog.messages

        assert await adapter.get_external_redirect_url(page) == (
            "https://example.com/apply?id=1"
        )
        assert any(
            "External apply CTA link evidence" in message
            for message in caplog.messages
        ), caplog.messages

    @pytest.mark.asyncio
    async def test_native_button_beats_unrelated_prose_external_phrase(
        self, offline_browser, caplog
    ):
        # E5-R5.4 offline regression: a native Apply button is visible while
        # unrelated job-description prose contains an external-apply phrase.
        # The page must classify NAUKRI_NATIVE, not EXTERNAL.
        caplog.set_level(logging.INFO)
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(NATIVE_WITH_PROSE_HTML)

        assert await adapter._observe_application_type(page) == "NAUKRI_NATIVE"
        assert not any(
            "External apply indicator matched" in message
            for message in caplog.messages
        ), caplog.messages

    @pytest.mark.asyncio
    async def test_applied_state_and_visible_form_container(self, offline_browser):
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(SYNTHETIC_HTML)

        applied, evidence = await adapter.detect_applied_state(
            page, scan_whole_page=False
        )
        assert applied is True
        assert 'Applied to "Synthetic Role"' in evidence
        assert await adapter._has_visible_application_container(page) is True

    @pytest.mark.asyncio
    async def test_evidence_screenshot_written_under_configured_dir(
        self, offline_browser, tmp_path
    ):
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(SYNTHETIC_HTML)

        path = await adapter._capture_evidence_screenshot(page, "e5r43_test")
        assert path is not None
        assert str(path).startswith(str(tmp_path))
        assert Path(path).exists()
        assert Path(path).stat().st_size > 0

    @pytest.mark.asyncio
    async def test_conversational_radio_selection(self, offline_browser):
        """E5-R14: Test radio button selection in conversational form."""
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(CONVERSATIONAL_RADIO_HTML)

        # Get the container and test selection logic directly
        container = await adapter._get_visible_application_container(page)
        assert container is not None

        # Find radio buttons
        radios = await container.query_selector_all('input[type="radio"]')
        assert len(radios) == 2

        # Click the "Yes" radio via its label
        radio_yes = await container.query_selector("#radio_yes")
        label_yes = await container.query_selector('label[for="radio_yes"]')
        
        if label_yes and await label_yes.is_visible():
            await label_yes.click()
        else:
            await radio_yes.check()
        
        # Verify the radio was checked
        is_checked = await radio_yes.is_checked()
        assert is_checked is True

    @pytest.mark.asyncio
    async def test_conversational_dropdown_selection(self, offline_browser):
        """E5-R14: Test dropdown selection in conversational form."""
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(CONVERSATIONAL_DROPDOWN_HTML)

        # Get the container
        container = await adapter._get_visible_application_container(page)
        assert container is not None

        # Find dropdown
        select = await container.query_selector("select[name='education']")
        assert select is not None

        # Select "Bachelor's Degree"
        await select.select_option(value="bachelor")

        # Verify the dropdown was selected
        value = await select.input_value()
        assert value == "bachelor"

    @pytest.mark.asyncio
    async def test_popup_observer_records_presence_and_absence(
        self, offline_browser, caplog
    ):
        caplog.set_level(logging.INFO)
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(SYNTHETIC_HTML)

        task = asyncio.create_task(
            context.wait_for_event("page", timeout=5000)
        )
        await page.click("#neutral-opener")
        await adapter._record_new_tab(page, task)
        assert any(
            message.startswith("new_tab_detected=yes") for message in caplog.messages
        ), caplog.messages

        task_absent = asyncio.create_task(
            context.wait_for_event("page", timeout=700)
        )
        await adapter._record_new_tab(page, task_absent)
        assert any(
            message.startswith("new_tab_detected=no") for message in caplog.messages
        ), caplog.messages


# E5-R16: authentication state is separate from application mode.
LOGGED_OUT_JOB_HTML = """
<!doctype html><html><head><title>Job</title></head><body>
  <div class="nI-gNb-lg-rg__login">
    <a href="https://login.naukri.com/nLogin/Login.php">Login</a>
    <a href="https://login.naukri.com/nRegistration/Register.php">Register</a>
  </div>
  <div id="job_header">
    <button id="apply-button" style="display:none">Apply</button>
  </div>
  <p>We are hiring. Apply on company site for faster hiring.</p>
</body></html>
"""

LOGGED_IN_JOB_HTML = """
<!doctype html><html><head><title>Job</title></head><body>
  <div class="account">
    <a href="https://www.naukri.com/mn-jobs">My Jobs</a>
    <a href="https://www.naukri.com/job-seekers/profile/view">My Profile</a>
  </div>
  <div id="job_header">
    <button id="apply-button">Apply</button>
  </div>
  <p>We are hiring.</p>
</body></html>
"""


class TestLoginStateSeparation:
    """E5-R16: a logged-out session is detected and never classifies a job."""

    @pytest.mark.asyncio
    async def test_logged_out_page_reports_logged_out_state(self, offline_browser):
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(LOGGED_OUT_JOB_HTML)

        state = await adapter.detect_login_state(page)
        assert state["authenticated"] is False
        assert state["evidence"].startswith("logged_out_control:")

    @pytest.mark.asyncio
    async def test_logged_out_page_is_ambiguous_never_external(
        self, offline_browser, caplog
    ):
        """A logged-out page with external-looking prose must not go EXTERNAL."""
        caplog.set_level(logging.INFO)
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(LOGGED_OUT_JOB_HTML)

        assert await adapter._observe_application_type(page) == "AMBIGUOUS"
        assert not any(
            "External apply indicator matched" in message for message in caplog.messages
        ), caplog.messages

    @pytest.mark.asyncio
    async def test_logged_out_page_fails_the_security_gate(self, offline_browser):
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(LOGGED_OUT_JOB_HTML)

        with pytest.raises(Exception, match="Naukri login required"):
            await adapter._check_security(page)

    @pytest.mark.asyncio
    async def test_logged_in_page_is_authenticated_and_native(self, offline_browser):
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(LOGGED_IN_JOB_HTML)

        state = await adapter.detect_login_state(page)
        assert state["authenticated"] is True
        assert state["evidence"].startswith("logged_in_control:")

        assert await adapter._observe_application_type(page) == "NAUKRI_NATIVE"
        await adapter._check_security(page)

    @pytest.mark.asyncio
    async def test_third_party_profile_links_never_read_as_signed_in(
        self, offline_browser
    ):
        """E5-R16 regression: ambitionbox /profiles/ links are not evidence.

        The Naukri homepage links to third-party interview-question pages whose
        URLs contain "/profile"; treating them as account controls reported a
        signed-in session while the profile was logged out.
        """
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(
            LOGGED_OUT_JOB_HTML
            + """
            <a href="https://www.ambitionbox.com/profiles/software-engineer/interview-questions?utm_source=naukri">Software Engineer</a>
            <a href="https://www.ambitionbox.com/profiles/business-analyst/interview-questions">Business Analyst</a>
            """
        )

        state = await adapter.detect_login_state(page)
        assert state["authenticated"] is False
        assert state["evidence"].startswith("logged_out_control:")

    @pytest.mark.asyncio
    async def test_external_links_alone_leave_login_state_unknown(
        self, offline_browser
    ):
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(
            """
            <p>Careers</p>
            <a href="https://www.ambitionbox.com/profiles/software-engineer/interview-questions">Software Engineer</a>
            """
        )

        state = await adapter.detect_login_state(page)
        assert state["authenticated"] is None


HISTORY_LIST_HTML = """
<!doctype html><html><body>
<div class="appHistWrapper">
  <div class="jdTuplesContainer" style="max-height: 600px">
    <div class="ot__jdTupleContainer jdTupleContainer select">
      <div class="lWhCont full-width">
        <div class="grayBoldHd jdTitle truncate" title="Immediate openings For asp.net Developer">Immediate openings For asp.net Developer</div>
        <div class="subheading"><span title="Creative Solutions" class="company truncate fleft">Creative Solutions</span></div>
      </div>
      <div class="jdFooter">
        <section class="apply-status green-text"><span class="title">Application sent today</span></section>
        <div class="lastActivityDate">Recruiter last active 2w ago</div>
        <a href="/ai-interview-questions/question-bank?jobId=200926010034&amp;skipRole=true">Mock</a>
      </div>
    </div>
    <div class="ot__jdTupleContainer jdTupleContainer">
      <div class="lWhCont full-width">
        <div class="grayBoldHd jdTitle truncate" title="Trainee Web Developer">Trainee Web Developer</div>
        <div class="subheading"><span title="WebMD" class="company truncate fleft">WebMD</span></div>
      </div>
      <div class="jdFooter">
        <section class="apply-status"><span class="title">Application sent 12 Oct 2026</span></section>
        <div class="lastActivityDate">Recruiter last active 7d ago</div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""


class TestApplicationHistoryCards:
    """E5-R16: read-only extraction of the My Naukri application history."""

    @pytest.mark.asyncio
    async def test_reads_rendered_history_cards_without_clicking(self, offline_browser):
        context, adapter = offline_browser
        page = await context.new_page()
        await page.set_content(HISTORY_LIST_HTML)

        cards = await page.evaluate(adapter._HISTORY_CARDS_JS)

        assert len(cards) == 2
        assert cards[0]["title"] == "Immediate openings For asp.net Developer"
        assert cards[0]["company"] == "Creative Solutions"
        assert cards[0]["status_text"] == "Application sent today"
        assert cards[0]["external_job_id"] == "200926010034"
        assert cards[0]["url"] is None
        assert cards[1]["title"] == "Trainee Web Developer"
        assert cards[1]["external_job_id"] is None

    @pytest.mark.asyncio
    async def test_history_url_points_at_application_status_page(self):
        assert NaukriAdapter.applied_jobs_history_url == (
            "https://www.naukri.com/myapply/historypage"
        )


class TestParseHistoryDate:
    """E5-R16: Naukri renders relative dates, so parsing must handle both."""

    def test_parses_relative_status_wording(self) -> None:
        parse = NaukriAdapter()._parse_history_date
        now = datetime.now(UTC)

        today = parse("Application sent today")
        assert today is not None and abs((now - today).total_seconds()) < 120

        yesterday = parse("Application sent yesterday")
        assert yesterday is not None and (now - yesterday).days in (0, 1)

        one_week = parse("Application sent 1 week ago")
        assert one_week is not None and 6 <= (now - one_week).days <= 8

        two_weeks = parse("Resume viewed 2 weeks ago")
        assert two_weeks is not None and 13 <= (now - two_weeks).days <= 15

        three_months = parse("Application sent 3 months ago")
        assert three_months is not None and 88 <= (now - three_months).days <= 92

    def test_parses_absolute_status_wording(self) -> None:
        parse = NaukriAdapter()._parse_history_date
        assert parse("Application sent 12 Oct 2026") == datetime(
            2026, 10, 12, tzinfo=UTC
        )

    def test_never_fabricates_from_activity_or_empty_text(self) -> None:
        parse = NaukriAdapter()._parse_history_date
        assert parse("") is None
        assert parse(None) is None
        assert parse("Recruiter last active 2w ago") is None
        assert parse("Application sent") is None


from datetime import UTC, datetime
