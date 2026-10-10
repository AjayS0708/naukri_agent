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
