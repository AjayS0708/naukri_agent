"""
Diagnostic script to investigate Naukri search 0-results problem.
This script will inspect the live page to understand what's happening.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter
import urllib.parse


async def diagnose_search():
    """Diagnose the Naukri search issue."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("NAUKRI SEARCH DIAGNOSTIC")
    print("="*80)
    print()

    try:
        # Start browser session
        print("Step 1: Starting browser session...")
        started = await adapter.start_session()
        if not started:
            print("[FAIL] Failed to start browser session")
            return

        print("[OK] Browser session started")
        print()

        # Check authentication
        print("Step 2: Checking authentication status...")
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

        # Build search URL as current implementation does
        print("Step 3: Building search URL...")
        search_term = "Data Analyst"
        locations = ["Bengaluru"]

        base_url = "https://www.naukri.com/jobs-in-india"
        query_params = {"k": search_term}
        if locations:
            query_params["l"] = ",".join(locations)

        url = f"{base_url}?{urllib.parse.urlencode(query_params)}"
        print(f"Current search URL: {url}")
        print()

        # Navigate to search page
        print("Step 4: Navigating to search page...")
        page = await adapter.browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        print(f"Actual page URL after navigation: {page.url}")
        print(f"Page title: {await page.title()}")
        print()

        # Check for security
        print("Step 5: Checking for security challenges...")
        try:
            await adapter._check_security(page)
            print("[OK] No security challenges detected")
        except Exception as e:
            print(f"[WARN] Security challenge detected: {e}")
            print("   If this is a CAPTCHA, please solve it manually in the browser window.")
            print("   Waiting 30 seconds for manual resolution...")
            await asyncio.sleep(30)
            print("[OK] Continuing after manual resolution")
        print()

        # Inspect page content
        print("Step 6: Inspecting page content...")
        content = await page.content()
        content_lower = content.lower()

        # Check for common page states
        if "no jobs found" in content_lower or "0 jobs" in content_lower:
            print("[INFO] Page indicates 'no jobs found'")
        elif "error" in content_lower and "page" in content_lower:
            print("[INFO] Page shows error state")
        elif "login" in content_lower and "sign in" in content_lower:
            print("[INFO] Page redirects to login")
        else:
            print("[INFO] Page appears to be a normal search results page")
        print()

        # Test current selectors
        print("Step 7: Testing current job card selectors...")
        selector1 = 'article.jobTuple'
        selector2 = '.srp-jobtuple-wrapper'

        cards1 = await page.query_selector_all(selector1)
        cards2 = await page.query_selector_all(selector2)

        print(f"Selector '{selector1}': {len(cards1)} cards found")
        print(f"Selector '{selector2}': {len(cards2)} cards found")
        print()

        # Look for alternative selectors
        print("Step 8: Looking for alternative job card selectors...")
        alternative_selectors = [
            '.job-tuple',
            '.jobTuple',
            '[class*="job"]',
            '[class*="tuple"]',
            '.srp-job-tuple',
            '.srp-jobtuple',
            'div[class*="job"]',
            'article[class*="job"]',
        ]

        for selector in alternative_selectors:
            try:
                cards = await page.query_selector_all(selector)
                if cards:
                    print(f"  Selector '{selector}': {len(cards)} elements found")
            except Exception as e:
                pass
        print()

        # Inspect page structure
        print("Step 9: Inspecting page structure...")
        # Get some sample HTML to understand the structure
        body_text = await page.inner_text('body')
        print(f"Page body text length: {len(body_text)} characters")
        print(f"First 500 characters of body:")
        print(body_text[:500])
        print()

        # Check for specific job-related elements
        print("Step 10: Checking for job-related elements...")
        job_title_elements = await page.query_selector_all('[class*="title"]')
        company_elements = await page.query_selector_all('[class*="company"]')
        location_elements = await page.query_selector_all('[class*="location"]')
        exp_elements = await page.query_selector_all('[class*="exp"]')

        print(f"Elements with 'title' in class: {len(job_title_elements)}")
        print(f"Elements with 'company' in class: {len(company_elements)}")
        print(f"Elements with 'location' in class: {len(location_elements)}")
        print(f"Elements with 'exp' in class: {len(exp_elements)}")
        print()

        # Try to identify actual job cards by looking for common patterns
        print("Step 11: Looking for job card patterns...")
        all_divs = await page.query_selector_all('div')
        print(f"Total div elements on page: {len(all_divs)}")

        # Look for divs that might be job cards
        potential_job_cards = []
        for div in all_divs[:100]:  # Check first 100 divs
            try:
                class_attr = await div.get_attribute('class')
                if class_attr and any(keyword in class_attr.lower() for keyword in ['job', 'tuple', 'card', 'listing']):
                    potential_job_cards.append(class_attr)
            except:
                pass

        if potential_job_cards:
            print(f"Potential job card classes found (first 10):")
            for card_class in potential_job_cards[:10]:
                print(f"  - {card_class}")
        else:
            print("No obvious job card classes found")
        print()

        # Keep page open for manual inspection
        print("="*80)
        print("DIAGNOSTIC COMPLETE")
        print("="*80)
        print("The browser window will remain open for 60 seconds for manual inspection.")
        print("Please inspect the page to understand the actual structure.")
        print()
        print("Press Ctrl+C to close early, or wait for auto-close.")
        print("="*80)

        await asyncio.sleep(60)

        await page.close()

    except Exception as e:
        print(f"[ERROR] Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        print("Cleaning up...")
        await adapter.stop_session()
        print("[OK] Browser session closed")


if __name__ == "__main__":
    asyncio.run(diagnose_search())
