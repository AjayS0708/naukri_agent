"""
Test alternative Naukri search URL formats.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def test_search_urls():
    """Test different Naukri search URL formats."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("TESTING NAUKRI SEARCH URL FORMATS")
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

        # Test different URL formats
        search_term = "Data Analyst"
        location = "Bengaluru"

        # Format 1: Current implementation (broken)
        url1 = f"https://www.naukri.com/jobs-in-india?k={search_term}&l={location}"

        # Format 2: Path-based format (mentioned in comments)
        url2 = f"https://www.naukri.com/{search_term.replace(' ', '-')}-jobs-in-{location}"

        # Format 3: Alternative query format
        url3 = f"https://www.naukri.com/job-search?k={search_term}&l={location}"

        # Format 4: Another common format
        url4 = f"https://www.naukri.com/{search_term.replace(' ', '-')}-jobs-in-{location.replace(' ', '-')}"

        test_urls = [
            ("Current implementation", url1),
            ("Path-based format", url2),
            ("Job-search format", url3),
            ("Path-based with hyphenated location", url4),
        ]

        for name, url in test_urls:
            print(f"Testing: {name}")
            print(f"URL: {url}")

            test_page = await adapter.browser.new_page()
            try:
                await test_page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                print(f"  Actual URL: {test_page.url}")
                print(f"  Title: {await test_page.title()}")

                # Check for security
                try:
                    await adapter._check_security(test_page)
                    print(f"  Security: OK")
                except Exception as e:
                    print(f"  Security: {e}")

                # Check page content
                body_text = await test_page.inner_text('body')
                print(f"  Body length: {len(body_text)} chars")

                # Check for job indicators
                if "job" in body_text.lower() and len(body_text) > 1000:
                    print(f"  [POTENTIAL SUCCESS] Page contains job content")

                    # Test selectors
                    selector1 = 'article.jobTuple'
                    selector2 = '.srp-jobtuple-wrapper'
                    selector3 = '.styles_fcs__tuple__Pb2B6'

                    cards1 = await test_page.query_selector_all(selector1)
                    cards2 = await test_page.query_selector_all(selector2)
                    cards3 = await test_page.query_selector_all(selector3)

                    print(f"  Selector '{selector1}': {len(cards1)} cards")
                    print(f"  Selector '{selector2}': {len(cards2)} cards")
                    print(f"  Selector '{selector3}': {len(cards3)} cards")

                    if cards1 or cards2 or cards3:
                        print(f"  [SUCCESS] Found job cards!")
                else:
                    print(f"  [FAIL] Page does not contain job content")

                print()
            except Exception as e:
                print(f"  [ERROR] {e}")
                print()
            finally:
                await test_page.close()

        print("="*80)
        print("URL TESTING COMPLETE")
        print("="*80)

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        print("Cleaning up...")
        await adapter.stop_session()
        print("[OK] Browser session closed")


if __name__ == "__main__":
    asyncio.run(test_search_urls())
