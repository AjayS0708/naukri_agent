"""Explicitly gated launcher for one supervised native application attempt.

This module does not perform any work on import. Run it manually with a job ID or URL.
Every live side effect is behind two exact confirmation prompts (or --yes flag).
"""

import argparse
import asyncio
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse, parse_qs

from sqlalchemy import inspect, select

from backend.database.database import get_session, SessionLocal
from backend.models.ai import JobAnalysisModel
from backend.models.application import Application
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile
from backend.models.scheduler import SchedulerConfig
from backend.schemas.ai import AIRecommendation, JobAnalysis
from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.services.applications.limits import ApplicationLimitService
from backend.services.applications.runner import ApplicationRunner
from backend.services.applications.service import ApplicationService
from backend.services.gemini.provider import APIQuotaExhaustedError, GeminiProvider
from backend.services.matching.normalizer import (
    compute_profile_experience_years,
    extract_experience_years,
    extract_lowest_salary_lpa,
    has_overlapping_location,
    is_employment_type_allowed,
)
from backend.services.naukri.adapter import NaukriAdapter
from backend.core.logging import get_logger

logger = get_logger(__name__)


FORBIDDEN_JOB_ID = "300926927428"
BACKUP_PATH = Path("data/naukri_agent.db.bak-before-launcher-url")
QUADRASYSTEMS_URL = (
    "https://www.naukri.com/"
    "job-listings-aws-devops-engineer-quadrasystems-net-bengaluru-0-to-1-years-240926500723"
)


def validate_naukri_url(url: str) -> Optional[str]:
    """Validate Naukri job URL and extract job ID.

    Returns the external job ID (10-15 trailing digits) if valid, None otherwise.
    Must be: https, naukri.com domain, /job-listing(s)- in path, trailing 10-15 digit ID.
    """
    try:
        parsed = urlparse(url)
        # Check HTTPS
        if parsed.scheme != "https":
            return None
        # Check domain
        if "naukri.com" not in parsed.netloc:
            return None
        # Check path pattern: /job-listing- or /job-listings-
        if "/job-listing" not in parsed.path or "-" not in parsed.path:
            return None
        # Extract trailing digits (job ID): last segment after final dash
        parts = parsed.path.rstrip("/").split("-")
        if parts and parts[-1].isdigit() and 10 <= len(parts[-1]) <= 15:
            return parts[-1]
    except Exception:
        pass
    return None


def exact_confirmation(value: str | None, command: str, job_id: str) -> bool:
    return value == f"{command} {job_id}"


def reject_forbidden_job(job_id: str) -> None:
    if job_id == FORBIDDEN_JOB_ID:
        raise RuntimeError("Refusing forbidden S&P Global job 300926927428")


async def ingest_job_from_url(adapter: NaukriAdapter, url: str, session) -> Optional[Job]:
    """Ingest a job by opening its URL directly.

    - Opens only the job URL (never homepage)
    - Waits up to 20s for rendered signal (h1 header or JSON-LD script)
    - Reads DOM up to 3 times with no reloads
    - Extracts: title, company, location, experience, salary, employment_type, description
    - Priority: visible header → JSON-LD → og: meta tags
    - Never uses URL slug as value
    - Treats "Unpaid" as 0 (disclosed), "Not disclosed"/"" as null
    - Aborts with diagnostics (screenshot, HTML) if required fields missing or description empty

    Returns the ingested Job if successful, None if aborted.
    """
    page = None
    try:
        # Open job page directly
        result = await adapter.open_job_page(url)
        page = result.page
        if result.security_required:
            print(f"INGEST_ABORT: Security required: {result.security_reason}")
            return None

        # Wait for rendered signal: h1 or JSON-LD script (max 20s)
        rendered = False
        start_time = datetime.now(UTC)
        while (datetime.now(UTC) - start_time).total_seconds() < 20:
            h1_text = await page.query_selector("h1")
            if h1_text:
                rendered = True
                break
            ld_json = await page.query_selector('script[type="application/ld+json"]')
            if ld_json:
                rendered = True
                break
            await asyncio.sleep(1)

        if not rendered:
            print(f"INGEST_ABORT: Page did not render within 20s")
            await _capture_ingest_diagnostics(page, url, "timeout_no_render")
            return None

        # Try reading DOM up to 3 times (no reloads)
        title = None
        company = None
        location = None
        experience = None
        salary = None
        employment_type = None
        description = None

        for attempt in range(3):
            if attempt > 0:
                await asyncio.sleep(2)

            # Extract title
            if not title:
                title = await _extract_title_from_page(page)
            # Extract company
            if not company:
                company = await _extract_company_from_page(page)
            # Extract location
            if not location:
                location = await _extract_location_from_page(page)
            # Extract experience
            if not experience:
                experience = await _extract_experience_from_page(page)
            # Extract salary
            if not salary:
                salary = await _extract_salary_from_page(page)
            # Extract employment type
            if not employment_type:
                employment_type = await _extract_employment_type_from_page(page)
            # Extract description
            if not description:
                description = await _extract_description_from_page(page)

            # If all required fields filled, break early
            if title and company and location and description:
                break

        # Validate required fields and build list of missing ones
        missing_required = []
        if not title:
            missing_required.append("title")
        if not company:
            missing_required.append("company")
        if not location:
            missing_required.append("location")

        if missing_required:
            print(f"INGEST_ABORT: Missing required fields: {', '.join(missing_required)}")
            await _capture_ingest_diagnostics(page, url, "missing_required_fields", title, company, location, missing_required)
            return None

        if not description or not description.strip():
            print(f"INGEST_ABORT: Description is empty")
            await _capture_ingest_diagnostics(page, url, "empty_description", title, company, location, ["description"])
            return None

        # Handle salary: "Unpaid" becomes 0, "Not disclosed" or empty stays null
        salary_min = None
        salary_max = None
        if salary:
            salary_lower = salary.lower().strip()
            if salary_lower == "unpaid":
                salary_min = 0
                salary_max = 0
                salary = "Unpaid"  # Store as-is
            elif salary_lower not in ("not disclosed", ""):
                # Try to parse numeric salary
                sal_min = extract_lowest_salary_lpa(salary)
                if sal_min is not None:
                    salary_min = sal_min

        # Extract job ID from URL
        job_id = validate_naukri_url(url)
        if not job_id:
            print(f"INGEST_ABORT: Could not extract job ID from URL")
            return None

        # Check if job already exists
        existing = session.execute(
            select(Job).where(Job.external_job_id == job_id)
        ).scalars().first()
        if existing:
            print(f"INGEST_REUSE: Job {job_id} already in database")
            return existing

        # Check forbidden job ID
        if job_id == FORBIDDEN_JOB_ID:
            print(f"INGEST_ABORT: Forbidden job ID {FORBIDDEN_JOB_ID}")
            return None

        # Normalize experience fields
        exp_min = None
        exp_max = None
        if experience:
            exp_min, exp_max = extract_experience_years(experience)

        # Create and return new Job record (do not persist yet)
        job = Job(
            platform="naukri",
            external_job_id=job_id,
            url=url,
            title=title.strip(),
            company=company.strip(),
            description=description.strip(),
            location=location.strip(),
            salary=salary,
            salary_min=salary_min,
            salary_max=salary_max,
            experience=experience,
            experience_min=exp_min,
            experience_max=exp_max,
            employment_type=employment_type.strip() if employment_type else None,
            source="launcher_url",
            status="DISCOVERED",
            discovered_at=datetime.now(UTC),
        )
        return job

    except Exception as e:
        print(f"INGEST_ERROR: {e}")
        if page:
            await _capture_ingest_diagnostics(page, url, f"exception_{type(e).__name__}")
        return None
    finally:
        if page and not page.is_closed():
            await page.close()


async def _extract_title_from_page(page) -> Optional[str]:
    """Extract title: visible h1 → JSON-LD title → og:title."""
    try:
        # Try h1
        h1 = await page.query_selector("h1")
        if h1:
            text = await h1.text_content()
            if text and text.strip():
                return text.strip()
    except Exception:
        pass
    try:
        # Try JSON-LD
        ld_json = await page.query_selector('script[type="application/ld+json"]')
        if ld_json:
            text = await ld_json.text_content()
            data = json.loads(text)
            if isinstance(data, dict) and "title" in data:
                return data["title"].strip()
    except Exception:
        pass
    try:
        # Try og:title
        og = await page.query_selector('meta[property="og:title"]')
        if og:
            content = await og.get_attribute("content")
            if content and content.strip():
                return content.strip()
    except Exception:
        pass
    return None


async def _extract_company_from_page(page) -> Optional[str]:
    """Extract company: visible text under title → JSON-LD → og: meta."""
    try:
        # Try visible company name text (often right after h1, in a link or div)
        elements = await page.query_selector_all('[class*="company"], [class*="Company"]')
        for elem in elements:
            text = await elem.text_content()
            if text and text.strip() and len(text.strip()) > 2 and len(text.strip()) < 200:
                return text.strip()
    except Exception:
        pass
    try:
        # Try JSON-LD JobPosting hiringOrganization
        ld_json = await page.query_selector('script[type="application/ld+json"]')
        if ld_json:
            text = await ld_json.text_content()
            data = json.loads(text)
            if isinstance(data, dict):
                if "hiringOrganization" in data:
                    org = data["hiringOrganization"]
                    if isinstance(org, dict) and "name" in org:
                        return org["name"].strip()
                    elif isinstance(org, str):
                        return org.strip()
    except Exception:
        pass
    try:
        # Try og:company or similar
        og = await page.query_selector('meta[property*="company"], meta[name*="company"]')
        if og:
            content = await og.get_attribute("content")
            if content and content.strip():
                return content.strip()
    except Exception:
        pass
    return None


async def _extract_location_from_page(page) -> Optional[str]:
    """Extract location: visible chip/badge → JSON-LD."""
    try:
        # Try visible location chip (often in a .chip or .badge element)
        elements = await page.query_selector_all('[class*="chip"], [class*="badge"]')
        for elem in elements:
            text = await elem.text_content()
            if text and text.strip() and len(text.strip()) < 100:
                # Filter out common non-location text
                lower_text = text.strip().lower()
                if any(word in lower_text for word in ['year', 'salary', 'urgent', 'apply']):
                    continue
                return text.strip()
    except Exception:
        pass
    try:
        # Try JSON-LD JobPosting jobLocation
        ld_json = await page.query_selector('script[type="application/ld+json"]')
        if ld_json:
            text = await ld_json.text_content()
            data = json.loads(text)
            if isinstance(data, dict) and "jobLocation" in data:
                loc = data["jobLocation"]
                if isinstance(loc, dict) and "address" in loc:
                    addr = loc["address"]
                    if isinstance(addr, dict) and "addressLocality" in addr:
                        return addr["addressLocality"].strip()
    except Exception:
        pass
    return None


async def _extract_experience_from_page(page) -> Optional[str]:
    """Extract experience: visible chip → JSON-LD."""
    try:
        # Try visible experience text (look for "Xyr" or "X-Y years" pattern)
        body_text = await page.evaluate("() => document.body.innerText")
        exp_match = re.search(r'(\d+)\s*yr(?:s)?(?:\s*[-–]\s*(\d+)\s*yr(?:s)?)?', body_text, re.IGNORECASE)
        if exp_match:
            return exp_match.group(0)
    except Exception:
        pass
    try:
        # Try JSON-LD
        ld_json = await page.query_selector('script[type="application/ld+json"]')
        if ld_json:
            text = await ld_json.text_content()
            data = json.loads(text)
            if isinstance(data, dict):
                if "experienceRequirements" in data:
                    exp = data["experienceRequirements"]
                    if isinstance(exp, dict) and "description" in exp:
                        return exp["description"].strip()
                    elif isinstance(exp, str):
                        return exp.strip()
    except Exception:
        pass
    return None


async def _extract_salary_from_page(page) -> Optional[str]:
    """Extract salary: visible text → JSON-LD → og: meta.
    Returns "Unpaid" for unpaid positions, None for "Not disclosed" or empty."""
    try:
        # Try visible salary text (look for LPA, currency, or "Unpaid")
        body_text = await page.evaluate("() => document.body.innerText")
        # Check for Unpaid
        if re.search(r'\bUnpaid\b', body_text):
            return "Unpaid"
        # Check for salary ranges
        sal_match = re.search(r'([0-9.,]+(?:\s*[-–]\s*[0-9.,]+)?)\s*(?:LPA|lpa|INR|₹)', body_text)
        if sal_match:
            return sal_match.group(0)
    except Exception:
        pass
    try:
        # Try JSON-LD baseSalary
        ld_json = await page.query_selector('script[type="application/ld+json"]')
        if ld_json:
            text = await ld_json.text_content()
            data = json.loads(text)
            if isinstance(data, dict) and "baseSalary" in data:
                sal = data["baseSalary"]
                if isinstance(sal, dict):
                    if "currency" in sal and "value" in sal:
                        val = sal["value"]
                        if isinstance(val, dict) and "minValue" in val:
                            return str(val["minValue"]).strip()
                        elif isinstance(val, (int, float)):
                            return str(val).strip()
    except Exception:
        pass
    return None


async def _extract_employment_type_from_page(page) -> Optional[str]:
    """Extract employment type: visible chip/text → JSON-LD."""
    try:
        # Try visible employment type (look for "Full Time", "Internship", etc in chips)
        body_text = await page.evaluate("() => document.body.innerText")
        emp_types = ['Full Time', 'Part Time', 'Contract', 'Temporary', 'Freelance', 'Internship']
        for emp_type in emp_types:
            if emp_type in body_text:
                return emp_type
    except Exception:
        pass
    try:
        # Try JSON-LD employmentType
        ld_json = await page.query_selector('script[type="application/ld+json"]')
        if ld_json:
            text = await ld_json.text_content()
            data = json.loads(text)
            if isinstance(data, dict) and "employmentType" in data:
                emp = data["employmentType"]
                if isinstance(emp, list):
                    emp = emp[0] if emp else None
                if emp and isinstance(emp, str):
                    return emp.strip()
    except Exception:
        pass
    return None


async def _extract_description_from_page(page) -> Optional[str]:
    """Extract description: visible "About the job" section → JSON-LD."""
    try:
        # Try visible description (look for "About the job" section)
        html = await page.content()
        desc_match = re.search(r'(?:About\s+the\s+job|Job\s+Description)[^<]*</?\w+>[^<]{1,500}', html, re.IGNORECASE)
        if desc_match:
            # Strip HTML tags
            desc_text = re.sub(r'<[^>]+>', '', desc_match.group(0))
            desc_text = desc_text.strip()
            if desc_text and len(desc_text) > 10:
                return desc_text
    except Exception:
        pass
    try:
        # Try JSON-LD description
        ld_json = await page.query_selector('script[type="application/ld+json"]')
        if ld_json:
            text = await ld_json.text_content()
            data = json.loads(text)
            if isinstance(data, dict) and "description" in data:
                desc = data["description"]
                if isinstance(desc, str):
                    return desc.strip()
    except Exception:
        pass
    return None


async def _capture_ingest_diagnostics(page, url: str, reason: str, title: Optional[str] = None, company: Optional[str] = None, location: Optional[str] = None, missing_fields: Optional[list] = None) -> None:
    """Capture screenshot, HTML, and print diagnostics for failed ingest."""
    try:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"data/ingest_abort_{reason}_{timestamp}.png"
        html_path = f"data/ingest_abort_{reason}_{timestamp}.html"

        # Capture screenshot
        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"   Screenshot: {screenshot_path}")
        except Exception as e:
            print(f"   Screenshot failed: {e}")

        # Capture HTML
        try:
            content = await page.content()
            Path(html_path).write_text(content, encoding="utf-8")
            print(f"   HTML saved: {html_path}")
        except Exception as e:
            print(f"   HTML capture failed: {e}")

        # Print diagnostics
        print(f"   URL: {url}")
        if missing_fields:
            print(f"   Missing required fields: {', '.join(missing_fields)}")
        else:
            print(f"   Title: {'FOUND' if title else 'MISSING'}")
            print(f"   Company: {'FOUND' if company else 'MISSING'}")
            print(f"   Location: {'FOUND' if location else 'MISSING'}")

        # Print first 300 chars of visible text
        try:
            visible_text = await page.evaluate("() => document.body.innerText")
            visible_preview = visible_text[:300] if visible_text else ""
            print(f"   Body length: {len(visible_text or '')}")
            print(f"   First 300 chars: {visible_preview}")
        except Exception:
            pass

    except Exception as e:
        print(f"   Diagnostics capture failed: {e}")


def reject_forbidden_job(job_id: str) -> None:
    if job_id == FORBIDDEN_JOB_ID:
        raise RuntimeError("Refusing forbidden S&P Global job 300926927428")


def backup_database(
    source: Path = Path("data/naukri_agent.db"),
    destination: Path = BACKUP_PATH,
    copier: Callable[[str, str], str] = shutil.copy2,
) -> Path:
    """Create the required backup, raising before any write if it fails."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        copier(str(source), str(destination))
    except Exception as exc:
        raise RuntimeError(f"Database backup failed: {exc}") from exc
    if not destination.is_file():
        raise RuntimeError("Database backup failed: destination was not created")
    return destination


def _job_analysis(model: JobAnalysisModel) -> JobAnalysis:
    return JobAnalysis(
        match_score=model.match_score,
        role_match=model.role_match,
        skill_match=model.skill_match,
        experience_match=model.experience_match,
        location_match=model.location_match,
        salary_match=model.salary_match,
        job_quality=model.job_quality,
        duplicate_probability=model.duplicate_probability,
        suspicious=model.suspicious,
        recommendation=model.recommendation,
        short_reason=model.short_reason,
    )


def deterministic_check(job: Job, profile: Profile, preferences: JobPreference, session) -> tuple[bool, str]:
    if not profile.confirmed:
        return False, "Profile is not confirmed"
    if preferences.job_titles and not any(
        title.lower() in job.title.lower() for title in preferences.job_titles
    ):
        return False, f"Job title '{job.title}' is outside configured scope"
    if job.location and preferences.locations and not has_overlapping_location(
        job.location, preferences.locations
    ):
        return False, f"Location mismatch: {job.location}"
    experience_source = job.experience or job.description or ""
    minimum_experience, _ = extract_experience_years(experience_source)
    profile_years = compute_profile_experience_years(
        profile.data.get("experience", []) if isinstance(profile.data, dict) else []
    )
    if minimum_experience is not None and minimum_experience > profile_years + 2:
        return False, (
            f"Experience {minimum_experience} exceeds {profile_years} "
            "(including +2 year tolerance)"
        )
    # Salary filter: treat salary_max==0 (disclosed unpaid) as below minimum
    # salary NULL/None (undisclosed) is NOT rejected
    if job.salary_max == 0:
        # Disclosed zero pay (unpaid) - always reject
        return False, "Salary is unpaid (disclosed 0 LPA)"
    salary = extract_lowest_salary_lpa(job.salary or job.description or "")
    if salary is not None and preferences.min_salary_lpa is not None:
        if salary < preferences.min_salary_lpa:
            return False, f"Salary {salary} LPA is below minimum {preferences.min_salary_lpa}"
    # Note: salary NULL (undisclosed) does not trigger rejection
    if job.employment_type and preferences.employment_types:
        if not is_employment_type_allowed(job.employment_type, preferences.employment_types):
            return False, f"Employment type '{job.employment_type}' is not allowed"
    if not job.company.strip():
        return False, "Employer is not identifiable"
    if not (job.description or "").strip():
        return False, "Job description is empty"
    existing = session.execute(
        select(Application).where(Application.job_id == job.id)
    ).scalars().all()
    if any(a.status in {"APPLIED", "SUBMITTED"} for a in existing):
        return False, "APPLIED/SUBMITTED duplicate exists"
    if any(a.status in {"EXTERNAL_APPLICATION", "NEEDS_ATTENTION"} for a in existing):
        return False, "Unresolved prior attempt exists"
    return True, (
        f"PASS; experience={job.experience!r}, profile_years={profile_years}, "
        f"tolerance=+2, salary={job.salary!r}, location={job.location!r}, "
        f"employment_type={job.employment_type!r}"
    )


def preflight(session, job_id: Optional[str] = None) -> dict:
    """Preflight checks for profile, preferences, scheduler, and limits.

    If job_id is provided, validates that it exists in DB.
    Does not require job_id for URL-based ingest (job will be ingested in-process).
    """
    profile = session.execute(select(Profile)).scalars().first()
    preferences = session.execute(select(JobPreference)).scalars().first()
    scheduler = session.execute(select(SchedulerConfig)).scalars().first()
    limits = ApplicationLimitService(session).check_limits()
    columns = {column["name"] for column in inspect(session.get_bind()).get_columns("applications")}

    if not profile or not profile.confirmed:
        raise RuntimeError("Confirmed profile is required")
    if not preferences:
        raise RuntimeError("Job preferences are required")
    if scheduler and scheduler.is_running:
        raise RuntimeError("Scheduler must be stopped")
    if not limits.allowed:
        raise RuntimeError(f"Application limit blocked: {limits.reason}")
    if "confirmation_evidence" not in columns:
        raise RuntimeError("applications.confirmation_evidence column is missing")

    # Lookup job only if job_id provided (not for URL-based ingest)
    job = None
    if job_id:
        job = session.execute(
            select(Job).where(Job.external_job_id == job_id)
        ).scalars().all()
        if len(job) != 1:
            raise RuntimeError(f"Expected exactly one DB job for {job_id}; found {len(job)}")
        job = job[0]

    return {
        "profile": profile,
        "preferences": preferences,
        "job": job,
        "limits": limits,
        "profile_years": compute_profile_experience_years(
            profile.data.get("experience", []) if isinstance(profile.data, dict) else []
        ),
        "anz_experience": any(
            "anz" in str(item).lower()
            for item in (profile.data.get("experience", []) if isinstance(profile.data, dict) else [])
        ),
    }


async def classify_twice(adapter: NaukriAdapter, page) -> tuple[str, str]:
    first = await adapter.detect_application_type(page)
    await asyncio.sleep(3)
    second = await adapter.detect_application_type(page)
    return first, second


async def run(job_id: Optional[str] = None, url: Optional[str] = None, yes_flag: bool = False) -> int:
    """Run supervised application for a job by ID or URL.

    If url is provided, ingest the job in-process first.
    If job_id is provided, use existing DB record.
    """
    # Validate inputs
    if not job_id and not url:
        print("ERROR: Either job_id or --url required")
        return 1

    if job_id and url:
        print("ERROR: Cannot specify both job_id and --url")
        return 1

    # For URL mode: validate, ingest, and set job_id
    if url:
        validated_job_id = validate_naukri_url(url)
        if not validated_job_id:
            print(f"INVALID_URL: Not a valid Naukri job URL")
            return 1
        # Check forbidden ID early
        if validated_job_id == FORBIDDEN_JOB_ID:
            raise RuntimeError("Refusing forbidden S&P Global job 300926927428")
        job_id = validated_job_id
    else:
        # For job_id mode: check forbidden ID
        reject_forbidden_job(job_id)

    session = next(get_session())
    before = session.execute(select(Application).order_by(Application.id)).scalars().all()

    # Preflight without job_id if URL mode (job will be ingested first)
    context = preflight(session, job_id if not url else None)

    # For URL mode: ingest job before preflight
    if url:
        adapter = NaukriAdapter()
        try:
            if not await adapter.start_session():
                print("AUTH_REQUIRED: browser session could not start")
                return 2
            ingested_job = await ingest_job_from_url(adapter, url, session)
            await adapter.stop_session()
            if not ingested_job:
                print("INGEST_FAILED: Could not ingest job from URL")
                return 1
            # If job already existed, it was returned from DB; if new, persist it
            if ingested_job.id is None:
                backup_database()
                session.add(ingested_job)
                session.commit()
            job = ingested_job
            print(f"INGEST_SUCCESS: Job {job_id} ingested/reused")
        except Exception as e:
            print(f"INGEST_ERROR: {e}")
            return 1
        finally:
            await adapter.stop_session()
    else:
        job = context["job"]
        if not job:
            print(f"ERROR: Job {job_id} not found in database")
            return 1

    print("PREFLIGHT", {
        "applications": len(before),
        "applied": sum(a.status == "APPLIED" for a in before),
        "submitted": sum(a.status == "SUBMITTED" for a in before),
        "profile_years": context["profile_years"],
        "anz_apprenticeship_in_experience": context["anz_experience"],
        "scheduler_stopped": not bool(
            session.execute(select(SchedulerConfig)).scalars().first()
            and session.execute(select(SchedulerConfig)).scalars().first().is_running
        ),
        "limits_allow": context["limits"].allowed,
    })
    adapter = NaukriAdapter()
    page = None
    try:
        if not await adapter.start_session():
            print("AUTH_REQUIRED: browser session could not start")
            return 2
        result = await adapter.open_job_page(job.url or QUADRASYSTEMS_URL)
        page = result.page
        if result.security_required:
            print("SECURITY_REQUIRED:", result.security_reason)
            return 3
        await adapter._check_security(page)
        fetched_description = None
        if not job.description:
            fetched_description = await adapter.fetch_job_description(job.url)
            # The job description assignment may be flushed by a later query,
            # so establish the required backup before mutating the ORM object.
            backup_database()
            job.description = fetched_description
        allowed, reason = deterministic_check(job, context["profile"], context["preferences"], session)
        print("DETERMINISTIC", {"allowed": allowed, "reason": reason})
        if not allowed:
            return 4
        analysis = GeminiProvider().analyze_job(
            f"Title: {job.title}\nCompany: {job.company}\nDescription: {job.description}",
            str(context["profile"].data),
        )
        if not analysis or analysis.recommendation != AIRecommendation.APPLY or analysis.suspicious:
            print("BLOCKED_BY_GEMINI", analysis.model_dump() if analysis else None)
            return 5
        # The analysis persistence below is safe because the backup already
        # exists; reuse the backup if the description was already persisted.
        if fetched_description is None:
            backup_database()
        session.add(JobAnalysisModel(
            job_id=job.id, match_score=analysis.match_score,
            role_match=analysis.role_match, skill_match=analysis.skill_match,
            experience_match=analysis.experience_match, location_match=analysis.location_match,
            salary_match=analysis.salary_match, job_quality=analysis.job_quality,
            duplicate_probability=analysis.duplicate_probability, suspicious=analysis.suspicious,
            recommendation=analysis.recommendation, short_reason=analysis.short_reason,
            model=getattr(GeminiProvider, "provider_name", "gemini"),
            prompt_version="phase10-live-launcher",
        ))
        session.commit()
        if not ApplicationService(session).run_final_safety_gate(
            job, context["profile"], context["preferences"], analysis
        )[0]:
            print("BLOCKED_BY_SAFETY_GATE")
            return 6

        # PROCEED confirmation: skip with --yes, prompt without
        if yes_flag:
            print("AUTO_PROCEED: --yes flag set, skipping typed confirmation")
        else:
            if not exact_confirmation(input(f"Type PROCEED {job_id}: "), "PROCEED", job_id):
                print("ABORTED: confirmation mismatch")
                return 7

        first, second = await classify_twice(adapter, page)
        print("PRE_CLICK_CLASSIFICATION", {"first": first, "second": second})
        if first != "NAUKRI_NATIVE" or second != "NAUKRI_NATIVE":
            print("ABORTED: native classification was not stable")
            return 8
        await page.screenshot(path="data/phase10_live_pre_click.png", full_page=True)
        print("Clicking Apply submits my existing Naukri profile and resume immediately; no question answers are prepared.")

        # SUBMIT confirmation: skip with --yes, prompt without
        if yes_flag:
            print("AUTO_SUBMIT: --yes flag set, skipping typed confirmation")
        else:
            if not exact_confirmation(input(f"Type SUBMIT {job_id}: "), "SUBMIT", job_id):
                print("ABORTED: confirmation mismatch")
                return 9

        state = AgentStateManager(initial_state=AgentState.IDLE)
        runner = ApplicationRunner(
            session,
            state,
            dry_run=False,
            supervise_form=True,
        )
        result_code = await runner.run_applications([job.id], dry_run=False)
        print("RUNNER_RESULT", result_code)
        return 0
    except APIQuotaExhaustedError:
        print("GEMINI_QUOTA_EXHAUSTED")
        return 10
    finally:
        if page and not page.is_closed():
            await page.close()
        await adapter.stop_session()
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id", nargs="?", default=None, help="Job ID from database")
    parser.add_argument("--url", type=str, help="Naukri job URL to ingest and apply")
    parser.add_argument("--yes", action="store_true", help="Skip typed confirmations and auto-proceed when all checks pass")
    args = parser.parse_args()

    if not args.job_id and not args.url:
        parser.print_help()
        return 1

    return asyncio.run(run(job_id=args.job_id, url=args.url, yes_flag=args.yes))


if __name__ == "__main__":
    raise SystemExit(main())
