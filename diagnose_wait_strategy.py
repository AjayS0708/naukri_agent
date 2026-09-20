"""
Test different wait strategies for Naukri search page.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def test_wait_strategies():
    """Test different wait strategies."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("TESTING WAIT STRATEGIES")
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

        # Test different wait strategies
        search_url = "https://www.naukri.com/Data-Analyst-jobs-in-Bengaluru"

        wait_strategies = [
            ("domcontentloaded", "domcontentloaded"),
            ("load", "load"),
            ("networkidle", "networkidle"),
        ]

        for strategy_name, strategy in wait_strategies:
            print(f"Testing wait strategy: {strategy_name}")
            test_page = await adapter.browser.new_page()

            try:
                await test_page.goto(search_url, wait_until=strategy, timeout=30000)
                await asyncio.sleep(5)  # Additional wait

                print(f"  Actual URL: {test_page.url}")
                print(f"  Title: {await test_page.title()}")

                body_text = await test_page.inner_text('body')
                print(f"  Body length: {len(body_text)} characters")

                if len(body_text) > 1000:
                    print(f"  [SUCCESS] Page has content with {strategy_name}")

                    # Check for job cards
                    cards = await test_page.query_selector_all('.srp-jobtuple-wrapper')
                    print(f"  Job cards found: {len(cards)}")

                    if cards:
                        print(f"  [SUCCESS] Found {len(cards)} job cards!")
                        break  # Found working strategy
                else:
                    print(f"  [FAIL] Page has minimal content with {strategy_name}")
                    print(f"  First 300 chars: {body_text[:300]}")

            except Exception as e:
                print(f"  [ERROR] {strategy_name} failed: {e}")
            finally:
                await test_page.close()

            print()

        print("="*80)
        print("WAIT STRATEGY TESTING COMPLETE")
        print("="*80)
        print("Browser will remain open for 30 seconds for manual inspection.")

        await asyncio.sleep(30)

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
    asyncio.run(test_wait_strategies())
