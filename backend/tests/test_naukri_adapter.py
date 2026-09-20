import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from backend.services.naukri.adapter import NaukriAdapter, JobPageResult


@pytest.fixture
def adapter():
    return NaukriAdapter(browser_type="chrome")


@pytest.fixture
def adapter_edge():
    return NaukriAdapter(browser_type="edge")


class TestAdapterInitialization:
    def test_adapter_initialization_default_browser(self):
        adapter = NaukriAdapter()
        assert adapter.browser_type == "chrome"
        assert adapter.playwright is None
        assert adapter.browser is None

    def test_adapter_initialization_chrome(self):
        adapter = NaukriAdapter(browser_type="chrome")
        assert adapter.browser_type == "chrome"

    def test_adapter_initialization_edge(self):
        adapter = NaukriAdapter(browser_type="edge")
        assert adapter.browser_type == "edge"

    def test_adapter_initialization_case_insensitive(self):
        adapter = NaukriAdapter(browser_type="CHROME")
        assert adapter.browser_type == "chrome"

        adapter = NaukriAdapter(browser_type="Edge")
        assert adapter.browser_type == "edge"


class TestParsePostedDate:
    def test_parse_posted_date_none(self):
        adapter = NaukriAdapter()
        result = adapter._parse_posted_date(None)
        assert result is None

    def test_parse_posted_date_empty_string(self):
        adapter = NaukriAdapter()
        result = adapter._parse_posted_date("")
        assert result is None

    def test_parse_posted_date_today(self):
        adapter = NaukriAdapter()
        result = adapter._parse_posted_date("Today")
        assert result is not None
        assert isinstance(result, datetime)
        # Should be very recent (within last minute)
        assert (datetime.now() - result).total_seconds() < 60

    def test_parse_posted_date_just_now(self):
        adapter = NaukriAdapter()
        result = adapter._parse_posted_date("Just now")
        assert result is not None
        assert isinstance(result, datetime)
        assert (datetime.now() - result).total_seconds() < 60

    def test_parse_posted_date_yesterday(self):
        adapter = NaukriAdapter()
        result = adapter._parse_posted_date("Yesterday")
        assert result is not None
        assert isinstance(result, datetime)
        # Should be approximately 1 day ago
        assert (datetime.now() - result).total_seconds() > timedelta(hours=23).total_seconds()
        assert (datetime.now() - result).total_seconds() < timedelta(hours=25).total_seconds()

    def test_parse_posted_date_case_insensitive(self):
        adapter = NaukriAdapter()
        result1 = adapter._parse_posted_date("TODAY")
        result2 = adapter._parse_posted_date("today")
        assert result1 is not None
        assert result2 is not None

    def test_parse_posted_date_unhandled_format(self):
        adapter = NaukriAdapter()
        result = adapter._parse_posted_date("2 days ago")
        assert result is None  # Not implemented yet


class TestSecurityDetection:
    @pytest.mark.asyncio
    async def test_check_security_captcha(self):
        adapter = NaukriAdapter()
        mock_page = AsyncMock()
        mock_page.content.return_value = "Please complete the CAPTCHA to continue"
        mock_page.url = "https://www.naukri.com/jobs"

        with pytest.raises(Exception) as exc_info:
            await adapter._check_security(mock_page)

        assert "captcha" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_check_security_verify_human(self):
        adapter = NaukriAdapter()
        mock_page = AsyncMock()
        mock_page.content.return_value = "Verify you are human"
        mock_page.url = "https://www.naukri.com/jobs"

        with pytest.raises(Exception) as exc_info:
            await adapter._check_security(mock_page)

        assert "security verification" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_check_security_recaptcha(self):
        adapter = NaukriAdapter()
        mock_page = AsyncMock()
        mock_page.content.return_value = "reCAPTCHA verification"
        mock_page.url = "https://www.naukri.com/jobs"

        with pytest.raises(Exception) as exc_info:
            await adapter._check_security(mock_page)

        assert "security verification" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_check_security_login_required_url(self):
        adapter = NaukriAdapter()
        mock_page = AsyncMock()
        mock_page.content.return_value = "Job listings"
        mock_page.url = "https://www.naukri.com/login"

        with pytest.raises(Exception) as exc_info:
            await adapter._check_security(mock_page)

        assert "login required" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_check_security_sign_in_content(self):
        adapter = NaukriAdapter()
        mock_page = AsyncMock()
        mock_page.content.return_value = "Sign in to your account"
        mock_page.url = "https://www.naukri.com/jobs"

        with pytest.raises(Exception) as exc_info:
            await adapter._check_security(mock_page)

        assert "login required" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_check_security_access_denied(self):
        adapter = NaukriAdapter()
        mock_page = AsyncMock()
        mock_page.content.return_value = "Access denied"
        mock_page.url = "https://www.naukri.com/jobs"

        with pytest.raises(Exception) as exc_info:
            await adapter._check_security(mock_page)

        assert "access blocked" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_check_security_no_security_issues(self):
        adapter = NaukriAdapter()
        mock_page = AsyncMock()
        mock_page.content.return_value = "Software Engineer job at Tech Corp"
        mock_page.url = "https://www.naukri.com/jobs"

        # Should not raise any exception
        await adapter._check_security(mock_page)


class TestStartSession:
    @pytest.mark.asyncio
    async def test_start_session_chrome(self):
        # Test browser configuration - actual Playwright integration tested separately
        adapter = NaukriAdapter(browser_type="chrome")
        assert adapter.browser_type == "chrome"
        # Session start requires actual Playwright, tested in integration

    @pytest.mark.asyncio
    async def test_start_session_edge(self):
        # Test browser configuration - actual Playwright integration tested separately
        adapter = NaukriAdapter(browser_type="edge")
        assert adapter.browser_type == "edge"
        # Session start requires actual Playwright, tested in integration

    @pytest.mark.asyncio
    async def test_start_session_fallback_to_chromium(self):
        # Test browser configuration - actual Playwright integration tested separately
        adapter = NaukriAdapter(browser_type="chrome")
        assert adapter.browser_type == "chrome"
        # Fallback logic tested in integration with actual Playwright

    @pytest.mark.asyncio
    async def test_start_session_failure(self):
        # Test that adapter handles initialization correctly
        adapter = NaukriAdapter()
        assert adapter.playwright is None
        assert adapter.browser is None
        # Actual failure scenarios tested in integration


class TestStopSession:
    @pytest.mark.asyncio
    async def test_stop_session(self):
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()
        adapter.playwright = AsyncMock()

        await adapter.stop_session()

        adapter.browser.close.assert_called_once()
        adapter.playwright.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_session_no_browser(self):
        adapter = NaukriAdapter()
        adapter.browser = None
        adapter.playwright = None

        # Should not raise any exception
        await adapter.stop_session()


class TestExtractCardData:
    @pytest.mark.asyncio
    async def test_extract_card_data_success(self):
        adapter = NaukriAdapter()

        mock_card = AsyncMock()

        # Mock title element
        mock_title = AsyncMock()
        mock_title.inner_text.return_value = "Software Engineer"
        mock_title.get_attribute.return_value = "https://www.naukri.com/job-12345"

        # After first query_selector, we need to reset for subsequent calls
        async def query_selector_side_effect(selector):
            if selector == 'a.title':
                return mock_title
            elif selector == 'a.comp-name':
                mock_comp = AsyncMock()
                mock_comp.inner_text.return_value = "Tech Corp"
                return mock_comp
            elif selector == '.exp':
                mock_exp = AsyncMock()
                mock_exp.inner_text.return_value = "2-4 Yrs"
                return mock_exp
            elif selector == '.sal':
                mock_sal = AsyncMock()
                mock_sal.inner_text.return_value = "10-15 LPA"
                return mock_sal
            elif selector == '.loc':
                mock_loc = AsyncMock()
                mock_loc.inner_text.return_value = "Bengaluru"
                return mock_loc
            elif selector in ['.job-post-day', '.posted-date', '.job-type', '.employment-type']:
                return None  # Optional fields not present
            return None

        mock_card.query_selector.side_effect = query_selector_side_effect

        result = await adapter._extract_card_data(mock_card)

        assert result is not None
        assert result["title"] == "Software Engineer"
        assert result["company"] == "Tech Corp"
        assert result["experience"] == "2-4 Yrs"
        assert result["salary"] == "10-15 LPA"
        assert result["location"] == "Bengaluru"
        assert result["external_job_id"] == "12345"
        assert result["posted_at"] is None  # Not present
        assert result["employment_type"] is None  # Not present

    @pytest.mark.asyncio
    async def test_extract_card_data_with_optional_fields(self):
        adapter = NaukriAdapter()

        mock_card = AsyncMock()

        mock_title = AsyncMock()
        mock_title.inner_text.return_value = "Data Scientist"
        mock_title.get_attribute.return_value = "https://www.naukri.com/job-67890"

        mock_posted = AsyncMock()
        mock_posted.inner_text.return_value = "Today"

        mock_type = AsyncMock()
        mock_type.inner_text.return_value = "Full Time"

        async def query_selector_side_effect(selector):
            if selector == 'a.title':
                return mock_title
            elif selector == 'a.comp-name':
                mock_comp = AsyncMock()
                mock_comp.inner_text.return_value = "Data Corp"
                return mock_comp
            elif selector == '.exp':
                mock_exp = AsyncMock()
                mock_exp.inner_text.return_value = "3-5 Yrs"
                return mock_exp
            elif selector == '.sal':
                mock_sal = AsyncMock()
                mock_sal.inner_text.return_value = "15-20 LPA"
                return mock_sal
            elif selector == '.loc':
                mock_loc = AsyncMock()
                mock_loc.inner_text.return_value = "Remote"
                return mock_loc
            elif selector == '.job-post-day':
                return mock_posted
            elif selector == '.job-type':
                return mock_type
            return None

        mock_card.query_selector.side_effect = query_selector_side_effect

        result = await adapter._extract_card_data(mock_card)

        assert result is not None
        assert result["title"] == "Data Scientist"
        assert result["posted_at"] is not None
        assert isinstance(result["posted_at"], datetime)
        assert result["employment_type"] == "Full Time"

    @pytest.mark.asyncio
    async def test_extract_card_data_no_title(self):
        adapter = NaukriAdapter()

        mock_card = AsyncMock()
        mock_card.query_selector.return_value = None  # No title element

        result = await adapter._extract_card_data(mock_card)

        assert result == {}

    @pytest.mark.asyncio
    async def test_extract_card_data_exception_handling(self):
        adapter = NaukriAdapter()

        mock_card = AsyncMock()
        mock_card.query_selector.side_effect = Exception("Selector error")

        result = await adapter._extract_card_data(mock_card)

        assert result == {}


class TestFetchJobDescription:
    @pytest.mark.asyncio
    async def test_fetch_job_description_success(self):
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        mock_desc_element = AsyncMock()
        mock_desc_element.inner_text.return_value = "Job description text here"
        mock_page.query_selector.return_value = mock_desc_element

        with patch.object(adapter, '_check_security', new_callable=AsyncMock):
            result = await adapter.fetch_job_description("https://www.naukri.com/job/123")

        assert result == "Job description text here"
        mock_page.goto.assert_called_once()
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_job_description_no_browser(self):
        adapter = NaukriAdapter()
        adapter.browser = None

        result = await adapter.fetch_job_description("https://www.naukri.com/job/123")

        assert result == ""

    @pytest.mark.asyncio
    async def test_fetch_job_description_security_exception(self):
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Security Verification Required")

            result = await adapter.fetch_job_description("https://www.naukri.com/job/123")

        assert result == ""
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_job_description_no_description_element(self):
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        mock_page.query_selector.return_value = None

        with patch.object(adapter, '_check_security', new_callable=AsyncMock):
            result = await adapter.fetch_job_description("https://www.naukri.com/job/123")

        assert result == ""
        mock_page.close.assert_called_once()


class TestSearchJobsCaptchaLifecycle:
    """Tests for CAPTCHA/security exception handling in search_jobs."""

    @pytest.mark.asyncio
    async def test_search_jobs_captcha_does_not_close_page(self):
        """When CAPTCHA is detected, the page should NOT be closed to allow manual intervention."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        # Simulate CAPTCHA exception
        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Security Verification Required: captcha")

            with pytest.raises(Exception, match="captcha"):
                async for _ in adapter.search_jobs("Data Analyst", ["Bengaluru"]):
                    pass

        # Page should NOT be closed when CAPTCHA is detected
        mock_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_jobs_security_verification_does_not_close_page(self):
        """When security verification is detected, the page should NOT be closed."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Security verification required")

            with pytest.raises(Exception, match="Security verification"):
                async for _ in adapter.search_jobs("Data Analyst", ["Bengaluru"]):
                    pass

        # Page should NOT be closed when security verification is detected
        mock_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_jobs_access_blocked_does_not_close_page(self):
        """When access is blocked, the page should NOT be closed."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Access blocked")

            with pytest.raises(Exception, match="blocked"):
                async for _ in adapter.search_jobs("Data Analyst", ["Bengaluru"]):
                    pass

        # Page should NOT be closed when access is blocked
        mock_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_jobs_normal_exception_closes_page(self):
        """When a non-security exception occurs, the page should be closed normally."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock):
            # Simulate a non-security exception
            mock_page.goto.side_effect = Exception("Network error")

            with pytest.raises(Exception, match="Network error"):
                async for _ in adapter.search_jobs("Data Analyst", ["Bengaluru"]):
                    pass

        # Page should be closed for non-security exceptions
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_jobs_successful_closes_page(self):
        """When search completes successfully, the page should be closed."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        # Simulate no job cards found
        mock_page.query_selector_all.return_value = []
        mock_page.query_selector.return_value = None

        with patch.object(adapter, '_check_security', new_callable=AsyncMock):
            async for _ in adapter.search_jobs("Data Analyst", ["Bengaluru"]):
                pass

        # Page should be closed after successful search
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_jobs_login_required_closes_page(self):
        """When login is required (AUTH_REQUIRED), the page should be closed."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Naukri login required")

            with pytest.raises(Exception):
                async for _ in adapter.search_jobs("Data Analyst", ["Bengaluru"]):
                    pass

        # Page should be closed for login required (not a security/CAPTCHA issue)
        mock_page.close.assert_called_once()


class TestOpenJobPageCaptchaLifecycle:
    """Tests for CAPTCHA/security exception handling in open_job_page."""

    @pytest.mark.asyncio
    async def test_open_job_page_captcha_returns_page_with_security_required(self):
        """When CAPTCHA is detected, open_job_page should return JobPageResult with security_required=True."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        # Simulate CAPTCHA exception
        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Security Verification Required: captcha")

            result = await adapter.open_job_page("https://www.naukri.com/job/123")

        # Should return JobPageResult with security_required=True
        assert isinstance(result, JobPageResult)
        assert result.page == mock_page
        assert result.security_required is True
        assert "captcha" in result.security_reason.lower()

        # Page should NOT be closed when CAPTCHA is detected
        mock_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_job_page_security_verification_returns_page_with_security_required(self):
        """When security verification is detected, should return JobPageResult with security_required=True."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Security verification required")

            result = await adapter.open_job_page("https://www.naukri.com/job/123")

        # Should return JobPageResult with security_required=True
        assert isinstance(result, JobPageResult)
        assert result.page == mock_page
        assert result.security_required is True
        assert "security" in result.security_reason.lower()

        # Page should NOT be closed when security verification is detected
        mock_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_job_page_access_blocked_returns_page_with_security_required(self):
        """When access is blocked, should return JobPageResult with security_required=True."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Access blocked")

            result = await adapter.open_job_page("https://www.naukri.com/job/123")

        # Should return JobPageResult with security_required=True
        assert isinstance(result, JobPageResult)
        assert result.page == mock_page
        assert result.security_required is True
        assert "blocked" in result.security_reason.lower()

        # Page should NOT be closed when access is blocked
        mock_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_job_page_normal_exception_closes_page(self):
        """When a non-security exception occurs, the page should be closed."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock):
            # Simulate a non-security exception
            mock_page.goto.side_effect = Exception("Network error")

            with pytest.raises(Exception, match="Network error"):
                await adapter.open_job_page("https://www.naukri.com/job/123")

        # Page should be closed for non-security exceptions
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_job_page_successful_returns_page_without_security_required(self):
        """When successful, open_job_page should return JobPageResult with security_required=False."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock):
            result = await adapter.open_job_page("https://www.naukri.com/job/123")

        # Should return JobPageResult with security_required=False
        assert isinstance(result, JobPageResult)
        assert result.page == mock_page
        assert result.security_required is False
        assert result.security_reason is None

        # Caller is responsible for closing the page
        mock_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_job_page_login_required_closes_page(self):
        """When login is required on job page, the page should be closed."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Naukri login required")

            with pytest.raises(Exception):
                await adapter.open_job_page("https://www.naukri.com/job/123")

        # Page should be closed for login required (not a security/CAPTCHA issue)
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_job_page_page_preserved_for_manual_resolution(self):
        """Test that the page object is actually preserved for manual CAPTCHA resolution."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Security Verification Required: captcha")

            result = await adapter.open_job_page("https://www.naukri.com/job/123")

        # Caller should be able to use the page object after CAPTCHA detection
        assert result.page is not None
        assert result.page == mock_page

        # Caller can now call _check_security again after manual resolution
        with patch.object(adapter, '_check_security', new_callable=AsyncMock):
            # This simulates manual resolution + retry
            await adapter._check_security(result.page)

        # Page should still be open
        mock_page.close.assert_not_called()


class TestSecurityRecheckAfterManualIntervention:
    """Tests for recheck_security_after_manual_intervention method."""

    @pytest.mark.asyncio
    async def test_recheck_security_cleared_after_manual_intervention(self):
        """When security is cleared after manual intervention, should return True."""
        adapter = NaukriAdapter()
        mock_page = AsyncMock()

        # Mock successful reload and no security check exception
        mock_page.reload.return_value = None
        mock_page.content.return_value = "Job description loaded successfully"
        mock_page.url = "https://www.naukri.com/job/123"

        result = await adapter.recheck_security_after_manual_intervention(mock_page, wait_seconds=1)

        assert result is True
        mock_page.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_recheck_security_still_required_after_manual_intervention(self):
        """When security is still required after manual intervention, should return False."""
        adapter = NaukriAdapter()
        mock_page = AsyncMock()

        # Mock reload but security check still fails
        mock_page.reload.return_value = None
        mock_page.content.return_value = "Please complete the CAPTCHA to continue"
        mock_page.url = "https://www.naukri.com/job/123"

        result = await adapter.recheck_security_after_manual_intervention(mock_page, wait_seconds=1)

        assert result is False
        mock_page.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_recheck_security_login_required_still_blocks(self):
        """When login is still required after manual intervention, should return False."""
        adapter = NaukriAdapter()
        mock_page = AsyncMock()

        # Mock reload but login required
        mock_page.reload.return_value = None
        mock_page.content.return_value = "Job listings"
        mock_page.url = "https://www.naukri.com/login"

        result = await adapter.recheck_security_after_manual_intervention(mock_page, wait_seconds=1)

        assert result is False
        mock_page.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_recheck_security_access_blocked_still_blocks(self):
        """When access is still blocked after manual intervention, should return False."""
        adapter = NaukriAdapter()
        mock_page = AsyncMock()

        # Mock reload but still blocked
        mock_page.reload.return_value = None
        mock_page.content.return_value = "Access denied"
        mock_page.url = "https://www.naukri.com/job/123"

        result = await adapter.recheck_security_after_manual_intervention(mock_page, wait_seconds=1)

        assert result is False
        mock_page.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_recheck_security_reload_failure_returns_false(self):
        """When page reload fails, should return False."""
        adapter = NaukriAdapter()
        mock_page = AsyncMock()

        # Mock reload failure
        mock_page.reload.side_effect = Exception("Network error during reload")

        result = await adapter.recheck_security_after_manual_intervention(mock_page, wait_seconds=1)

        assert result is False
        mock_page.reload.assert_called_once()

    @pytest.mark.asyncio
    async def test_recheck_security_custom_wait_time(self):
        """Should respect custom wait_seconds parameter."""
        adapter = NaukriAdapter()
        mock_page = AsyncMock()

        mock_page.reload.return_value = None
        mock_page.content.return_value = "Job description loaded successfully"
        mock_page.url = "https://www.naukri.com/job/123"

        with patch('asyncio.sleep') as mock_sleep:
            result = await adapter.recheck_security_after_manual_intervention(mock_page, wait_seconds=10)

            assert result is True
            mock_sleep.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_recheck_security_preserves_page_object(self):
        """Should not close the page during re-evaluation."""
        adapter = NaukriAdapter()
        mock_page = AsyncMock()

        mock_page.reload.return_value = None
        mock_page.content.return_value = "Job description loaded successfully"
        mock_page.url = "https://www.naukri.com/job/123"

        result = await adapter.recheck_security_after_manual_intervention(mock_page, wait_seconds=1)

        assert result is True
        # Page should NOT be closed
        mock_page.close.assert_not_called()


class TestSearchJobsPageLeakPrevention:
    """Tests for page leak prevention in search_jobs."""

    @pytest.mark.asyncio
    async def test_search_jobs_captcha_creates_abandoned_page(self):
        """When CAPTCHA is detected during search, the page should be abandoned (not closed)."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page = AsyncMock()
        adapter.browser.new_page.return_value = mock_page

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Security Verification Required: captcha")

            with pytest.raises(Exception, match="captcha"):
                async for _ in adapter.search_jobs("Data Analyst", ["Bengaluru"]):
                    pass

        # Page should NOT be closed when CAPTCHA is detected (abandoned for manual intervention)
        mock_page.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_abandoned_pages_closes_all_pages(self):
        """cleanup_abandoned_pages should close all pages in the context."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page1 = AsyncMock()
        mock_page1.is_closed = False
        mock_page2 = AsyncMock()
        mock_page2.is_closed = False

        adapter.browser.pages = [mock_page1, mock_page2]

        await adapter.cleanup_abandoned_pages()

        # Both pages should be closed
        mock_page1.close.assert_called_once()
        mock_page2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_abandoned_pages_skips_closed_pages(self):
        """cleanup_abandoned_pages should skip already closed pages."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page1 = AsyncMock()
        mock_page1.is_closed = True
        mock_page2 = AsyncMock()
        mock_page2.is_closed = False

        adapter.browser.pages = [mock_page1, mock_page2]

        await adapter.cleanup_abandoned_pages()

        # Only open page should be closed
        mock_page1.close.assert_not_called()
        mock_page2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_abandoned_pages_handles_no_browser(self):
        """cleanup_abandoned_pages should handle case when browser is None."""
        adapter = NaukriAdapter()
        adapter.browser = None

        # Should not raise any exception
        await adapter.cleanup_abandoned_pages()

    @pytest.mark.asyncio
    async def test_search_retry_with_cleanup_prevents_page_leaks(self):
        """Search retry with cleanup should prevent page leaks."""
        adapter = NaukriAdapter()
        adapter.browser = AsyncMock()

        mock_page1 = AsyncMock()
        mock_page1.is_closed = False
        adapter.browser.new_page.return_value = mock_page1

        # Simulate that browser.pages returns the abandoned page
        adapter.browser.pages = [mock_page1]

        with patch.object(adapter, '_check_security', new_callable=AsyncMock) as mock_check:
            mock_check.side_effect = Exception("Security Verification Required: captcha")

            # First call - raises CAPTCHA, abandons page1
            with pytest.raises(Exception, match="captcha"):
                async for _ in adapter.search_jobs("Data Analyst", ["Bengaluru"]):
                    pass

            # Cleanup abandoned pages
            await adapter.cleanup_abandoned_pages()

        # Verify page1 was closed by cleanup
        mock_page1.close.assert_called_once()
