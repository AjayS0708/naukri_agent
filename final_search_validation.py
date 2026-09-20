"""
Final validation of Naukri search flow with wait-strategy fix.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.services.naukri.adapter import NaukriAdapter


async def final_search_validation():
    """Final validation of complete search flow."""
    adapter = NaukriAdapter(browser_type="chrome")

    print("="*80)
    print("FINAL NAUKRI SEARCH VALIDATION")
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

        # Test URL building
        print("Step 3: Testing URL building...")
        search_term = "Data Analyst"
        location = "Bengaluru"

        built_url = adapter._build_naukri_search_url(search_term, [location])
        print(f"Generated search URL: {built_url}")
        print()

        # Run actual search
        print("Step 4: Running actual search...")
        print(f"Search term: {search_term}")
        print(f"Location: {location}")
        print()

        search_page = await adapter.browser.new_page()

        try:
            # Navigate with load wait strategy
            await search_page.goto(built_url, wait_until="load", timeout=30000)

            print(f"Final URL: {search_page.url}")
            print(f"Page title: {await search_page.title()}")
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

                # Re-check security
                try:
                    await adapter._check_security(search_page)
                    print("[OK] Security cleared after manual resolution")
                except Exception as e2:
                    print(f"[FAIL] Security still required: {e2}")
                    print("   Cannot proceed with search validation")
                    return
            print()

            # Inspect page content
            print("Step 6: Inspecting page content...")
            body_text = await search_page.inner_text('body')
            print(f"Page content length: {len(body_text)} characters")
            print()

            # Check for job cards
            print("Step 7: Checking for job cards...")
            selector1 = '.srp-jobtuple-wrapper'
            selector2 = 'article.jobTuple'

            cards1 = await search_page.query_selector_all(selector1)
            cards2 = await search_page.query_selector_all(selector2)

            print(f"Selector '{selector1}': {len(cards1)} cards")
            print(f"Selector '{selector2}': {len(cards2)} cards")
            print()

            if cards1:
                print(f"[SUCCESS] Found {len(cards1)} job cards with primary selector")
                print()

                # Extract up to 5 jobs
                print("Step 8: Extracting job details (up to 5 jobs)...")
                jobs_extracted = []

                for i, card in enumerate(cards1[:5]):
                    try:
                        job_data = await adapter._extract_card_data(card)
                        if job_data:
                            jobs_extracted.append(job_data)
                            print(f"Job {i+1}:")
                            print(f"  Title: {job_data.get('title')}")
                            print(f"  Company: {job_data.get('company')}")
                            print(f"  Location: {job_data.get('location')}")
                            print(f"  Experience: {job_data.get('experience')}")
                            print(f"  Salary: {job_data.get('salary')}")
                            print(f"  Posted: {job_data.get('posted_at')}")
                            print(f"  URL: {job_data.get('url')}")
                            print(f"  External ID: {job_data.get('external_job_id')}")
                            print()
                    except Exception as e:
                        print(f"Job {i+1}: Extraction failed - {e}")
                        print()

                print(f"Total jobs extracted: {len(jobs_extracted)}")
                print()

                # Check pagination
                print("Step 9: Checking pagination...")
                next_btn = await search_page.query_selector('a.styles_btn-secondary__2BqIV')
                if next_btn:
                    print("[OK] Pagination button found")
                else:
                    print("[INFO] No pagination button found (might be single page)")
                print()

            else:
                print("[FAIL] No job cards found with either selector")
                print("   Search may have returned no results or page structure changed")
                print()

        except Exception as e:
            print(f"[ERROR] Search failed: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Keep page open for manual inspection
            print("="*80)
            print("VALIDATION COMPLETE")
            print("="*80)
            print("The browser window will remain open for 30 seconds for manual inspection.")
            print()
            print("Press Ctrl+C to close early, or wait for auto-close.")
            print("="*80)

            await asyncio.sleep(30)

            await search_page.close()

    except Exception as e:
        print(f"[ERROR] Validation failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        print("Cleaning up...")
        await adapter.stop_session()
        print("[OK] Browser session closed")


if __name__ == "__main__":
    asyncio.run(final_search_validation())
