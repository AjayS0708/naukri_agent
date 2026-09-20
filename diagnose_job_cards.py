"""
Inspect job card structure to understand extraction selectors.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def inspect_job_cards():
    """Inspect job card structure."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("INSPECTING JOB CARD STRUCTURE")
    print("="*80)
    print()

    try:
        # Start browser session
        print("Starting browser session...")
        started = await adapter.start_session()
        if not started:
            print("[FAIL] Failed to start browser session")
            return

        print("[OK] Browser session started")
        print()

        # Check authentication
        print("Checking authentication status...")
        page = await adapter.browser.new_page()
        await page.goto("https://www.naukri.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        content = await page.content()
        content_lower = content.lower()

        if "login" in content_lower and "sign in" in content_lower:
            print("[WARN] Manual Naukri login required")
            print("   Please log in manually to Naukri in the opened browser window.")
            print("   Waiting 30 seconds for manual login...")
            await asyncio.sleep(30)
        else:
            print("[OK] Naukri login/session detected")

        await page.close()
        print()

        # Navigate to working search URL
        print("Navigating to working search URL...")
        search_url = "https://www.naukri.com/Data-Analyst-jobs-in-Bengaluru"
        print(f"URL: {search_url}")

        page = await adapter.browser.new_page()
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        print(f"Actual URL: {page.url}")
        print(f"Title: {await page.title()}")
        print()

        # Get job cards using working selector
        print("Getting job cards...")
        job_cards = await page.query_selector_all('.srp-jobtuple-wrapper')
        print(f"Found {len(job_cards)} job cards")
        print()

        # Inspect first job card
        if job_cards:
            print("Inspecting first job card structure...")
            first_card = job_cards[0]

            # Get HTML of first card
            card_html = await first_card.inner_html()
            print(f"Card HTML length: {len(card_html)} characters")
            print(f"First 1000 characters of card HTML:")
            print(card_html[:1000])
            print()

            # Test current extraction selectors
            print("Testing current extraction selectors on first card:")

            selectors_to_test = [
                ('a.title', 'Job title link'),
                ('a.comp-name', 'Company name link'),
                ('.exp', 'Experience'),
                ('.sal', 'Salary'),
                ('.loc', 'Location'),
                ('.job-post-day', 'Posted date'),
                ('.posted-date', 'Posted date alternative'),
                ('.job-type', 'Job type'),
                ('.employment-type', 'Employment type'),
            ]

            for selector, description in selectors_to_test:
                element = await first_card.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    print(f"  [OK] {description} ({selector}): '{text[:50]}...'")
                else:
                    print(f"  [FAIL] {description} ({selector}): Not found")
            print()

            # Look for alternative selectors
            print("Looking for alternative selectors in first card...")
            all_links = await first_card.query_selector_all('a')
            print(f"  Total links in card: {len(all_links)}")

            for i, link in enumerate(all_links[:5]):
                href = await link.get_attribute('href')
                text = await link.inner_text()
                print(f"  Link {i+1}: '{text[:30]}...' -> {href[:50] if href else 'no href'}")
            print()

            # Check for common job card patterns
            print("Looking for job title patterns...")
            title_candidates = await first_card.query_selector_all('[class*="title"]')
            print(f"  Elements with 'title' in class: {len(title_candidates)}")
            for i, elem in enumerate(title_candidates[:3]):
                class_attr = await elem.get_attribute('class')
                text = await elem.inner_text()
                print(f"    {i+1}. class='{class_attr}' text='{text[:30]}...'")
            print()

            print("Looking for company patterns...")
            company_candidates = await first_card.query_selector_all('[class*="comp"]')
            print(f"  Elements with 'comp' in class: {len(company_candidates)}")
            for i, elem in enumerate(company_candidates[:3]):
                class_attr = await elem.get_attribute('class')
                text = await elem.inner_text()
                print(f"    {i+1}. class='{class_attr}' text='{text[:30]}...'")
            print()

            print("Looking for location patterns...")
            location_candidates = await first_card.query_selector_all('[class*="loc"]')
            print(f"  Elements with 'loc' in class: {len(location_candidates)}")
            for i, elem in enumerate(location_candidates[:3]):
                class_attr = await elem.get_attribute('class')
                text = await elem.inner_text()
                print(f"    {i+1}. class='{class_attr}' text='{text[:30]}...'")
            print()

        # Keep page open for manual inspection
        print("="*80)
        print("INSPECTION COMPLETE")
        print("="*80)
        print("The browser window will remain open for 60 seconds for manual inspection.")
        print()
        print("Press Ctrl+C to close early, or wait for auto-close.")
        print("="*80)

        await asyncio.sleep(60)

        await page.close()

    except Exception as e:
        print(f"[ERROR] Inspection failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        print("Cleaning up...")
        await adapter.stop_session()
        print("[OK] Browser session closed")


if __name__ == "__main__":
    asyncio.run(inspect_job_cards())
