"""Manual apply queue API schemas (E5-R29).

The operator applies to previously discovered jobs without running the
discovery sweep. Selection is explicit; every safety rule (protection,
relevance, hard filters, external boundary, evidence verification) is
enforced by the same code paths the autonomous cycle uses.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ManualApplyEligibleItem(BaseModel):
    """One previously discovered job with its eligibility verdict."""

    model_config = ConfigDict(extra="forbid")

    job_id: int
    title: str
    company: str
    location: Optional[str] = None
    experience: Optional[str] = None
    application_mode: Optional[str] = None
    discovered_at: Optional[datetime] = None
    application_status: Optional[str] = None
    eligible: bool
    exclusion_reason: Optional[str] = None


class ManualApplyEligibleResponse(BaseModel):
    """Eligibility listing for the Apply to Discovered Jobs queue."""

    model_config = ConfigDict(extra="forbid")

    items: list[ManualApplyEligibleItem]
    total: int
    eligible_count: int
    # E5-R30: every eligible id of the (search-matched) set, not just the
    # current page, so "Apply to all eligible" is not limited to a page.
    eligible_job_ids: list[int] = []
    profile_confirmed: bool
    preferences_present: bool


class ManualApplyStartRequest(BaseModel):
    """Start a manual apply run over explicitly selected job ids."""

    model_config = ConfigDict(extra="forbid")

    job_ids: list[int] = Field(min_length=1, description="Explicitly selected job ids")
    dry_run: bool = Field(
        default=False,
        description="Inspect application forms without submitting anything.",
    )


class ManualApplyStartResponse(BaseModel):
    """Response when starting a manual apply run."""

    model_config = ConfigDict(extra="forbid")

    status: str
    run_token: Optional[str] = None
    accepted_job_ids: list[int] = []
    dropped_job_ids: list[int] = []
    message: str


class ManualApplyStopRequest(BaseModel):
    """Request to stop the active manual apply run (idempotent)."""

    model_config = ConfigDict(extra="forbid")

    run_token: Optional[str] = None


class ManualApplyStopResponse(BaseModel):
    """Response after requesting a stop (idempotent)."""

    model_config = ConfigDict(extra="forbid")

    cancel_requested: bool
    active_state: str
    message: str


class ManualApplyRunSummary(BaseModel):
    """Safe summary of the active or last manual apply run."""

    model_config = ConfigDict(extra="forbid")

    run_token: Optional[str] = None
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stats: dict = Field(default_factory=dict)
    error: Optional[str] = None
    progress: Optional[dict] = None
    waiting_for_user: bool = False
    waiting_for_question_id: Optional[int] = None
    cancel_requested: bool = False


class ManualApplyStatusResponse(BaseModel):
    """Live status of the manual apply queue (shares the singleton cycle lock)."""

    model_config = ConfigDict(extra="forbid")

    active_state: str
    lock_held: bool
    active_run: Optional[ManualApplyRunSummary] = None
    last_manual_run: Optional[ManualApplyRunSummary] = None
    pending_question_available: bool = False
