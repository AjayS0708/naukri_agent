"""
Dashboard summary schemas for Checkpoint E1.

These schemas expose only safe, read-only aggregate data to the frontend.
No API keys, credentials, cookies, session data, or internal secrets are included.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DiscoverySummary(BaseModel):
    """Summary of the most recent completed discovery run."""
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[int] = None
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    jobs_discovered: int = 0
    new_jobs: int = 0
    pages_processed: int = 0
    total_runs: int = 0


class ApplicationCounts(BaseModel):
    """All-time application status counts from the database."""
    model_config = ConfigDict(extra="forbid")

    total: int = 0
    applied: int = 0
    needs_attention: int = 0
    skipped: int = 0
    external_application: int = 0
    failed: int = 0


class ProfileSummary(BaseModel):
    """Safe profile status summary — no personal data or secrets."""
    model_config = ConfigDict(extra="forbid")

    status: str = "EMPTY"
    confirmed: bool = False
    original_filename: Optional[str] = None


class DashboardSummary(BaseModel):
    """
    Top-level dashboard summary response.

    Combines discovery, application, and profile status into a single
    read-only snapshot for the frontend dashboard.
    """
    model_config = ConfigDict(extra="forbid")

    discovery: DiscoverySummary
    applications: ApplicationCounts
    profile: ProfileSummary


class RecentApplicationItem(BaseModel):
    """
    A single enriched application record for the activity feed.

    Includes job title and company from the joined Job row.
    Does not expose: API keys, cookies, session tokens, credentials,
    database internals, or confirmation_evidence raw values.
    """
    model_config = ConfigDict(extra="forbid")

    application_id: int
    job_id: int
    job_title: str
    company: str
    status: str
    application_method: Optional[str] = None
    applied_at: Optional[datetime] = None
    skip_reason: Optional[str] = None
    needs_attention: bool = False
    is_dry_run: bool = False
    created_at: datetime


class RecentApplicationsResponse(BaseModel):
    """Response wrapper for recent applications with job details."""
    model_config = ConfigDict(extra="forbid")

    applications: list[RecentApplicationItem]
    total: int


class NeedsAttentionItem(BaseModel):
    """
    A single application that requires user attention.

    Includes job title, company, and the reason for attention.
    Does not expose: API keys, cookies, session tokens, credentials,
    or internal browser data.
    """
    model_config = ConfigDict(extra="forbid")

    application_id: int
    job_id: int
    job_title: str
    company: str
    status: str
    skip_reason: Optional[str] = None
    failure_reason: Optional[str] = None
    needs_attention: bool = True
    created_at: datetime


class NeedsAttentionResponse(BaseModel):
    """Response wrapper for needs-attention applications."""
    model_config = ConfigDict(extra="forbid")

    applications: list[NeedsAttentionItem]
    total: int
