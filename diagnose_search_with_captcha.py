"""
Diagnostic script to understand search behavior after CAPTCHA resolution.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def diagnose_search_with_captcha():
    """Diagnose search behavior after CAPTCHA resolution."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("SEARCH DIAGNOSTIC WITH CAPTCHA RESOLUTION")
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

        # Test the new URL building logic
        print("Step 3: Testing new URL building logic...")
        search_term = "Data Analyst"
        location = "Bengaluru"

        built_url = adapter._build_naukri_search_url(search_term, [location])
        print(f"Built URL: {built_url}")
        print()

        # Navigate to the search URL
        print("Step 4: Navigating to search URL...")
        search_page = await adapter.browser.new_page()

        try:
            await search_page.goto(built_url, wait_until="domcontentloaded", timeout=30000)
            print(f"Initial navigation successful")
            print(f"Actual URL: {search_page.url}")
            print(f"Title: {await search_page.title()}")
            print()

            # Check for security
            print("Step 5: Checking for security challenges...")
            try:
                await adapter._check_security(search_page)
                print("[OK] No security challenges detected")
            except Exception as e:
                print(f"[WARN] Security challenge detected: {e}")
                print("   Please solve the CAPTCHA manually in the browser window.")
                print("   Waiting 30 seconds for manual resolution...")
                await asyncio.sleep(30)
                print("[OK] Continuing after manual resolution")

                # Re-check security after manual resolution
                try:
                    await adapter._check_security(search_page)
                    print("[OK] Security cleared after manual resolution")
                except Exception as e2:
                    print(f"[FAIL] Security still required: {e2}")
                    print("   This indicates the CAPTCHA was not successfully resolved")
            print()

            # Inspect page content
            print("Step 6: Inspecting page content...")
            body_text = await search_page.inner_text('body')
            print(f"Body length: {len(body_text)} characters")

            if len(body_text) > 1000:
                print("[INFO] Page has substantial content")

                # Check for job cards
                print("Step 7: Checking for job cards...")
                selector1 = '.srp-jobtuple-wrapper'
                selector2 = 'article.jobTuple'

                cards1 = await search_page.query_selector_all(selector1)
                cards2 = await search_page.query_selector_all(selector2)

                print(f"Selector '{selector1}': {len(cards1)} cards")
                print(f"Selector '{selector2}': {len(cards2)} cards")

                if cards1:
                    print("[SUCCESS] Found job cards with primary selector!")
                    # Inspect first card
                    first_card = cards1[0]
                    card_html = await first_card.inner_html()
                    print(f"First card HTML length: {len(card_html)} characters")
                    print(f"First 500 characters of card HTML:")
                    print(card_html[:500])
                elif cards2:
                    print("[SUCCESS] Found job cards with fallback selector!")
                else:
                    print("[FAIL] No job cards found with either selector")

                    # Check if page has job-related content
                    if "job" in body_text.lower():
                        print("[INFO] Page contains 'job' text but no job cards found")
                        print("This might indicate a different page structure")

                    # Show some page content
                    print(f"First 500 characters of body:")
                    print(body_text[:500])
            else:
                print("[FAIL] Page has minimal content")
                print(f"First 500 characters of body:")
                print(body_text[:500])

            print()

        except Exception as e:
            print(f"[ERROR] Navigation failed: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Keep page open for manual inspection
            print("="*80)
            print("DIAGNOSTIC COMPLETE")
            print("="*80)
            print("The browser window will remain open for 60 seconds for manual inspection.")
            print()
            print("Press Ctrl+C to close early, or wait for auto-close.")
            print("="*80)

            await asyncio.sleep(60)

            await search_page.close()

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
    asyncio.run(diagnose_search_with_captcha())
