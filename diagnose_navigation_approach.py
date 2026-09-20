"""
Test different navigation approaches to the search page.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def test_navigation_approaches():
    """Test different navigation approaches."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("NAVIGATION APPROACH DIAGNOSTIC")
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

        print()

        # Test different navigation approaches
        search_url = "https://www.naukri.com/Data-Analyst-jobs-in-Bengaluru"

        approaches = [
            ("Direct navigation with load", lambda p: p.goto(search_url, wait_until="load", timeout=30000)),
            ("Navigation from homepage", lambda p: (
                p.goto("https://www.naukri.com", wait_until="load", timeout=30000),
                asyncio.sleep(2),
                p.goto(search_url, wait_until="load", timeout=30000)
            )),
            ("Navigation with javascript:location", lambda p: p.evaluate(f"window.location.href = '{search_url}'")),
        ]

        for approach_name, nav_func in approaches:
            print(f"Testing: {approach_name}")
            test_page = await adapter.browser.new_page()

            try:
                # Execute navigation
                nav_func(test_page)
                await asyncio.sleep(5)  # Wait for page to settle

                print(f"  Actual URL: {test_page.url}")
                print(f"  Title: {await test_page.title()}")

                body_text = await test_page.inner_text('body')
                print(f"  Body length: {len(body_text)} characters")

                if len(body_text) > 1000:
                    print(f"  [SUCCESS] Page has content")
                    cards = await test_page.query_selector_all('.srp-jobtuple-wrapper')
                    print(f"  Job cards: {len(cards)}")
                    if cards:
                        print(f"  [SUCCESS] Found working approach!")
                        break
                else:
                    print(f"  [FAIL] Page has minimal content")
                    print(f"  First 300 chars: {body_text[:300]}")

            except Exception as e:
                print(f"  [ERROR] {e}")
            finally:
                await test_page.close()
            print()

        print("="*80)
        print("DIAGNOSTIC COMPLETE")
        print("Browser will remain open for 30 seconds for manual inspection.")
        await asyncio.sleep(30)

    except Exception as e:
        print(f"[ERROR] Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("Cleaning up...")
        await adapter.stop_session()
        print("[OK] Browser session closed")


if __name__ == "__main__":
    asyncio.run(test_navigation_approaches())
