"""
Simple navigation test for search page.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def simple_navigation_test():
    """Simple navigation test."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("SIMPLE NAVIGATION TEST")
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
        print("Checking authentication...")
        page = await adapter.browser.new_page()
        await page.goto("https://www.naukri.com", wait_until="load", timeout=30000)
        await asyncio.sleep(2)

        content = await page.content()
        content_lower = content.lower()

        if "login" in content_lower and "sign in" in content_lower:
            print("[WARN] Manual Naukri login required")
            print("   Waiting 30 seconds for manual login...")
            await asyncio.sleep(30)
        else:
            print("[OK] Naukri login/session detected")

        await page.close()
        print()

        # Test navigation from homepage to search
        print("Testing navigation from homepage to search...")
        search_page = await adapter.browser.new_page()

        try:
            # First go to homepage
            await search_page.goto("https://www.naukri.com", wait_until="load", timeout=30000)
            await asyncio.sleep(2)
            print(f"Homepage loaded: {search_page.url}")

            # Then navigate to search
            search_url = "https://www.naukri.com/Data-Analyst-jobs-in-Bengaluru"
            await search_page.goto(search_url, wait_until="load", timeout=30000)
            await asyncio.sleep(5)

            print(f"Search page URL: {search_page.url}")
            print(f"Title: {await search_page.title()}")

            body_text = await search_page.inner_text('body')
            print(f"Body length: {len(body_text)} characters")

            if len(body_text) > 1000:
                print(f"[SUCCESS] Page has content")
                cards = await search_page.query_selector_all('.srp-jobtuple-wrapper')
                print(f"Job cards: {len(cards)}")
                if cards:
                    print(f"[SUCCESS] Found {len(cards)} job cards!")
            else:
                print(f"[FAIL] Page has minimal content")
                print(f"First 300 chars: {body_text[:300]}")

        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()

        finally:
            print()
            print("Browser will remain open for 30 seconds for manual inspection.")
            await asyncio.sleep(30)
            await search_page.close()

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("Cleaning up...")
        await adapter.stop_session()
        print("[OK] Browser session closed")


if __name__ == "__main__":
    asyncio.run(simple_navigation_test())
