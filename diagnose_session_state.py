"""
Diagnose session state and page loading behavior.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def diagnose_session_state():
    """Diagnose session state and page loading."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("SESSION STATE DIAGNOSTIC")
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

        # Check authentication with different approach
        print("Checking authentication with direct navigation...")
        page = await adapter.browser.new_page()

        # Try navigating directly to homepage with load wait
        await page.goto("https://www.naukri.com", wait_until="load", timeout=30000)
        await asyncio.sleep(3)

        content = await page.content()
        content_lower = content.lower()

        print(f"Homepage content length: {len(content)} characters")
        print(f"First 300 characters: {content[:300]}")
        print()

        if "login" in content_lower and "sign in" in content_lower:
            print("[WARN] Manual Naukri login required")
            print("   Please log in manually to Naukri in the opened browser window.")
            print("   Waiting 30 seconds for manual login...")
            await asyncio.sleep(30)
        else:
            print("[OK] Naukri login/session detected")

        await page.close()
        print()

        # Test search with different approach
        print("Testing search with step-by-step approach...")
        search_url = "https://www.naukri.com/Data-Analyst-jobs-in-Bengaluru"

        search_page = await adapter.browser.new_page()

        try:
            print(f"Navigating to: {search_url}")

            # Try with different wait strategies sequentially
            print("Attempt 1: domcontentloaded")
            await search_page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            content1 = await search_page.inner_text('body')
            print(f"  Content length: {len(content1)}")
            print(f"  First 200 chars: {content1[:200]}")
            print()

            print("Attempt 2: Reload with load")
            await search_page.reload(wait_until="load", timeout=30000)
            await asyncio.sleep(3)
            content2 = await search_page.inner_text('body')
            print(f"  Content length: {len(content2)}")
            print(f"  First 200 chars: {content2[:200]}")
            print()

            if len(content2) > 1000:
                print("[SUCCESS] Page has content after reload")
                cards = await search_page.query_selector_all('.srp-jobtuple-wrapper')
                print(f"Job cards found: {len(cards)}")
            else:
                print("[FAIL] Page still has minimal content")

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
        print(f"[ERROR] Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("Cleaning up...")
        await adapter.stop_session()
        print("[OK] Browser session closed")


if __name__ == "__main__":
    asyncio.run(diagnose_session_state())
