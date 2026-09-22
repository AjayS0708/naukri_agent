import asyncio
import re
import urllib.parse
from datetime import datetime
from typing import AsyncGenerator, Dict, Any, List, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from dataclasses import dataclass
import os

from backend.services.platform_adapter import JobPlatformAdapter
from backend.core.logging import get_logger
from backend.core.config import get_settings

logger = get_logger(__name__)

# User-data directory for Playwright persistent context to maintain active logged-in sessions without needing credentials
# Now configurable via environment variable NAUKRI_AGENT_BROWSER_USER_DATA_DIR
def get_browser_user_data_dir() -> str:
    """Get browser user data directory from settings."""
    settings = get_settings()
    return str(settings.browser_user_data_path)

USER_DATA_DIR = get_browser_user_data_dir()


@dataclass
class JobPageResult:
    """Result of opening a job page with explicit state handling."""
    page: Page
    security_required: bool = False
    security_reason: Optional[str] = None


class NaukriAdapter(JobPlatformAdapter):
    """
    Playwright-based adapter for Naukri job discovery.
    Operates using normal browser interactions without evasion techniques.
    Raises exceptions on CAPTCHA / Security walls designed to halt agents.
    """
    platform_name = "naukri"

    def __init__(self, browser_type: str = "chrome"):
        """
        Initialize adapter with browser selection.

        Args:
            browser_type: "chrome" or "edge". Defaults to "chrome".
        """
        self.playwright = None
        self.browser: BrowserContext = None
        self.browser_type = browser_type.lower()

    async def start_session(self) -> bool:
        try:
            self.playwright = await async_playwright().start()

            # Select browser channel based on configuration
            if self.browser_type == "edge":
                browser_channel = "msedge"
            else:
                browser_channel = "chrome"

            # Use persistent context to reuse existing sessions (assumes manual login beforehand)
            try:
                self.browser = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=USER_DATA_DIR,
                    channel=browser_channel,
                    headless=False,
                )
            except Exception as channel_error:
                logger.warning(f"Failed to launch {browser_channel}, falling back to chromium: {channel_error}")
                # Fallback to default chromium if specific channel not available
                self.browser = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=USER_DATA_DIR,
                    headless=False,
                )
            return True
        except Exception as e:
            logger.error(f"Failed to start Playwright browser: {e}")
            return False

    async def stop_session(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def _check_security(self, page: Page):
        """Detect boundaries where agent needs to stop safely per PRD."""
        content = await page.content()
        content_lower = content.lower()
        url_lower = page.url.lower()

        # Security verification indicators
        security_indicators = [
            "captcha",
            "verify you are human",
            "security challenge",
            "security verification",
            "suspicious activity",
            "human verification",
            "we need to verify",
            "please verify",
            "recaptcha",
            "hcaptcha",
            "are you a robot",
        ]

        for indicator in security_indicators:
            if indicator in content_lower:
                raise Exception(f"Security Verification Required: {indicator}")

        # Login required indicators
        if "login" in url_lower or "sign in" in content_lower:
            raise Exception("Naukri login required")

        # Blocked access indicators
        blocked_indicators = [
            "access denied",
            "blocked",
            "your access has been restricted",
            "account suspended",
            "temporarily blocked",
        ]

        for indicator in blocked_indicators:
            if indicator in content_lower:
                raise Exception(f"Access Blocked: {indicator}")

    async def recheck_security_after_manual_intervention(self, page: Page, wait_seconds: int = 5) -> bool:
        """
        Re-evaluate security status after manual CAPTCHA resolution.

        This method should be called after the user manually resolves a security challenge.
        It reloads the page to ensure fresh content and checks if security is cleared.

        Args:
            page: The page object that had a security challenge
            wait_seconds: Time to wait after reload for page to stabilize

        Returns:
            True if security is cleared (no security indicators), False if still blocked
        """
        try:
            # Reload the page to get fresh content after manual resolution
            await page.reload(wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(wait_seconds)

            # Check if security is cleared
            await self._check_security(page)

            # If we get here, security is cleared
            return True
        except Exception as e:
            error_msg = str(e).lower()
            # Security still required
            if any(indicator in error_msg for indicator in ["captcha", "security", "verify", "access blocked"]):
                logger.warning(f"Security still required after manual intervention: {e}")
                return False
            # Other error
            logger.error(f"Error during security re-evaluation: {e}")
            return False

    async def fetch_job_description(self, url: str) -> str:
        """Fetch the details page explicitly if missing from cards."""
        if not self.browser:
            return ""

        page = None
        try:
            page = await self.browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2) # Natural pause

            await self._check_security(page)

            # typical description selectors, fall back to body
            desc_element = await page.query_selector('.job-desc')
            if not desc_element:
                desc_element = await page.query_selector('.styles_JDC__') # Example obfuscated class Naukri sometimes uses

            if desc_element:
                text = await desc_element.inner_text()
                return text.strip()

            return ""
        except Exception as e:
            logger.warning(f"Failed to fetch description for {url}: {e}")
            return ""
        finally:
            if page:
                await page.close()

    def _build_naukri_search_url(self, search_term: str, locations: List[str]) -> str:
        """
        Build Naukri search URL using path-based format.

        Format: https://www.naukri.com/{SearchTerm}-jobs-in-{Location}

        Normalizes:
        - spaces → hyphens
        - capitalizes each word
        - handles multiple-word search terms and locations

        Args:
            search_term: Job title/keywords (e.g., "Data Analyst")
            locations: List of locations (e.g., ["Bengaluru"])

        Returns:
            Formatted Naukri search URL
        """
        # Normalize search term: capitalize words, replace spaces with hyphens
        normalized_search = "-".join(word.capitalize() for word in search_term.split())

        # Normalize location: use first location, capitalize words, replace spaces with hyphens
        if locations:
            normalized_location = "-".join(word.capitalize() for word in locations[0].split())
        else:
            normalized_location = "india"

        # Build path-based URL
        url = f"https://www.naukri.com/{normalized_search}-jobs-in-{normalized_location}"
        logger.info(f"Built Naukri search URL: {url}")
        return url

    async def search_jobs(self, search_term: str, locations: List[str]) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Navigates Naukri and scrapes job cards.
        Extracts structured info.

        Note: If a security exception is raised, the page is NOT closed to allow
        manual user intervention. The caller is responsible for cleanup after handling
        the security state transition by calling cleanup_abandoned_pages().
        """
        if not self.browser:
            return

        page = await self.browser.new_page()
        security_exception = None

        try:
            # Navigate to Naukri homepage first to establish session context
            logger.info("Navigating to Naukri homepage to establish session context")
            await page.goto("https://www.naukri.com", wait_until="load", timeout=30000)
            await self._check_security(page)

            # Build search URL using path-based format
            url = self._build_naukri_search_url(search_term, locations)
            logger.info(f"Navigating to search URL: {url}")

            await page.goto(url, wait_until="load", timeout=30000)

            # Wait for job cards to appear with timeout
            try:
                await page.wait_for_selector('.srp-jobtuple-wrapper', timeout=10000)
            except Exception:
                # If selector doesn't appear, continue anyway - might be empty results
                logger.debug("Job card selector not found within timeout, continuing anyway")

            await self._check_security(page)

            # Paginate up to MAX_SEARCH_PAGES
            MAX_PAGES = 3

            for page_num in range(1, MAX_PAGES + 1):
                # Use the working primary selector
                job_cards = await page.query_selector_all('.srp-jobtuple-wrapper')
                if not job_cards:
                    # Fallback to older selector for backward compatibility
                    job_cards = await page.query_selector_all('article.jobTuple')

                for card in job_cards:
                    data = await self._extract_card_data(card)
                    if data:
                        data["page_number"] = page_num
                        yield data

                # Next page
                next_btn = await page.query_selector('a.styles_btn-secondary__2BqIV')
                if next_btn:
                    await next_btn.click()
                    await asyncio.sleep(4)
                else:
                    break
        except Exception as e:
            # Store security exceptions to prevent page closure
            error_msg = str(e).lower()
            if "captcha" in error_msg or "security" in error_msg or "verify" in error_msg or "access blocked" in error_msg:
                security_exception = e
                logger.warning(f"Security challenge detected, keeping page open for manual intervention: {e}")
                raise
            else:
                raise
        finally:
            # Only close the page if no security exception was raised
            # This allows manual CAPTCHA resolution on the open page
            if security_exception is None:
                await page.close()

    async def cleanup_abandoned_pages(self):
        """
        Clean up any abandoned pages from security exceptions.
        Call this after manual CAPTCHA resolution to prevent page leaks.
        """
        if self.browser:
            try:
                # Close all pages in the context except the active one
                pages = self.browser.pages
                for page in pages:
                    if not page.is_closed:
                        await page.close()
            except Exception as e:
                logger.warning(f"Error cleaning up abandoned pages: {e}")

    async def _extract_card_data(self, card) -> Dict[str, Any]:
        """Extract job fields from a single job card element."""
        try:
            # typical tags in modern Naukri cards
            title_el = await card.query_selector('a.title')
            if not title_el:
                return {}

            title = await title_el.inner_text()
            url = await title_el.get_attribute('href')

            company_el = await card.query_selector('a.comp-name')
            company = await company_el.inner_text() if company_el else ""

            exp_el = await card.query_selector('.exp')
            experience = await exp_el.inner_text() if exp_el else ""

            sal_el = await card.query_selector('.sal')
            salary = await sal_el.inner_text() if sal_el else ""

            loc_el = await card.query_selector('.loc')
            location = await loc_el.inner_text() if loc_el else ""

            # Try to extract posted date/time
            posted_at = None
            posted_el = await card.query_selector('.job-post-day')
            if not posted_el:
                posted_el = await card.query_selector('.posted-date')
            if posted_el:
                posted_text = await posted_el.inner_text()
                posted_at = self._parse_posted_date(posted_text)

            # Try to extract employment type
            employment_type = None
            type_el = await card.query_selector('.job-type')
            if not type_el:
                type_el = await card.query_selector('.employment-type')
            if type_el:
                employment_type = await type_el.inner_text()
                if employment_type:
                    employment_type = employment_type.strip()

            # Simple Naukri Job ID extraction from URL
            external_job_id = None
            if url:
                 match = re.search(r'-([a-zA-Z0-9]+)\?', url)
                 if not match:
                     match = re.search(r'-([a-zA-Z0-9]+)$', url)
                 if match:
                     external_job_id = match.group(1)

            return {
                "title": title.strip(),
                "url": url,
                "company": company.strip(),
                "experience": experience.strip(),
                "salary": salary.strip(),
                "location": location.strip(),
                "external_job_id": external_job_id,
                "posted_at": posted_at,
                "employment_type": employment_type
            }
        except Exception as e:
            logger.debug(f"Error parsing job card: {e}")
            return {}

    def _parse_posted_date(self, posted_text: str) -> datetime | None:
        """Parse Naukri posted date text into datetime if possible."""
        if not posted_text:
            return None

        posted_text = posted_text.strip().lower()

        # Handle relative time formats like "2 days ago", "1 week ago", etc.
        # This is a basic implementation - can be enhanced later
        try:
            from datetime import timedelta
            if "today" in posted_text or "just now" in posted_text:
                return datetime.now()
            elif "yesterday" in posted_text:
                return datetime.now() - timedelta(days=1)
            # For more complex formats, return None for now
            # This can be enhanced with dateutil or similar in future
        except Exception:
            pass

        return None

    async def open_job_page(self, url: str) -> JobPageResult:
        """
        Open a job page and return a JobPageResult with explicit state.

        Returns:
            JobPageResult: Contains the page object and security state information.

        The caller is responsible for:
        - Checking result.security_required to determine if manual intervention is needed
        - Closing result.page when done (regardless of security state)
        - Calling _check_security(page) again after manual resolution if needed

        Security exceptions are handled explicitly rather than raised, allowing
        the caller to receive the page object for manual CAPTCHA resolution.
        """
        if not self.browser:
            raise Exception("Browser session not started")

        page = await self.browser.new_page()
        security_required = False
        security_reason = None
        non_security_exception = None

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)  # Natural pause
            await self._check_security(page)
            return JobPageResult(page=page, security_required=False)
        except Exception as e:
            error_msg = str(e).lower()
            if "captcha" in error_msg or "security" in error_msg or "verify" in error_msg or "access blocked" in error_msg:
                security_required = True
                security_reason = str(e)
                logger.warning(f"Security challenge on job page, keeping page open for manual intervention: {e}")
                # Return the page with security_required=True instead of raising
                return JobPageResult(page=page, security_required=True, security_reason=security_reason)
            else:
                non_security_exception = e
                raise
        finally:
            # Only close the page on non-security exceptions
            # Security exceptions: page stays open for manual intervention
            # Success: page returned for caller to close
            # Non-security exceptions: page closed for cleanup
            if non_security_exception is not None:
                await page.close()

    async def detect_application_type(self, page: Page) -> str:
        """
        Detect if the job has a Naukri-native application or redirects externally.
        Returns: "NAUKRI_NATIVE" or "EXTERNAL"
        """
        try:
            # Check for external redirect indicators
            content = await page.content()
            content_lower = content.lower()

            # External application indicators
            external_indicators = [
                "apply on company website",
                "external application",
                "redirecting to",
                "you will be redirected",
                "apply externally"
            ]

            for indicator in external_indicators:
                if indicator in content_lower:
                    return "EXTERNAL"

            # Check for Naukri native apply button
            apply_button = await page.query_selector('button[type="submit"]')
            if not apply_button:
                apply_button = await page.query_selector('.apply-btn')
            if not apply_button:
                apply_button = await page.query_selector('a.apply')

            if apply_button:
                return "NAUKRI_NATIVE"

            # Default to external if unclear
            return "EXTERNAL"
        except Exception as e:
            logger.warning(f"Error detecting application type: {e}")
            return "EXTERNAL"

    async def start_application(self, page: Page) -> bool:
        """
        Start the application process by clicking the apply button.
        Returns True if started successfully, False otherwise.
        """
        try:
            # Try various apply button selectors
            apply_selectors = [
                'button[type="submit"]',
                '.apply-btn',
                'a.apply',
                'button.apply-now',
                '.apply-now-btn'
            ]

            for selector in apply_selectors:
                button = await page.query_selector(selector)
                if button:
                    await button.click()
                    await asyncio.sleep(2)
                    await self._check_security(page)
                    return True

            logger.warning("No apply button found")
            return False
        except Exception as e:
            logger.error(f"Error starting application: {e}")
            raise e

    async def detect_application_questions(self, page: Page) -> List[Dict[str, Any]]:
        """
        Detect application questions on the page.
        Returns a list of question dictionaries with 'question' and 'type' keys.
        """
        questions = []
        try:
            # Look for common question selectors
            question_selectors = [
                'input[type="text"]',
                'textarea',
                'select',
                '.question',
                '.form-group label'
            ]

            for selector in question_selectors:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    # Get label or placeholder
                    label = await element.get_attribute('placeholder')
                    if not label:
                        # Try to find associated label
                        label_element = await element.query_selector('label')
                        if label_element:
                            label = await label_element.inner_text()

                    if label:
                        questions.append({
                            'question': label.strip(),
                            'type': 'text'  # Simplified type detection
                        })

            return questions
        except Exception as e:
            logger.warning(f"Error detecting questions: {e}")
            return []

    async def answer_question(self, page: Page, question: str, answer: str) -> bool:
        """
        Answer a specific question on the application form.
        Returns True if answered successfully, False otherwise.
        """
        try:
            # Find the input/textarea by placeholder or label
            input_selectors = [
                f'input[placeholder="{question}"]',
                f'textarea[placeholder="{question}"]',
                f'input[name="{question}"]',
                f'textarea[name="{question}"]'
            ]

            for selector in input_selectors:
                element = await page.query_selector(selector)
                if element:
                    await element.fill(answer)
                    await asyncio.sleep(0.5)
                    return True

            # Try to find by label text
            labels = await page.query_selector_all('label')
            for label in labels:
                label_text = await label.inner_text()
                if question.lower() in label_text.lower():
                    # Find the associated input
                    input_element = await page.query_selector(f'#{await label.get_attribute("for")}')
                    if input_element:
                        await input_element.fill(answer)
                        await asyncio.sleep(0.5)
                        return True

            logger.warning(f"Could not find input for question: {question}")
            return False
        except Exception as e:
            logger.error(f"Error answering question: {e}")
            return False

    async def submit_application(self, page: Page) -> bool:
        """
        Submit the application form.
        Returns True if submitted successfully, False otherwise.
        """
        try:
            # Look for submit button
            submit_selectors = [
                'button[type="submit"]',
                '.submit-btn',
                'input[type="submit"]',
                'button.submit'
            ]

            for selector in submit_selectors:
                button = await page.query_selector(selector)
                if button:
                    await button.click()
                    await asyncio.sleep(3)
                    await self._check_security(page)
                    return True

            logger.warning("No submit button found")
            return False
        except Exception as e:
            logger.error(f"Error submitting application: {e}")
            raise e

    async def confirm_submission(self, page: Page) -> bool:
        """
        Confirm that the application was submitted successfully.
        Returns True if confirmation detected, False otherwise.
        """
        try:
            content = await page.content()
            content_lower = content.lower()

            # Success indicators
            success_indicators = [
                "application submitted",
                "successfully applied",
                "your application has been submitted",
                "thank you for applying",
                "application received"
            ]

            for indicator in success_indicators:
                if indicator in content_lower:
                    return True

            return False
        except Exception as e:
            logger.warning(f"Error confirming submission: {e}")
            return False

    async def get_external_redirect_url(self, page: Page) -> str | None:
        """
        Get the external redirect URL if the application redirects externally.
        Returns the URL or None.
        """
        try:
            # Look for external links
            external_links = await page.query_selector_all('a[href^="http"]')
            for link in external_links:
                href = await link.get_attribute('href')
                if href and 'naukri.com' not in href:
                    return href

            return None
        except Exception as e:
            logger.warning(f"Error getting external URL: {e}")
            return None
