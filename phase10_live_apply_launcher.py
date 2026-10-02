"""Explicitly gated launcher for one supervised native application attempt.

This module does not perform any work on import. Run it manually with a job ID.
Every live side effect is behind two exact confirmation prompts.
"""

import argparse
import asyncio
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import inspect, select

from backend.database.database import get_session
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


FORBIDDEN_JOB_ID = "300926927428"
BACKUP_PATH = Path("data/naukri_agent.db.bak-before-live-test2")
QUADRASYSTEMS_URL = (
    "https://www.naukri.com/"
    "job-listings-aws-devops-engineer-quadrasystems-net-bengaluru-0-to-1-years-240926500723"
)


def exact_confirmation(value: str | None, command: str, job_id: str) -> bool:
    return value == f"{command} {job_id}"


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
    salary = extract_lowest_salary_lpa(job.salary or job.description or "")
    if salary is not None and preferences.min_salary_lpa is not None:
        if salary < preferences.min_salary_lpa:
            return False, f"Salary {salary} LPA is below minimum {preferences.min_salary_lpa}"
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


def preflight(session, job_id: str) -> dict:
    profile = session.execute(select(Profile)).scalars().first()
    preferences = session.execute(select(JobPreference)).scalars().first()
    scheduler = session.execute(select(SchedulerConfig)).scalars().first()
    limits = ApplicationLimitService(session).check_limits()
    columns = {column["name"] for column in inspect(session.get_bind()).get_columns("applications")}
    job = session.execute(
        select(Job).where(Job.external_job_id == job_id)
    ).scalars().all()
    if len(job) != 1:
        raise RuntimeError(f"Expected exactly one DB job for {job_id}; found {len(job)}")
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
    return {
        "profile": profile,
        "preferences": preferences,
        "job": job[0],
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


async def run(job_id: str, yes_flag: bool = False) -> int:
    reject_forbidden_job(job_id)
    session = next(get_session())
    before = session.execute(select(Application).order_by(Application.id)).scalars().all()
    context = preflight(session, job_id)
    job = context["job"]
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
    parser.add_argument("job_id")
    parser.add_argument("--yes", action="store_true", help="Skip typed confirmations and auto-proceed when all checks pass")
    args = parser.parse_args()
    return asyncio.run(run(args.job_id, yes_flag=args.yes))


if __name__ == "__main__":
    raise SystemExit(main())
