"""
Dashboard read-only API routes for Checkpoint E1.

All endpoints are GET only. No mutations to database state are performed.
No API keys, credentials, or internal secrets are exposed in any response.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.models.application import Application
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.profile import Profile, Resume
from backend.schemas.dashboard import (
    ApplicationCounts,
    DashboardSummary,
    DiscoverySummary,
    ProfileSummary,
    RecentApplicationItem,
    RecentApplicationsResponse,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _get_discovery_summary(db: Session) -> DiscoverySummary:
    """
    Return stats from the most recent COMPLETED discovery run, plus a total run count.
    Falls back to zero/None values if no run exists yet.
    """
    total_runs: int = db.execute(select(func.count(DiscoveryRun.id))).scalar() or 0

    # Latest run by started_at (any terminal status)
    latest_run = db.execute(
        select(DiscoveryRun)
        .where(DiscoveryRun.status.in_(["COMPLETED", "FAILED", "STOPPED",
                                        "AUTH_REQUIRED", "SECURITY_REQUIRED"]))
        .order_by(DiscoveryRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if latest_run is None:
        # No completed run — show all-time totals from all runs
        jobs_discovered: int = db.execute(select(func.count(Job.id))).scalar() or 0
        return DiscoverySummary(
            run_id=None,
            status=None,
            started_at=None,
            completed_at=None,
            jobs_discovered=jobs_discovered,
            new_jobs=0,
            pages_processed=0,
            total_runs=total_runs,
        )

    return DiscoverySummary(
        run_id=latest_run.id,
        status=latest_run.status,
        started_at=latest_run.started_at,
        completed_at=latest_run.completed_at,
        jobs_discovered=latest_run.jobs_discovered,
        new_jobs=latest_run.new_jobs,
        pages_processed=latest_run.pages_processed,
        total_runs=total_runs,
    )


def _get_application_counts(db: Session) -> ApplicationCounts:
    """
    Return all-time application status counts.
    Uses direct COUNT queries per status to avoid loading all rows.
    """
    def count_status(status: str) -> int:
        return db.execute(
            select(func.count(Application.id)).where(Application.status == status)
        ).scalar() or 0

    total: int = db.execute(select(func.count(Application.id))).scalar() or 0
    applied = count_status("APPLIED") + count_status("SUBMITTED")
    needs_attention = count_status("NEEDS_ATTENTION")
    skipped = count_status("SKIPPED")
    external_application = count_status("EXTERNAL_APPLICATION")
    failed = count_status("FAILED") + count_status("APPLICATION_STARTED")

    return ApplicationCounts(
        total=total,
        applied=applied,
        needs_attention=needs_attention,
        skipped=skipped,
        external_application=external_application,
        failed=failed,
    )


def _get_profile_summary(db: Session) -> ProfileSummary:
    """
    Return a safe profile status summary.
    Exposes status, confirmed flag, and original filename only.
    Never exposes: resume_hash, profile data fields, API keys, credentials.
    """
    resume = db.execute(
        select(Resume)
        .where(Resume.is_current.is_(True))
        .order_by(Resume.uploaded_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if resume is None:
        return ProfileSummary(status="EMPTY", confirmed=False, original_filename=None)

    profile = db.execute(
        select(Profile).where(Profile.resume_id == resume.id)
    ).scalar_one_or_none()

    if profile is None:
        return ProfileSummary(status="EMPTY", confirmed=False, original_filename=None)

    return ProfileSummary(
        status=profile.status,
        confirmed=bool(profile.confirmed),
        original_filename=resume.original_filename,
    )


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummary:
    """
    Return a read-only snapshot of the agent's current state for the dashboard.

    Combines:
    - Latest discovery run statistics
    - All-time application status counts
    - Safe profile/configuration status (no secrets)

    This endpoint is read-only. It performs no mutations.
    """
    return DashboardSummary(
        discovery=_get_discovery_summary(db),
        applications=_get_application_counts(db),
        profile=_get_profile_summary(db),
    )


@router.get("/recent-applications", response_model=RecentApplicationsResponse)
def get_recent_applications(
    limit: int = 10,
    db: Session = Depends(get_db),
) -> RecentApplicationsResponse:
    """
    Return recent application records enriched with job title and company.

    Joins Application with Job so the frontend can display meaningful labels
    without making a separate request per application.

    Limit is capped at 50 to prevent large payloads.
    This endpoint is read-only. It performs no mutations.
    """
    if limit > 50:
        limit = 50
    if limit < 1:
        limit = 1

    rows = db.execute(
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .order_by(Application.created_at.desc())
        .limit(limit)
    ).all()

    items = [
        RecentApplicationItem(
            application_id=app.id,
            job_id=app.job_id,
            job_title=job.title,
            company=job.company,
            status=app.status,
            application_method=app.application_method,
            applied_at=app.applied_at,
            skip_reason=app.skip_reason,
            needs_attention=app.needs_attention,
            is_dry_run=app.is_dry_run,
            created_at=app.created_at,
        )
        for app, job in rows
    ]

    return RecentApplicationsResponse(applications=items, total=len(items))
