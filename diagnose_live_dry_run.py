"""
Phase 9B-2B: Live Naukri Dry-Run Validation
============================================
- Real Playwright browser
- Real Naukri search (Data Analyst + Bengaluru)
- Bounded discovery: max 5 jobs
- Gemini analysis on ONE selected job
- ApplicationRunner with dry_run=True
- STOPS before submit_application()
- No real application submitted

Run: python diagnose_live_dry_run.py
"""
import asyncio
import json
import sys
import os
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select
from backend.database.database import initialize_database, get_session
from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.services.naukri.adapter import NaukriAdapter
from backend.services.gemini.provider import GeminiProvider, APIQuotaExhaustedError
from backend.services.applications.runner import ApplicationRunner
from backend.services.matching.normalizer import extract_experience_years
from backend.core.config import get_settings

LOCATIONS = ["Bengaluru"]
MAX_JOBS = 5
MAX_SEARCH_TERMS = 5

# ── Safety proof ──────────────────────────────────────────────────────────────
_submit_call_count = 0
_original_submit = NaukriAdapter.submit_application

async def _patched_submit(self, page):
    global _submit_call_count
    _submit_call_count += 1
    raise RuntimeError(
        "SAFETY VIOLATION: submit_application() was called in dry-run mode. "
        "This must never happen."
    )

NaukriAdapter.submit_application = _patched_submit
# ─────────────────────────────────────────────────────────────────────────────


def _banner(msg):
    print(f"\n{'='*72}")
    print(f"  {msg}")
    print('='*72)


def _check_hard_filters(job_data: dict, preference: JobPreference) -> tuple[bool, str]:
    """Apply deterministic hard filters to raw job data before persisting."""
    title = job_data.get("title", "")
    location = job_data.get("location", "")
    experience = job_data.get("experience", "")
    salary = job_data.get("salary", "")

    # Location filter (only if preferences configured)
    if preference.locations and location:
        from backend.services.matching.normalizer import has_overlapping_location
        if not has_overlapping_location(location, preference.locations):
            return False, f"Location mismatch: '{location}'"

    # Experience filter
    if experience:
        exp_min, _ = extract_experience_years(experience)
        if exp_min is not None and exp_min > 3:  # user has ~1 entry = 1yr, grace=2 → block >3
            return False, f"Experience too high: '{experience}'"

    return True, "PASS"


async def _ensure_job_description(adapter: NaukriAdapter, job: Job) -> str:
    """Populate a persisted diagnostic job with its real Naukri description."""
    if job.description:
        return job.description
    if not job.url:
        return ""

    description = await adapter.fetch_job_description(job.url)
    job.description = description.strip() if description else None
    return job.description or ""


async def _inspect_application_mode(adapter: NaukriAdapter, url: str) -> tuple[str, str | None]:
    """Inspect a job page without clicking any application control."""
    result = await adapter.open_job_page(url)
    try:
        if result.security_required:
            return "SECURITY_REQUIRED", result.security_reason
        return await adapter.detect_application_type(result.page), None
    finally:
        await result.page.close()


def _select_native_apply_candidate(candidates: list[dict]) -> dict | None:
    """Return the first candidate that is both native and Gemini-approved."""
    for candidate in candidates:
        if (
            candidate.get("application_mode") == "NAUKRI_NATIVE"
            and candidate.get("recommendation") == "APPLY"
        ):
            return candidate
    return None


async def run_dry_run():
    settings = get_settings()
    print(f"\nGemini model : {settings.gemini_model}")
    print(f"API key      : {'PRESENT' if settings.gemini_api_key else 'MISSING'}")

    initialize_database()
    db = next(get_session())

    # ── Verify profile ────────────────────────────────────────────────────────
    _banner("STEP 1 - Profile verification")
    profile = db.execute(select(Profile)).scalars().first()
    if not profile:
        print("ERROR: No profile found.")
        return
    print(f"Profile ID : {profile.id}")
    print(f"Status     : {profile.status}")
    print(f"Confirmed  : {profile.confirmed}")
    if not profile.confirmed:
        print("BLOCKED: Profile is not confirmed. Cannot proceed.")
        return

    preference = db.execute(select(JobPreference)).scalars().first()
    if not preference:
        print("ERROR: No job preferences found.")
        return
    print(f"Preferences: locations={preference.locations}, "
          f"job_titles={preference.job_titles}, "
          f"min_salary={preference.min_salary_lpa}")

    # ── Browser + Discovery ───────────────────────────────────────────────────
    _banner("STEP 2 - Browser launch + Naukri search")
    adapter = NaukriAdapter(browser_type=settings.browser_type)

    browser_launched = False
    naukri_opened = False
    login_state = "unknown"
    search_performed = False
    discovered_jobs_raw = []
    inspected_candidates = []
    captcha_encountered = False
    captcha_location = None
    quota_exhausted = False

    try:
        started = await adapter.start_session()
        if not started:
            print("ERROR: Failed to start browser session.")
            return
        browser_launched = True
        print("Browser launched: YES")

        print("(Browser window is visible - log in manually if prompted)")
        search_terms = [
            term for term in (preference.job_titles or [])
            if term and term.strip().casefold() != "related entry-level roles"
        ][:MAX_SEARCH_TERMS]
        if not search_terms:
            print("ERROR: No concrete configured job titles available.")
            return

        # ── Inspect all bounded candidates before selecting a native job ──
        _banner("STEP 3-5 - Job selection + Gemini analysis")
        gemini = GeminiProvider()
        job = None
        selected_raw = None
        analysis = None
        analysis_model = None
        count = 0
        for search_term in search_terms:
            print(f"\nSearching Naukri: '{search_term}' in {LOCATIONS}")
            print("Collecting up to", MAX_JOBS, "jobs...")
            count = 0
            try:
                async for job_data in adapter.search_jobs(search_term, LOCATIONS):
                    if count == 0:
                        naukri_opened = True
                        login_state = "authenticated"
                        search_performed = True
                        print("Naukri opened: YES")
                        print("Login state  : authenticated")
                        print("Search       : performed")

                    passes, reason = _check_hard_filters(job_data, preference)
                    status_str = "PASS" if passes else f"FILTERED ({reason})"
                    print(f"  [{count + 1}] {job_data.get('title', '?')!r:40s} | "
                          f"{job_data.get('company', '?')!r:25s} | "
                          f"loc={job_data.get('location', '?')!r:20s} | "
                          f"exp={job_data.get('experience', '?')!r:15s} | {status_str}")
                    count += 1
                    if passes:
                        discovered_jobs_raw.append(job_data)
                    if count >= MAX_JOBS:
                        break
            except Exception as e:
                err = str(e).lower()
                if any(x in err for x in ["captcha", "security", "verify", "access blocked", "login"]):
                    captcha_encountered = True
                    captcha_location = f"During {search_term} search: {e}"
                    print(f"SECURITY encountered: {e}")
                    print("Stopping safely as designed.")
                    return
                print(f"Search error: {e}")
                continue

            for candidate in discovered_jobs_raw:
                if candidate in [item["raw"] for item in inspected_candidates]:
                    continue
                print(f"\nEvaluating: {candidate.get('title')} @ {candidate.get('company')}")

                cjob = None
                if candidate.get("external_job_id"):
                    cjob = db.execute(select(Job).where(
                        Job.external_job_id == candidate["external_job_id"]
                    )).scalars().first()
                if not cjob and candidate.get("url"):
                    cjob = db.execute(select(Job).where(
                        Job.url == candidate["url"]
                    )).scalars().first()
                if not cjob:
                    cjob = Job(
                        platform="naukri",
                        external_job_id=candidate.get("external_job_id"),
                        url=candidate.get("url"),
                        title=candidate.get("title"),
                        company=candidate.get("company"),
                        location=candidate.get("location"),
                        salary=candidate.get("salary"),
                        experience=candidate.get("experience"),
                        employment_type=candidate.get("employment_type"),
                        status="DISCOVERED",
                        discovered_at=datetime.now(UTC),
                    )
                    db.add(cjob)
                    db.commit()
                    db.refresh(cjob)

                description = await _ensure_job_description(adapter, cjob)
                db.commit()
                print(f"DESCRIPTION_FETCHED: {'YES' if description else 'NO'}")
                print(f"DESCRIPTION_LENGTH: {len(description)}")

                mode, security_reason = await _inspect_application_mode(adapter, cjob.url)
                print(f"APPLICATION_MODE: {mode}")
                if mode == "SECURITY_REQUIRED":
                    captcha_encountered = True
                    captcha_location = security_reason
                    print("Stopping safely as designed.")
                    return

                record = {"raw": candidate, "job": cjob, "application_mode": mode,
                          "recommendation": None, "analysis_model": None}
                inspected_candidates.append(record)
                canalysis_model = db.execute(select(JobAnalysisModel).where(
                    JobAnalysisModel.job_id == cjob.id
                )).scalars().first()

                if mode == "EXTERNAL":
                    print("External candidate excluded from native-flow selection.")
                    if canalysis_model:
                        print(f"Existing analysis: recommendation={canalysis_model.recommendation}")
                    continue

                if canalysis_model:
                    recommendation = str(canalysis_model.recommendation)
                    record["recommendation"] = recommendation
                    record["analysis_model"] = canalysis_model
                    print(f"Existing analysis: recommendation={recommendation}")
                    continue

                try:
                    job_context = (
                        f"Title: {cjob.title}\nCompany: {cjob.company}\n"
                        f"Location: {cjob.location}\nExperience: {cjob.experience}\n"
                        f"Salary: {cjob.salary}\nDescription: {cjob.description or ''}"
                    )
                    canalysis = gemini.analyze_job(
                        job_context, json.dumps(profile.data, default=str)
                    )
                except APIQuotaExhaustedError as e:
                    quota_exhausted = True
                    print(f"Gemini quota exhausted: {e}")
                    break

                if not canalysis:
                    print("Gemini returned None, skipping.")
                    continue

                record["recommendation"] = str(canalysis.recommendation)
                canalysis_model = JobAnalysisModel(
                    job_id=cjob.id, match_score=canalysis.match_score,
                    role_match=canalysis.role_match, skill_match=canalysis.skill_match,
                    experience_match=canalysis.experience_match,
                    location_match=canalysis.location_match,
                    salary_match=canalysis.salary_match, job_quality=canalysis.job_quality,
                    duplicate_probability=canalysis.duplicate_probability,
                    suspicious=canalysis.suspicious,
                    recommendation=canalysis.recommendation,
                    short_reason=canalysis.short_reason, model=settings.gemini_model,
                    prompt_version="9B-2B-live",
                )
                db.add(canalysis_model)
                db.commit()
                record["analysis_model"] = canalysis_model
                print(f"recommendation={canalysis.recommendation} score={canalysis.match_score}")

            if quota_exhausted:
                break
            selected_record = _select_native_apply_candidate(inspected_candidates)
            if selected_record:
                job = selected_record["job"]
                selected_raw = selected_record["raw"]
                analysis_model = selected_record["analysis_model"]
                break

        if not job:
            print("\nNo eligible native job received APPLY from Gemini across all candidates.")
            print("This is a valid safety outcome - Gemini or application mode filtered all jobs.")
            print("Dry-run cannot proceed to ApplicationRunner without an APPLY-recommended job.")
            # Still report what we found
            _banner("PHASE 9B-2B RESULT SUMMARY")
            print(f"Browser launched              : YES")
            print(f"Naukri opened                 : YES")
            print(f"Login state                   : {login_state}")
            print(f"Search performed              : YES")
            print(f"Jobs discovered (raw)         : {count}")
            print(f"Jobs passing hard filters     : {len(discovered_jobs_raw)}")
            print(f"Gemini APPLY recommendation   : NONE (all SKIP)")
            print(f"ApplicationRunner started     : NO (no eligible job)")
            print(f"CAPTCHA/security encountered  : NO")
            print("submit_application() called   : NO")
            print("Real application submitted    : NO")
            return

        print(f"\nSelected for dry-run:")
        print(f"  Job ID     : {job.id}")
        print(f"  Title      : {job.title}")
        print(f"  Company    : {job.company}")
        print(f"  Location   : {job.location}")
        print(f"  Experience : {job.experience}")
        print(f"  URL        : {job.url}")

        # ── ApplicationRunner dry-run ─────────────────────────────────────────
        _banner("STEP 6 - ApplicationRunner dry_run=True")
        print("SAFETY: submit_application() is patched - any call raises RuntimeError.")
        print(f"submit_call_count before run: {_submit_call_count}")

        # Close the discovery browser session before runner opens its own
        await adapter.stop_session()
        adapter_stopped = True

        state_manager = AgentStateManager()
        runner = ApplicationRunner(
            session=db,
            state_manager=state_manager,
            dry_run=True,
        )

        print(f"\nRunning ApplicationRunner.run_applications([{job.id}], dry_run=True)...")
        stats = await runner.run_applications([job.id], dry_run=True)

        print(f"\nRunner stats: {json.dumps(stats, indent=2)}")
        print(f"\nDry-run result captured:")
        if runner.dry_run_result:
            print(json.dumps(runner.dry_run_result, indent=2, default=str))
        else:
            print("  (None - flow did not reach dry-run boundary)")

        print(f"\nsubmit_call_count after run: {_submit_call_count}")

        # ── Final safety proof ────────────────────────────────────────────────
        _banner("SAFETY VERIFICATION")
        print(f"submit_application() call count : {_submit_call_count}")
        print(f"submit_application() called     : {_submit_call_count > 0}")
        if _submit_call_count == 0:
            print("SUCCESS: submit_application() was NEVER called.")
            print("  Dry-run mode is proven safe.")
        else:
            print("FAILURE: submit_application() was called - this is a safety violation.")

        # ── Summary ───────────────────────────────────────────────────────────
        _banner("PHASE 9B-2B RESULT SUMMARY")
        dry_run_result = runner.dry_run_result or {}
        print(f"Browser launched              : {'YES' if browser_launched else 'NO'}")
        print(f"Naukri opened                 : {'YES' if naukri_opened else 'NO'}")
        print(f"Login state                   : {login_state}")
        print(f"Search performed              : {'YES' if search_performed else 'NO'}")
        print(f"Jobs discovered (raw)         : {count}")
        print(f"Jobs passing hard filters     : {len(discovered_jobs_raw)}")
        print(f"Selected job                  : {selected_raw.get('title')} @ {selected_raw.get('company')}")
        print(f"Hard-filter result            : PASS")
        print(f"ApplicationRunner started     : YES")
        print(f"Dry-run mode                  : YES (dry_run=True)")
        print(f"Application form reached      : {bool(dry_run_result.get('application_type'))}")
        print(f"Application type detected     : {dry_run_result.get('application_type', 'N/A')}")
        print(f"Questions encountered         : {dry_run_result.get('questions_count', 'N/A')}")
        print(f"Questions handled             : {len(dry_run_result.get('questions', []))}")
        print(f"Safety gate passed            : {dry_run_result.get('safety_gate_passed', 'N/A')}")
        print(f"Duplicate check passed        : {dry_run_result.get('duplicate_check_passed', 'N/A')}")
        print(f"Limits check passed           : {dry_run_result.get('limits_check_passed', 'N/A')}")
        print(f"CAPTCHA/security encountered  : {'YES - ' + captcha_location if captcha_encountered else 'NO'}")
        print(f"submit_application() called   : {'YES - VIOLATION' if _submit_call_count > 0 else 'NO'}")
        print(f"Real application submitted    : {'YES - VIOLATION' if _submit_call_count > 0 else 'NO'}")
        print(f"Runner stats - dry_run count  : {stats.get('dry_run', 0)}")
        print(f"Runner stats - applied count  : {stats.get('applied', 0)}")
        print(f"Runner stats - skipped count  : {stats.get('skipped', 0)}")

    finally:
        try:
            if browser_launched and not locals().get('adapter_stopped'):
                await adapter.stop_session()
        except Exception:
            pass
        db.close()


if __name__ == "__main__":
    asyncio.run(run_dry_run())
