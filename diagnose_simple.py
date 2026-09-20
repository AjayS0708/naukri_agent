"""
Simple diagnostic to understand what's happening with Naukri search.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def simple_diagnostic():
    """Simple diagnostic."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("SIMPLE NAUKRI DIAGNOSTIC")
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

        # Try direct navigation with different wait strategies
        print("Testing different navigation strategies...")

        test_urls = [
            "https://www.naukri.com/data-analyst-jobs-in-bengaluru",
            "https://www.naukri.com/Data-Analyst-jobs-in-Bengaluru",
        ]

        for url in test_urls:
            print(f"\nTesting URL: {url}")
            test_page = await adapter.browser.new_page()

            try:
                # Try with networkidle instead of domcontentloaded
                await test_page.goto(url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(5)  # Longer wait for SPA

                print(f"  Actual URL: {test_page.url}")
                print(f"  Title: {await test_page.title()}")

                body_text = await test_page.inner_text('body')
                print(f"  Body length: {len(body_text)} chars")

                if len(body_text) > 1000:
                    print(f"  [SUCCESS] Page has substantial content")

                    # Try multiple selectors
                    selectors = [
                        '.srp-jobtuple-wrapper',
                        'article.jobTuple',
                        '[class*="job"]',
                        '[class*="tuple"]',
                    ]

                    for selector in selectors:
                        try:
                            cards = await test_page.query_selector_all(selector)
                            if cards:
                                print(f"  Selector '{selector}': {len(cards)} elements")
                        except:
                            pass
                else:
                    print(f"  [FAIL] Page has minimal content")

                    # Show what we got
                    print(f"  First 300 chars of body:")
                    print(f"  {body_text[:300]}")

            except Exception as e:
                print(f"  [ERROR] {e}")
            finally:
                await test_page.close()

        print()
        print("="*80)
        print("DIAGNOSTIC COMPLETE")
        print("="*80)
        print("Browser will remain open for 30 seconds for manual inspection.")

        await asyncio.sleep(30)

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
    asyncio.run(simple_diagnostic())
