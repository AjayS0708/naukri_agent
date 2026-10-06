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
from backend.schemas.application import ApplicationStartResult
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
    post_apply_timeout_seconds = 8
    application_type_settle_seconds = 0.5
    _header_apply_selector = "#job_header button#apply-button"
    _fallback_apply_selector = "button#apply-button"

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
        """Detect boundaries where agent needs to stop safely per PRD.

        Uses visible rendered text (inner_text) rather than raw HTML to avoid
        false positives from JSON script blobs such as Naukri's
        ``"showCaptcha":false`` Redux state flag.
        """
        # Wait briefly for JS-rendered content to settle before inspecting
        # visible text.  Uses a short bounded wait on a known Naukri element;
        # if it never appears we proceed with whatever is visible.
        try:
            await page.wait_for_selector("body", timeout=3000)
        except Exception:
            pass

        # Visible text only — ignores raw HTML / embedded JSON script blobs.
        visible_text = await page.inner_text("body")
        visible_lower = visible_text.lower()
        url_lower = page.url.lower()

        # Security verification indicators (must be visible to the user)
        security_indicators = [
            "verify you are human",
            "security challenge",
            "security verification",
            "suspicious activity",
            "human verification",
            "we need to verify",
            "please verify",
            "are you a robot",
        ]

        for indicator in security_indicators:
            if indicator in visible_lower:
                raise Exception(f"Security Verification Required: {indicator}")

        # CAPTCHA widget presence: check for visible CAPTCHA text or known
        # widget labels.  Bare "captcha" is intentionally excluded to avoid
        # matching Naukri's "showCaptcha":false JSON flag in script tags;
        # inner_text() already strips script content, but this makes the
        # intent explicit.
        captcha_visible_indicators = [
            "recaptcha",
            "hcaptcha",
            "i'm not a robot",
            "i am not a robot",
        ]
        for indicator in captcha_visible_indicators:
            if indicator in visible_lower:
                raise Exception(f"Security Verification Required: {indicator}")

        # Login required indicators
        if "login" in url_lower or "sign in" in visible_lower:
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
            if indicator in visible_lower:
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

            description_selectors = [
                '[class*="dang-inner-html"]',
                'section[class*="job-desc-container"]',
            ]
            desc_element = None
            for selector in description_selectors:
                candidate = await page.query_selector(selector)
                if candidate and await candidate.is_visible():
                    desc_element = candidate
                    break

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

    async def fetch_job_details(self, url: str) -> Dict[str, Any]:
        """Fetch description and deterministic IT metadata from a job page."""
        if not self.browser:
            return {}
        page = None
        try:
            page = await self.browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            await self._check_security(page)
            result: Dict[str, Any] = {"description": ""}

            # Extract description
            desc = await page.query_selector('[class*="dang-inner-html"], section[class*="job-desc-container"]')
            if desc and await desc.is_visible():
                result["description"] = (await desc.inner_text()).strip()

            # Try to extract JSON-LD metadata first
            try:
                json_ld_scripts = await page.query_selector_all('script[type="application/ld+json"]')
                for script in json_ld_scripts:
                    script_content = await script.inner_text()
                    if script_content:
                        import json
                        try:
                            data = json.loads(script_content)
                            if isinstance(data, dict):
                                # Extract industry from JSON-LD
                                if "industry" in data and data["industry"]:
                                    result["industry"] = data["industry"]
                                # Extract occupationalCategory as role_category
                                if "occupationalCategory" in data and data["occupationalCategory"]:
                                    result["role_category"] = data["occupationalCategory"]
                                # Handle @graph format
                                if "@graph" in data:
                                    for item in data["@graph"]:
                                        if isinstance(item, dict):
                                            if "industry" in item and item["industry"]:
                                                result["industry"] = item["industry"]
                                            if "occupationalCategory" in item and item["occupationalCategory"]:
                                                result["role_category"] = item["occupationalCategory"]
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                logger.debug(f"JSON-LD extraction failed: {e}")

            # Fallback: Extract from "Other Details" section using selector-based approach
            # Look for the "Other Details" section which typically contains industry, department, role
            try:
                # Try various selectors for the other details section
                other_details_selectors = [
                    '[class*="other-details"]',
                    '[class*="otherDetails"]',
                    'section[class*="details"]',
                    '.job-details',
                    '[class*="jd-other-details"]',
                ]

                for selector in other_details_selectors:
                    other_details = await page.query_selector(selector)
                    if other_details and await other_details.is_visible():
                        details_text = await other_details.inner_text()
                        lines = details_text.splitlines()

                        # Look for key-value pairs
                        for i, line in enumerate(lines):
                            line_lower = line.strip().lower()
                            if i + 1 < len(lines):
                                value = lines[i + 1].strip()

                                # Skip employment type lines
                                if "employment type" in line_lower or "employment type:" in value.lower():
                                    continue

                                if "industry" in line_lower and "industry type" not in line_lower and value and not result.get("industry"):
                                    result["industry"] = value
                                elif "industry type" in line_lower and value and not result.get("industry"):
                                    result["industry"] = value
                                elif "department" in line_lower and value and not result.get("department"):
                                    result["department"] = value
                                elif "role" in line_lower and "role category" not in line_lower and value and not result.get("role_category"):
                                    result["role_category"] = value
                                elif "role category" in line_lower and value and not result.get("role_category"):
                                    result["role_category"] = value
                        break
            except Exception as e:
                logger.debug(f"Other details extraction failed: {e}")

            # Final fallback: Body text scanning
            if not result.get("industry") or not result.get("department") or not result.get("role_category"):
                body_text = (await page.inner_text("body")).splitlines()
                labels = {
                    "industry": ("industry type", "industry"),
                    "department": ("department",),
                    "role_category": ("role category", "role"),
                }
                for key, candidates in labels.items():
                    if not result.get(key):
                        for index, line in enumerate(body_text):
                            if line.strip().lower().rstrip(":") in candidates and index + 1 < len(body_text):
                                value = body_text[index + 1].strip()
                                if value:
                                    result[key] = value
                                    break

            return result
        except Exception as e:
            logger.warning(f"Failed to fetch job details for {url}: {e}")
            return {}
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
        url = f"https://www.naukri.com/{normalized_search}-jobs-in-{normalized_location}?experience=0"
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
            # Build search URL using path-based format
            url = self._build_naukri_search_url(search_term, locations)
            logger.info(f"Navigating directly to search URL: {url}")

            # Navigate directly to search results page
            # The persistent browser context should maintain authentication
            try:
                await page.goto(url, wait_until="load", timeout=60000)
            except Exception as e:
                logger.warning(f"Initial navigation with 'load' failed: {e}, retrying with 'domcontentloaded'")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Wait briefly for content to render
            await asyncio.sleep(3)

            # Check for security/auth issues immediately after navigation
            await self._check_security(page)

            # Wait for job cards to appear with timeout
            # This distinguishes between empty results vs navigation failure
            try:
                await page.wait_for_selector('.srp-jobtuple-wrapper', timeout=10000)
                logger.debug("Job card selector found on search results page")
            except Exception:
                # If selector doesn't appear, check if this is empty results or navigation failure
                page_content = await page.content()
                page_lower = page_content.lower()

                # Check for "no jobs found" indicators - this is valid empty results
                if "no jobs found" in page_lower or "0 jobs" in page_lower or "we couldn't find" in page_lower:
                    logger.info("Search returned no results (valid empty results)")
                # Check for login required
                elif "login" in page_lower and "sign in" in page_lower:
                    logger.error("Authentication required on search page")
                    raise Exception("Naukri login required")
                # Otherwise likely navigation failure
                else:
                    logger.warning(f"Job card selector not found, page may not have loaded correctly. URL: {page.url}")
                    # Continue anyway - let the caller handle empty results

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
                "employment_type": employment_type,
                # Industry metadata is populated from the job page during enrichment.
                "industry": None,
                "department": None,
                "role_category": None,
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

        Phase 10: Evidence-driven detection using visible rendered text,
        stable selectors, and exact text matching. No hashed classes.
        """
        try:
            result = await self._observe_application_type(page)
            if result != "AMBIGUOUS":
                return result

            # Naukri may render the application surface shortly after the job
            # page becomes available. Keep this bounded and do not reload.
            await asyncio.sleep(self.application_type_settle_seconds)
            return await self._observe_application_type(page)
        except Exception as e:
            logger.warning(f"Error detecting application type: {e}")
            return "AMBIGUOUS"

    async def _observe_application_type(self, page: Page) -> str:
        """Classify one visible page state without waiting or navigation."""
        content_lower = (await page.inner_text("body")).lower()
        external_indicators = [
            "apply on company site",
            "apply on company website",
            "external application",
            "redirecting to",
            "you will be redirected",
            "apply externally",
        ]
        if any(indicator in content_lower for indicator in external_indicators):
            return "EXTERNAL"

        apply_button, _ = await self._find_scoped_apply_button(page)
        if apply_button is not None:
            return "NAUKRI_NATIVE"

        return "AMBIGUOUS"

    async def _find_scoped_apply_button(self, page: Page):
        """Find the Naukri Apply control without permitting duplicate-ID ambiguity.

        Naukri may render an identically named sticky-header control. The job
        header is authoritative. A visible global match is used only when no
        header match exists at all, and only the first visible fallback is
        returned.
        """
        header_matches = await page.query_selector_all(self._header_apply_selector)
        if header_matches:
            for button in header_matches:
                if await button.is_visible():
                    logger.info("Using Apply button from #job_header")
                    return button, "job_header"
            logger.warning("Apply button exists in #job_header but is not visible")
            return None, "job_header_not_visible"

        fallback_matches = await page.query_selector_all(self._fallback_apply_selector)
        for button in fallback_matches:
            if await button.is_visible():
                logger.warning(
                    "Using fallback Apply button outside #job_header; header button is absent"
                )
                return button, "fallback"

        logger.info("No visible Apply button found in #job_header or fallback search")
        return None, "none"

    async def start_application(self, page: Page) -> ApplicationStartResult:
        """
        Start the application process by clicking the apply button.
        A click alone is not evidence that an application form opened.

        Phase 10: After the Apply click, wait for explicit post-click evidence:
        - Applied: visible #already-applied, .already-applied, exact "Applied" text,
                   or banner matching 'Applied to "<title>"'
        - Form opened: visible application container
        - Neither within timeout: NEEDS_ATTENTION
        """
        try:
            button, source = await self._find_scoped_apply_button(page)
            if button is None:
                logger.warning("No scoped visible Apply button found; needs attention")
                return ApplicationStartResult.NEEDS_ATTENTION

            logger.info(f"Clicking Apply button selected from {source}")
            await button.click()
            await self._check_security(page)

            # Phase 10: Bounded wait for explicit post-click evidence
            deadline = (
                asyncio.get_running_loop().time()
                + self.post_apply_timeout_seconds
            )
            while asyncio.get_running_loop().time() < deadline:
                # Check for explicit Applied state (visible evidence only)
                applied, evidence = await self.detect_applied_state(page)
                if applied:
                    logger.info(f"Applied state detected with evidence: {evidence}")
                    return ApplicationStartResult.APPLIED

                # Check for visible application container
                if await self._has_visible_application_container(page):
                    logger.info("Application container detected after click")
                    return ApplicationStartResult.FORM_OPENED

                await asyncio.sleep(0.25)

            # Bounded wait expired without explicit evidence
            logger.warning(
                f"No explicit post-click evidence after {self.post_apply_timeout_seconds}s"
            )
            return ApplicationStartResult.NEEDS_ATTENTION
        except Exception as e:
            logger.error(f"Error starting application: {e}")
            raise e

    async def detect_application_questions(self, page: Page) -> List[Dict[str, Any]]:
        """
        Detect application questions on the visible application container.

        Phase 10: Scope to visible editable application container only.
        Require each field to be: visible, enabled, non-zero box, not readonly,
        and not a header/search input.

        Returns a list of question dictionaries with 'question' and 'type' keys.
        """
        questions = []
        try:
            # Get the visible application container (dialog, drawer, modal, or form)
            container = await self._get_visible_application_container(page)
            if container is None:
                logger.info("No visible application container found for question detection")
                return []

            # Search for input/textarea/select fields within the container
            for selector in ['input', 'textarea', 'select']:
                for element in await container.query_selector_all(selector):
                    # Phase 10: Strict visibility and editability requirements
                    if not await element.is_visible():
                        continue
                    if not await element.is_enabled():
                        continue

                    # Reject readonly fields
                    if await element.get_attribute("readonly") is not None:
                        continue

                    # Reject disabled fields
                    if await element.get_attribute("disabled") is not None:
                        continue

                    # Reject zero-sized elements
                    box = await element.bounding_box()
                    if not box or box["width"] <= 0 or box["height"] <= 0:
                        continue

                    # Reject hidden type inputs
                    field_type = await element.get_attribute("type")
                    if field_type and field_type.lower() in ["hidden", "submit", "button"]:
                        continue

                    # Reject header/search inputs by name/id patterns
                    name_attr = await element.get_attribute("name")
                    id_attr = await element.get_attribute("id")
                    if name_attr and any(x in name_attr.lower() for x in ["search", "header", "filter"]):
                        continue
                    if id_attr and any(x in id_attr.lower() for x in ["search", "header", "filter"]):
                        continue

                    # Get label/placeholder for the question
                    label = await element.get_attribute("placeholder")
                    if not label:
                        # Try to find associated label element
                        label_for = await element.get_attribute("id")
                        if label_for:
                            label_element = await page.query_selector(f'label[for="{label_for}"]')
                            if label_element:
                                label = await label_element.inner_text()

                    if label:
                        questions.append({
                            "question": label.strip(),
                            "type": selector,
                            "required": await element.get_attribute("required") is not None
                        })

            logger.info(f"Detected {len(questions)} questions in visible application container")
            return questions
        except Exception as e:
            logger.warning(f"Error detecting questions: {e}")
            return []

    async def detect_applied_state(self, page: Page) -> tuple[bool, str]:
        """Return explicit post-Apply evidence without inferring from navigation."""
        try:
            # The header is authoritative when it renders an applied state.
            for selector in [
                "#job_header #already-applied",
                "#job_header .already-applied",
                "#job_header *",
            ]:
                for element in await page.query_selector_all(selector):
                    if await element.is_visible():
                        text = (await element.inner_text()).strip()
                        if (
                            selector != "#job_header *"
                            or text == "Applied"
                            or text.startswith('Applied to "')
                        ):
                            logger.info("Applied state detected in #job_header")
                            return True, text

            # Form banners may be rendered outside the header after a click.
            for selector in ["#already-applied", ".already-applied"]:
                for element in await page.query_selector_all(selector):
                    if await element.is_visible():
                        return True, (await element.inner_text()).strip()
            for element in await page.query_selector_all("*"):
                if not await element.is_visible():
                    continue
                text = (await element.inner_text()).strip()
                if text == "Applied" or text.startswith('Applied to "'):
                    return True, text
            return False, ""
        except Exception:
            return False, ""

    async def _get_visible_application_container(self, page: Page):
        for selector in ['[role="dialog"]', ".apply-drawer", ".apply-modal", "form"]:
            for element in await page.query_selector_all(selector):
                if await element.is_visible():
                    return element
        return None

    async def _has_visible_application_container(self, page: Page) -> bool:
        return await self._get_visible_application_container(page) is not None

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
                if element and await element.is_visible() and await element.is_enabled():
                    box = await element.bounding_box()
                    if not box or box["width"] <= 0 or box["height"] <= 0:
                        continue
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
                    if input_element and await input_element.is_visible() and await input_element.is_enabled():
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
