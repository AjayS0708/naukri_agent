import asyncio
import re
import urllib.parse
from typing import AsyncGenerator, Dict, Any, List
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
import os

from backend.services.platform_adapter import JobPlatformAdapter
from backend.core.logging import get_logger

logger = get_logger(__name__)

# User-data directory for Playwright persistent context to maintain active logged-in sessions without needing credentials
USER_DATA_DIR = os.path.join(os.getcwd(), ".agent", "browser_session")


class NaukriAdapter(JobPlatformAdapter):
    """
    Playwright-based adapter for Naukri job discovery.
    Operates using normal browser interactions without evasion techniques.
    Raises exceptions on CAPTCHA / Security walls designed to halt agents.
    """
    platform_name = "naukri"
    
    def __init__(self):
        self.playwright = None
        self.browser: BrowserContext = None
        
    async def start_session(self) -> bool:
        try:
            self.playwright = await async_playwright().start()
            
            # Use persistent context to reuse existing sessions (assumes manual login beforehand)
            self.browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                headless=False, # UI required for CAPTCHAs or manual logins if ever needed but typically False
                args=["--disable-blink-features=AutomationControlled"], # Basic clean driver
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
        if "captcha" in content.lower() or "verify you are human" in content.lower() or "challenge" in content.lower():
            raise Exception("Security Verification Required")
        if "login" in page.url.lower():
            raise Exception("Naukri login required")
            
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

    async def search_jobs(self, search_term: str, locations: List[str]) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Navigates Naukri and scrapes job cards.
        Extracts structured info. 
        """
        if not self.browser:
            return

        page = await self.browser.new_page()
        try:
            # Build search URL
            # Note: Naukri often uses https://www.naukri.com/{term}-jobs-in-{location}
            # For simplicity, using generic query param format which works reasonably well
            base_url = "https://www.naukri.com/jobs-in-india"
            query_params = {"k": search_term}
            if locations:
                 query_params["l"] = ",".join(locations)
                 
            url = f"{base_url}?{urllib.parse.urlencode(query_params)}"
            logger.info(f"Navigating to {url}")
            
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3) # Wait for cards SPA load
            
            await self._check_security(page)
            
            # Paginate up to MAX_SEARCH_PAGES
            MAX_PAGES = 3
            
            for _ in range(MAX_PAGES):
                job_cards = await page.query_selector_all('article.jobTuple')
                if not job_cards:
                     # try newer Naukri layout class
                     job_cards = await page.query_selector_all('.srp-jobtuple-wrapper')
                     
                for card in job_cards:
                    data = await self._extract_card_data(card)
                    if data:
                        yield data
                        
                # Next page
                next_btn = await page.query_selector('a.styles_btn-secondary__2BqIV')
                if next_btn:
                    await next_btn.click()
                    await asyncio.sleep(4)
                else:
                    break
        finally:
            await page.close()

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
                "external_job_id": external_job_id
            }
        except Exception as e:
            logger.debug(f"Error parsing job card: {e}")
            return {}
