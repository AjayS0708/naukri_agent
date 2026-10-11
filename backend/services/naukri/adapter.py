import asyncio
import re
import urllib.parse
from datetime import UTC, datetime, timedelta
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

# Relative posting-age units that Naukri renders on job cards. These are the
# only units converted to a concrete datetime; unknown units are left as None
# so the agent never fabricates a posting date.
_RELATIVE_POSTED_UNIT_DAYS = {
    "day": 1,
    "days": 1,
    "week": 7,
    "weeks": 7,
}

# Absolute posting-date formats that Naukri renders on job cards.
_ABSOLUTE_POSTED_FORMATS = ("%d %b %Y", "%d %B %Y", "%d-%m-%Y", "%Y-%m-%d")


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
    # D5: After the in-page timeout, reload once and recheck.
    # Naukri instant-apply may navigate/redirect before the Applied badge appears.
    post_apply_reload_settle_seconds = 5
    application_type_settle_seconds = 0.5
    _header_apply_selector = "#job_header button#apply-button"
    _fallback_apply_selector = "button#apply-button"
    # Single vocabulary for external-apply evidence: classification
    # (``_observe_application_type``) and the recorded external URL
    # (``get_external_redirect_url``) must agree on what counts as external.
    external_text_indicators = [
        "apply on company site",
        "apply on company website",
        "external application",
        "redirecting to",
        "you will be redirected",
        "apply externally",
    ]
    # E5-R4.2: read-only validation evidence. Terminal-state PNGs are written
    # under the existing data/ artifacts directory (covered by data/*.png).
    evidence_dir = "data"
    # How long the Apply click is observed for a popup/new tab after the
    # bounded window and reload settle have both elapsed.
    new_tab_observation_grace_seconds = 5

    def __init__(self, browser_type: str = "chrome"):
        """
        Initialize adapter with browser selection.

        Args:
            browser_type: "chrome" or "edge". Defaults to "chrome".
        """
        self.playwright = None
        self.browser: BrowserContext = None
        self.browser_type = browser_type.lower()
        self.last_startup_error: Optional[str] = None

    async def start_session(self) -> bool:
        try:
            self.last_startup_error = None
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
            self.last_startup_error = f"{type(e).__name__}: {e}"
            logger.exception("playwright_browser_start_failed", extra={"browser_type": self.browser_type})
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
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
        # Check URL first (most reliable)
        if "login" in url_lower:
            raise Exception("Naukri login required")
        # Check body text for explicit login page elements with word boundaries
        # to avoid false positives like "design" containing "sign"
        import re
        if re.search(r'\bsign\s+in\b', visible_lower):
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

    def _iter_naukri_search_urls(self, search_term: str, locations: List[str]) -> List[str]:
        """
        Build one Naukri search URL per configured location (E5-R8).

        Every non-empty, de-duplicated location gets its own URL so discovery
        is no longer pinned to ``locations[0]``. An empty/blank location list
        still falls back to a single India-wide URL.
        """
        ordered: List[str] = []
        seen: set[str] = set()
        for raw in locations or []:
            name = (raw or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(name)

        if not ordered:
            return [self._build_naukri_search_url(search_term, [])]

        return [self._build_naukri_search_url(search_term, [name]) for name in ordered]

    _NEXT_PAGE_TEXT_RE = re.compile(r"^next(\s*page)?$", re.IGNORECASE)

    @classmethod
    def _pick_next_page_href(cls, candidates: List[Dict[str, Any]]) -> Optional[str]:
        """
        Pick the href of the forward pagination control from collected anchors.

        Live-verified Naukri shape (2026-10-11):
          ``<a href="/<slug>-2" class="styles_btn-secondary__<hash>"><span>Next</span></a>`
        Previous shares the hashed ``btn-secondary`` class, so text/rel/aria
        (never the hash alone) identify the forward control. Disabled anchors
        and Apply links are rejected.
        """
        if not isinstance(candidates, list):
            return None

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("disabled") or candidate.get("aria_disabled") == "true":
                continue

            href = (candidate.get("href") or "").strip()
            if not href or href.lower().startswith("javascript"):
                continue

            text = (candidate.get("text") or "").strip()
            aria = (candidate.get("aria") or "").strip().lower()
            rel = (candidate.get("rel") or "").strip().lower()
            css_class = (candidate.get("class") or "").lower()

            if re.search(r"previous|prev\b", text, re.IGNORECASE):
                continue
            if re.search(r"\bapply\b", text, re.IGNORECASE) or "apply" in href.lower():
                continue

            is_next = (
                rel == "next"
                or aria == "next"
                or bool(cls._NEXT_PAGE_TEXT_RE.match(text))
                or "next" in css_class
            )
            if is_next:
                return href

        return None

    async def _find_next_page_url(self, page: Page) -> Optional[str]:
        """
        Return the absolute URL of the next search-results page, or None.

        Reads real pagination anchors from the live DOM (attribute and text
        based; hashed CSS classes are never required). Relative hrefs are
        resolved against the current URL. A Next target equal to the current
        page is treated as terminal to avoid loops.
        """
        try:
            candidates = await page.evaluate(
                """() => {
                    const sel = [
                        'a[aria-label="Next" i]',
                        'a[rel="next"]',
                        'div[class*="pagination"] a',
                        'a[class*="pagination"] a',
                        'a[class*="btn-secondary"]',
                    ].join(',');
                    const nodes = Array.from(document.querySelectorAll(sel));
                    const seen = new Set();
                    const out = [];
                    for (const a of nodes) {
                        if (!a || !a.getAttribute) continue;
                        const key = a.outerHTML.slice(0, 200);
                        if (seen.has(key)) continue;
                        seen.add(key);
                        out.push({
                            href: a.getAttribute('href'),
                            text: (a.innerText || a.textContent || '').trim().slice(0, 60),
                            aria: a.getAttribute('aria-label'),
                            rel: a.getAttribute('rel'),
                            class: a.getAttribute('class') || '',
                            disabled: a.hasAttribute('disabled') || a.getAttribute('aria-disabled') === 'true',
                        });
                    }
                    return out;
                }"""
            )
        except Exception as e:
            logger.debug(f"Failed to collect pagination candidates: {e}")
            return None

        href = self._pick_next_page_href(candidates)
        if not href:
            return None

        current = page.url
        if not isinstance(current, str) or not current:
            current = "https://www.naukri.com/"
        absolute = urllib.parse.urljoin(current, href)

        def _normalize(u: str) -> str:
            parsed = urllib.parse.urlsplit(u)
            path = parsed.path.rstrip("/") or "/"
            return urllib.parse.urlunsplit(
                (parsed.scheme.lower(), parsed.netloc.lower(), path, "", "")
            )

        if _normalize(absolute) == _normalize(current):
            logger.info(f"Next-page target equals current URL, stopping pagination: {absolute}")
            return None

        return absolute

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
            # Absolute URLs already loaded in this search call. Guards against
            # a Next control that points at the current page (or a cycle).
            visited_page_urls: set[str] = {page.url}

            for page_num in range(1, MAX_PAGES + 1):
                # Use the working primary selector
                job_cards = await page.query_selector_all('.srp-jobtuple-wrapper')
                if not job_cards:
                    # Fallback to older selector for backward compatibility
                    job_cards = await page.query_selector_all('article.jobTuple')

                # Freshness-first: emit the cards on this page with a known
                # posting date before cards whose posting date is unknown, and
                # newest first among the known dates. Dates are only read from
                # the card; unknown dates are never fabricated and sort last.
                page_jobs: List[Dict[str, Any]] = []
                for card in job_cards:
                    data = await self._extract_card_data(card)
                    if data:
                        data["page_number"] = page_num
                        page_jobs.append(data)

                page_jobs.sort(key=self._posted_sort_key)
                for data in page_jobs:
                    yield data

                if page_num >= MAX_PAGES:
                    break

                # An empty later page is terminal; do not chase further links.
                if not job_cards and page_num > 1:
                    break

                # Next results page via the live pagination control's href.
                # Naukri's control is an <a> (text "Next", path suffix -2, -3...)
                # whose hashed CSS class changes between deploys; the previous
                # hard-coded class never matched and pagination never advanced.
                next_url = await self._find_next_page_url(page)
                if not next_url:
                    break
                if next_url in visited_page_urls:
                    logger.info(f"Next page URL already visited, stopping pagination: {next_url}")
                    break

                logger.info(f"Advancing search results page {page_num} -> {page_num + 1}: {next_url}")
                try:
                    await page.goto(next_url, wait_until="load", timeout=60000)
                except Exception as e:
                    logger.warning(f"Next page navigation with 'load' failed: {e}, retrying with 'domcontentloaded'")
                    await page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
                visited_page_urls.add(next_url)
                await asyncio.sleep(3)
                await self._check_security(page)
                try:
                    await page.wait_for_selector('.srp-jobtuple-wrapper', timeout=10000)
                except Exception:
                    logger.debug("Job cards not immediately visible on next results page; continuing")
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

    def _posted_sort_key(self, job_data: Dict[str, Any]) -> tuple[int, float]:
        """Sort key that puts the freshest cards first.

        Returns ``(0, -timestamp)`` for cards with a known, grounded posting
        date (newest first) and ``(1, 0.0)`` for cards whose posting date is
        unknown, so unknown dates always sort last. No date is invented here.
        """
        posted_at = job_data.get("posted_at")
        if isinstance(posted_at, datetime):
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=UTC)
            return (0, -posted_at.timestamp())
        return (1, 0.0)

    def _parse_posted_date(self, posted_text: str) -> datetime | None:
        """Parse Naukri posted date text into a timezone-aware UTC datetime.

        Only formats that are actually present on the card are converted. Any
        unrecognised text returns ``None`` so callers never receive a
        fabricated posting date.
        """
        if not posted_text:
            return None

        text = posted_text.strip().lower()
        if not text:
            return None

        now = datetime.now(UTC)

        if "just now" in text or "today" in text:
            return now
        if "yesterday" in text:
            return now - timedelta(days=1)

        # Naukri's explicit floor format: "30+ days ago" means at least 30 days.
        if re.search(r"\b30\+\s*days?\b", text):
            return now - timedelta(days=30)

        relative = re.search(r"\b(\d+)\s*\+?\s*(day|days|week|weeks)\s+ago\b", text)
        if relative:
            amount = int(relative.group(1))
            days = amount * _RELATIVE_POSTED_UNIT_DAYS[relative.group(2)]
            return now - timedelta(days=days)

        for fmt in _ABSOLUTE_POSTED_FORMATS:
            try:
                parsed = datetime.strptime(text.title(), fmt)
            except ValueError:
                continue
            return parsed.replace(tzinfo=UTC)

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
        """Classify one visible page state without waiting or navigation.

        A visible native Apply control is authoritative: Naukri renders it
        only when an in-page application is available, so an external-apply
        phrase appearing elsewhere in the body (job-description prose,
        promos) must not reclassify a native page as EXTERNAL. The external
        body-scan runs only when no native control is visible, preserving
        genuine external-CTA detection (which never renders a native Apply
        button).
        """
        apply_button, _ = await self._find_scoped_apply_button(page)
        if apply_button is not None:
            return "NAUKRI_NATIVE"

        content_lower = (await page.inner_text("body")).lower()
        for indicator in self.external_text_indicators:
            if indicator in content_lower:
                # Evidence must be attributable: record which phrase matched
                # and on which page, so an EXTERNAL decision can be reviewed.
                logger.info(
                    "External apply indicator matched in visible page text: %r"
                    " (page: %s)",
                    indicator,
                    page.url,
                )
                return "EXTERNAL"

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
        - Neither within timeout: reload once and recheck (D5)
        - Still no evidence after reload: NEEDS_ATTENTION

        D5 note: Naukri instant-apply may perform a server-side redirect before
        the Applied badge renders in-page.  A single bounded page reload after
        the initial timeout safely detects that persistent server-side state
        without clicking Apply again.
        """
        try:
            button, source = await self._find_scoped_apply_button(page)
            if button is None:
                screenshot = await self._capture_evidence_screenshot(
                    page, "no_apply_button"
                )
                logger.warning(
                    "No scoped visible Apply button found; needs attention"
                    " | terminal_state=NEEDS_ATTENTION page=%s screenshot=%s",
                    page.url,
                    screenshot or "unavailable",
                )
                return ApplicationStartResult.NEEDS_ATTENTION

            logger.info(f"Clicking Apply button selected from {source}")
            logger.info("Apply click: page url before click: %s", page.url)

            # E5-R4.2: observe - never interact with - a tab or popup the click
            # may open. The observation spans the bounded window plus the reload
            # settle, and is always resolved in the finally block below.
            new_tab_task = asyncio.create_task(
                page.context.wait_for_event(
                    "page",
                    timeout=int(
                        (
                            self.post_apply_timeout_seconds
                            + self.post_apply_reload_settle_seconds
                            + self.new_tab_observation_grace_seconds
                        )
                        * 1000
                    ),
                )
            )
            try:
                await button.click()
                logger.info("Apply click: page url after click: %s", page.url)
                await self._check_security(page)

                # Phase 10 / D5: Bounded in-page polling for explicit post-click evidence.
                window_start = asyncio.get_running_loop().time()
                deadline = window_start + self.post_apply_timeout_seconds
                check_index = 0
                while asyncio.get_running_loop().time() < deadline:
                    check_index += 1
                    elapsed = asyncio.get_running_loop().time() - window_start
                    # Check for explicit Applied state (visible evidence only).
                    # The page-wide scan is deferred: it walks every element on the
                    # page and would consume the whole bounded window in one pass,
                    # starving the container check below.
                    applied, evidence = await self.detect_applied_state(
                        page, scan_whole_page=False
                    )
                    if applied:
                        logger.info(
                            "post-click check #%d at +%.2fs: applied=True evidence=%r",
                            check_index,
                            elapsed,
                            evidence,
                        )
                        return ApplicationStartResult.APPLIED

                    # Check for visible application container (questionnaire/form)
                    container = await self._has_visible_application_container(page)
                    logger.info(
                        "post-click check #%d at +%.2fs: applied=False container=%s",
                        check_index,
                        elapsed,
                        container,
                    )
                    if container:
                        logger.info("Application container detected after click")
                        return ApplicationStartResult.FORM_OPENED

                    await asyncio.sleep(0.25)

                logger.info(
                    "post-click window closed: elapsed=%.2fs checks=%d",
                    asyncio.get_running_loop().time() - window_start,
                    check_index,
                )

                # One page-wide confirmation inside the page, after the bounded
                # window expires and before the (destructive) reload decision.
                applied, evidence = await self.detect_applied_state(page)
                if applied:
                    logger.info(
                        "Applied state detected in-page after bounded window with evidence: %s",
                        evidence,
                    )
                    return ApplicationStartResult.APPLIED

                # D5: In-page timeout expired without evidence.  Naukri instant-apply
                # may update the job page state only after the server-side redirect
                # completes.  Reload once and check the persistent page state.
                # This is NOT a retry of the Apply click — it is a read-only confirmation
                # of whether Naukri persisted the application server-side.
                logger.info(
                    "No in-page post-click evidence after %ss; performing one reload check",
                    self.post_apply_timeout_seconds,
                )
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(self.post_apply_reload_settle_seconds)
                    await self._check_security(page)

                    applied, evidence = await self.detect_applied_state(page)
                    if applied:
                        logger.info(
                            "Applied state confirmed after reload with evidence: %s", evidence
                        )
                        return ApplicationStartResult.APPLIED

                    # Container visible after reload means a form was left open
                    if await self._has_visible_application_container(page):
                        logger.info("Application container visible after reload")
                        return ApplicationStartResult.FORM_OPENED

                except Exception as reload_exc:
                    logger.warning("Post-click reload check failed: %s", reload_exc)

                screenshot = await self._capture_evidence_screenshot(
                    page, "needs_attention"
                )
                logger.warning(
                    "No post-click Applied evidence after in-page wait and reload check"
                    " (page: %s) | terminal_state=NEEDS_ATTENTION checks=%d"
                    " screenshot=%s",
                    page.url,
                    check_index,
                    screenshot or "unavailable",
                )
                return ApplicationStartResult.NEEDS_ATTENTION
            finally:
                await self._record_new_tab(page, new_tab_task)
        except Exception as e:
            logger.error(f"Error starting application: {e}")
            raise e

    async def _capture_evidence_screenshot(self, page: Page, label: str) -> Optional[str]:
        """Capture a read-only PNG of a terminal post-click state.

        E5-R4.2 validation evidence only: no click, no form fill, no navigation,
        no application/retry/preference write. Returns the written path or None.
        """
        try:
            os.makedirs(self.evidence_dir, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(
                self.evidence_dir, f"apply_terminal_{label}_{stamp}.png"
            )
            await page.screenshot(path=path, full_page=False)
            logger.info("Evidence screenshot: label=%s path=%s", label, path)
            return path
        except Exception as exc:
            logger.warning("Evidence screenshot failed (%s): %s", label, exc)
            return None

    async def _record_new_tab(self, page: Page, task: "asyncio.Task") -> None:
        """Record whether the Apply click opened a new tab or popup.

        Read-only observation: the observed page is never clicked, filled,
        navigated, or closed here, and no security check is skipped.
        """
        try:
            if not task.done():
                task.cancel()
            try:
                new_page = await task
            except asyncio.CancelledError:
                logger.info(
                    "new_tab_detected=no (observation window closed before a new page)"
                )
                return
            except Exception as exc:
                logger.info(
                    "new_tab_detected=no (page event: %s)", type(exc).__name__
                )
                return
            pages = getattr(page.context, "pages", None)
            page_count = len(pages) if isinstance(pages, (list, tuple)) else None
            logger.info(
                "new_tab_detected=yes url=%s context_pages=%s",
                getattr(new_page, "url", "unknown"),
                page_count,
            )
        except Exception as exc:
            logger.warning("New-tab observation failed: %s", exc)

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

            # E5-R7: Naukri's conversational drawer renders ONE question at a time
            # (a bot message plus either a radio group or a contenteditable box).
            # Detect it as a single structured question rather than treating each
            # radio input as its own field. Only apply when the container really
            # is the conversational drawer, so legacy forms keep their behavior.
            container_cls = (await container.get_attribute("class")) or ""
            if "chatbot_Drawer" in container_cls:
                conv = await self._detect_conversational_question(container)
                if conv is not None:
                    logger.info(
                        "Detected conversational question (%s): %r options=%s",
                        conv["type"], conv["question"], conv.get("options"),
                    )
                    return [conv]

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

    async def _detect_conversational_question(self, container) -> Optional[Dict[str, Any]]:
        """Detect the single active question inside Naukri's conversational drawer.

        Returns a dict {question, type ('radio'|'text'), options, required} or
        None when the container is not a conversational drawer.
        """
        bot_msg = None
        for selector in (".botMsg span", ".botMsg"):
            el = await container.query_selector(selector)
            if el is not None and await el.is_visible():
                text = (await el.inner_text()).strip()
                if text:
                    bot_msg = text
                    break
        if bot_msg is None:
            return None

        # Radio group (single-select) -> capture the option labels.
        radios = await container.query_selector_all('input[type="radio"]')
        options = []
        for radio in radios:
            radio_id = await radio.get_attribute("id")
            label_text = ""
            if radio_id:
                label = await container.query_selector(f'label[for="{radio_id}"]')
                if label is not None:
                    label_text = (await label.inner_text()).strip()
            if not label_text:
                label_text = (await radio.get_attribute("value") or "").strip()
            if label_text:
                options.append(label_text)
        if options:
            return {
                "question": bot_msg,
                "type": "radio",
                "options": options,
                "required": True,
            }

        # Text question (contenteditable composer).
        composer = await container.query_selector('[contenteditable="true"]')
        if composer is not None and await composer.is_visible():
            return {"question": bot_msg, "type": "text", "options": [], "required": True}

        return {"question": bot_msg, "type": "text", "options": [], "required": True}

    @staticmethod
    def _normalize_choice(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    async def answer_conversational_question(self, page: Page, answer: str) -> bool:
        """Answer the active conversational question and click Save.

        Handles both radio-group questions (clicks the matching option) and
        text questions (fills the contenteditable composer), then clicks the
        drawer's Save control. Returns True only when an answer surface was
        found and Save was clicked.
        """
        container = await self._get_visible_application_container(page)
        if container is None:
            logger.warning("answer_conversational_question: no application container")
            return False

        target = self._normalize_choice(answer)
        answered = False

        radios = await container.query_selector_all('input[type="radio"]')
        if radios:
            best = None
            best_score = -1
            for radio in radios:
                radio_id = await radio.get_attribute("id")
                value = (await radio.get_attribute("value") or "").strip()
                label_text = value
                if radio_id:
                    label = await container.query_selector(f'label[for="{radio_id}"]')
                    if label is not None:
                        label_text = (await label.inner_text()).strip() or value
                norm = self._normalize_choice(label_text)
                score = -1
                if norm and norm == target:
                    score = 100
                elif norm and (norm in target or target in norm):
                    score = len(norm)
                if score > best_score:
                    best_score = score
                    best = radio
            if best is not None and best_score >= 0:
                try:
                    await best.check()
                    answered = True
                    logger.info(
                        "Conversational radio selected (score=%d) for answer=%r",
                        best_score, answer,
                    )
                except Exception as exc:
                    logger.warning("Failed to select conversational radio: %s", exc)
        else:
            composer = await container.query_selector('[contenteditable="true"]')
            if composer is not None and await composer.is_visible():
                try:
                    await composer.fill(answer)
                    answered = True
                    logger.info("Conversational text answer filled for %r", answer)
                except Exception as exc:
                    logger.warning("Failed to fill conversational composer: %s", exc)

        if not answered:
            logger.warning("No conversational answer surface matched answer=%r", answer)
            return False

        return await self._click_conversational_save(page)

    async def _click_conversational_save(self, page: Page) -> bool:
        """Click the conversational drawer's Save control (a div, not a button)."""
        for selector in (".sendMsg", ".send .sendMsg", "#sendMsg .sendMsg"):
            el = await page.query_selector(selector)
            if el is not None and await el.is_visible():
                try:
                    await el.click()
                    logger.info("Conversational Save clicked via %s", selector)
                    return True
                except Exception as exc:
                    logger.warning("Conversational Save click failed (%s): %s", selector, exc)
        logger.warning("No visible conversational Save control found")
        return False

    async def detect_applied_state(
        self, page: Page, scan_whole_page: bool = True
    ) -> tuple[bool, str]:
        """Return explicit post-Apply evidence without inferring from navigation.

        ``scan_whole_page`` controls the last-resort page-wide element scan.
        It is the expensive step (one visibility/text round trip per element on
        the page), so bounded polling passes ``scan_whole_page=False`` and runs
        the page-wide scan once after the window instead.
        """
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
            if not scan_whole_page:
                return False, ""
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
        # Legacy/compat selectors (kept for non-Naukri layouts and future changes).
        for selector in ['[role="dialog"]', ".apply-drawer", ".apply-modal", "form"]:
            for element in await page.query_selector_all(selector):
                if await element.is_visible():
                    return element

        # E5-R7: Naukri's native Apply opens a right-side *conversational* apply
        # drawer whose stable class is ``chatbot_Drawer`` (the element id is
        # instance-hashed, e.g. ``_nmx360oi8Drawer``). Live DOM capture on a
        # native job confirmed this is the application surface: it hosts the
        # screening question, radio/text inputs, and a Save control. None of the
        # legacy selectors above match it (Naukri pages contain zero <form> and
        # zero role="dialog"), so without this branch every genuine native
        # application was misreported as "form did not open" -> NEEDS_ATTENTION.
        for selector in (".chatbot_Drawer", '[class*="chatbot_Drawer"]'):
            for element in await page.query_selector_all(selector):
                if not await element.is_visible():
                    continue
                if await self._looks_like_application_form(element):
                    return element
        return None

    async def _looks_like_application_form(self, element) -> bool:
        """True when a visible container is an application surface, not page chrome.

        E5-R7 false-positive guards:
        - Reject the Apply-button wrapper (``styles_jhc__apply-button-container__*``)
          and any apply-button element, which also contain the substring "apply".
        - Require a real input surface (radio/text/select) or a Save/Submit control.
        """
        cls = (await element.get_attribute("class")) or ""
        if "apply-button" in cls.lower():
            return False
        id_attr = (await element.get_attribute("id")) or ""
        if "apply-button" in id_attr.lower():
            return False

        for probe in (
            'input[type="radio"]',
            'input:not([type="hidden"]):not([type="file"])',
            "textarea",
            "select",
            '[contenteditable="true"]',
            'button[type="submit"]',
            ".sendMsg",
            ".submit-btn",
        ):
            try:
                found = await element.query_selector(probe)
            except Exception:
                found = None
            if found is not None and await found.is_visible():
                return True
        return False

    async def _has_visible_application_container(self, page: Page) -> bool:
        return await self._get_visible_application_container(page) is not None

    async def is_conversational_apply(self, page: Page) -> bool:
        """True when the visible application surface is Naukri's chatbot drawer."""
        container = await self._get_visible_application_container(page)
        if container is None:
            return False
        cls = (await container.get_attribute("class")) or ""
        return "chatbot_Drawer" in cls

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
                'button.submit',
                # E5-R7: Naukri's conversational apply drawer submits via a
                # Save control that is a div (class "sendMsg"), not a button.
                '.sendMsg',
                '.send .sendMsg',
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

        Only a link whose own visible text is external-apply evidence is
        returned. Page-chrome links (footers, promos, social links) are not
        redirect targets and must not be recorded as such.
        """
        try:
            # Look for external links
            external_links = await page.query_selector_all('a[href^="http"]')
            for link in external_links:
                href = await link.get_attribute('href')
                if not href or 'naukri.com' in href:
                    continue
                link_text = (await link.inner_text()).strip().lower()
                if any(
                    indicator in link_text
                    for indicator in self.external_text_indicators
                ):
                    logger.info(
                        "External apply CTA link evidence: text=%r href=%s",
                        link_text,
                        href,
                    )
                    return href

            logger.info(
                "No external-apply CTA link on page; external URL falls back"
                " to the job URL"
            )
            return None
        except Exception as e:
            logger.warning(f"Error getting external URL: {e}")
            return None
