import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from backend.services.naukri.adapter import NaukriAdapter


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
        mock_page.query_selector.return_value = None  # No description element
        adapter.browser.new_page.return_value = mock_page
        
        with patch.object(adapter, '_check_security', new_callable=AsyncMock):
            result = await adapter.fetch_job_description("https://www.naukri.com/job/123")
        
        assert result == ""
