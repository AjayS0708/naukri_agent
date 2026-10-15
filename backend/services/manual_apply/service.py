"""Manual apply queue (E5-R29): apply to already-discovered jobs on demand.

The operator explicitly picks previously discovered jobs; no discovery sweep
ever runs. The run shares the singleton cycle lock with the autonomous cycle
(and, as of E5-R29, the scheduler's apply phase) so only one apply process can
hold the browser session at a time.

Safety is unchanged — every gate is the exact same code path the autonomous
cycle uses:

- application-history protection (``protection.protected_job_ids``)
- the shared relevance gate (``job_relevance_check``)
- the deterministic hard filters (``MatchEngine.evaluate_job_deterministic``)
- the external application boundary (EXTERNAL jobs are never selectable)
- mode re-verification of AMBIGUOUS / unclassified jobs (runner, never forced)
- evidence-verified APPLIED confirmation and challenge handling (runner)
- human-in-the-loop screening answers (coordinator waiting flag)
"""
from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.logging import get_logger
from backend.database import database as database_module
from backend.models.application import Application
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile
from backend.services.agent_state import AgentStateManager
from backend.services.applications.protection import protected_job_ids
from backend.services.applications.runner import ApplicationRunner
from backend.services.autonomous_cycle.coordinator import coordinator
from backend.services.matching.engine import MatchEngine, job_relevance_check

logger = get_logger(__name__)

# Outcome counters copied out of ApplicationRunner stats into the manual-run
# summary the dashboard displays.
_STAT_KEYS = (
    "applied",
    "submitted_unconfirmed",
    "skipped",
    "external",
    "needs_attention",
    "failed",
    "attempts_started",
    "auth_required",
    "errors",
)

# Runner event -> progress-doc counter (job_finished carries the outcome).
_OUTCOME_KEYS = {
    "APPLIED": "applied",
    "SUBMITTED_UNCONFIRMED": "submitted_unconfirmed",
    "SKIPPED": "skipped",
    "EXTERNAL": "external",
    "NEEDS_ATTENTION": "needs_attention",
    "FAILED": "failed",
    "ERROR": "failed",
}

# Process-local summary of the most recent completed manual apply run
# (display only; the durable record is always the applications table).
_last_manual_run: Optional[dict[str, Any]] = None


def get_last_manual_run() -> Optional[dict[str, Any]]:
    """Summary of the last completed manual apply run, if any."""
    return dict(_last_manual_run) if _last_manual_run else None


class ManualApplyService:
    """Eligibility listing plus the manual apply run over explicit job ids."""

    def __init__(
        self,
        session: Session,
        state_manager: Optional[AgentStateManager] = None,
    ):
        self.session = session
        self.state_manager = state_manager or AgentStateManager()
        self._run_token: Optional[str] = None
        self._run_progress: dict[str, Any] = {}

    # ── eligibility ──────────────────────────────────────────────────────

    def _load_context(
        self, db: Session
    ) -> tuple[Optional[Profile], Optional[JobPreference], Optional[MatchEngine]]:
        profile = db.execute(select(Profile)).scalars().first()
        if profile is not None and not profile.confirmed:
            profile = None
        preferences = db.execute(select(JobPreference)).scalars().first()
        match_engine = MatchEngine(db) if profile is not None and preferences is not None else None
        return profile, preferences, match_engine

    def _eligibility(
        self,
        job: Job,
        protected_ids: set[int],
        profile: Optional[Profile],
        preferences: Optional[JobPreference],
        match_engine: Optional[MatchEngine],
    ) -> tuple[bool, Optional[str]]:
        """The single eligibility rule for the manual queue (and start-time
        re-validation). Returns ``(eligible, exclusion_reason)``.

        EXTERNAL jobs are never selectable — the manual queue only ever
        submits native Naukri applications through the same runner the
        autonomous cycle uses. AMBIGUOUS / unclassified modes stay eligible:
        the runner re-verifies them live and never forces native without an
        Apply-button evidence.
        """
        mode = (getattr(job, "application_mode", None) or "").strip().upper()
        if mode == "EXTERNAL":
            return False, "external_application"
        if job.id in protected_ids:
            return False, "application_history"
        if job.title:
            allowed_titles = getattr(preferences, "job_titles", None) if preferences else None
            role_ok, role_reason = job_relevance_check(
                job.title,
                allowed_titles,
                role_category=job.role_category,
                department=job.department,
                description=job.description,
            )
            if not role_ok:
                return False, f"not_relevant: {role_reason}"
        if profile is None:
            return False, "profile_not_confirmed"
        if preferences is None:
            return False, "preferences_missing"
        if match_engine is not None:
            decision = match_engine.evaluate_job_deterministic(job, profile, preferences)
            if decision.decision.value != "APPLY":
                return False, f"hard_filtered: {decision.reason}"
        return True, None

    def list_eligible(
        self,
        limit: int = 200,
        offset: int = 0,
        only_eligible: bool = False,
    ) -> dict[str, Any]:
        """Previously discovered jobs with a per-job eligibility verdict."""
        jobs = (
            self.session.execute(
                select(Job).order_by(Job.discovered_at.desc(), Job.id.desc())
            )
            .scalars()
            .all()
        )
        profile, preferences, match_engine = self._load_context(self.session)
        protected = protected_job_ids(self.session, [job.id for job in jobs])

        latest_status: dict[int, str] = {}
        if jobs:
            rows = self.session.execute(
                select(Application.job_id, Application.status)
                .where(Application.job_id.in_([job.id for job in jobs]))
                .order_by(Application.id.desc())
            ).all()
            for job_id, status_value in rows:
                latest_status.setdefault(job_id, status_value or None)

        items: list[dict[str, Any]] = []
        eligible_count = 0
        for job in jobs:
            eligible, reason = self._eligibility(
                job, protected, profile, preferences, match_engine
            )
            if eligible:
                eligible_count += 1
            if only_eligible and not eligible:
                continue
            items.append(
                {
                    "job_id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "experience": job.experience,
                    "application_mode": job.application_mode,
                    "discovered_at": job.discovered_at,
                    "application_status": latest_status.get(job.id),
                    "eligible": eligible,
                    "exclusion_reason": reason,
                }
            )

        total = len(jobs)
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        return {
            "items": items[start:end],
            "total": total,
            "eligible_count": eligible_count,
            "profile_confirmed": profile is not None,
            "preferences_present": preferences is not None,
        }

    def validate_job_ids(self, job_ids: list[int]) -> tuple[list[int], list[int]]:
        """Re-check the shared eligibility rule at start time.

        Returns ``(accepted, dropped)``. A job can become ineligible between
        listing and starting (new application row, preferences change, mode
        re-verified to EXTERNAL); only accepted ids ever reach the runner.
        """
        normalized: list[int] = []
        for job_id in job_ids:
            try:
                normalized.append(int(job_id))
            except (TypeError, ValueError):
                continue
        if not normalized:
            return [], []

        rows = (
            self.session.execute(select(Job).where(Job.id.in_(normalized)))
            .scalars()
            .all()
        )
        by_id = {job.id: job for job in rows}
        profile, preferences, match_engine = self._load_context(self.session)
        protected = protected_job_ids(self.session, normalized)

        accepted: list[int] = []
        dropped: list[int] = []
        for job_id in normalized:
            job = by_id.get(job_id)
            if job is None:
                dropped.append(job_id)
                continue
            eligible, reason = self._eligibility(
                job, protected, profile, preferences, match_engine
            )
            if eligible:
                accepted.append(job_id)
            else:
                logger.info(
                    "manual_apply_job_dropped",
                    extra={"job_id": job_id, "reason": reason},
                )
                dropped.append(job_id)
        return accepted, dropped

    # ── run execution ────────────────────────────────────────────────────

    def _cancellation_requested(self) -> bool:
        if not self._run_token:
            return False
        try:
            return coordinator.is_cancellation_requested(self._run_token)
        except Exception as exc:
            logger.warning(f"Cancellation check failed (continuing run): {exc}")
            return False

    def _persist_progress(self) -> None:
        if not self._run_token:
            return
        try:
            coordinator.update_progress(self._run_token, dict(self._run_progress))
        except Exception as exc:
            logger.warning(f"Failed to persist manual-apply progress: {exc}")

    def _make_progress_hook(self):
        """Fold runner events into the progress doc and the waiting flag.

        Same contract as the autonomous cycle's hook: the runner emits
        ``waiting`` / ``answer_received`` / ``job_started`` / ``job_finished``
        / ``step`` events; the coordinator's waiting flag lets the existing
        pending-question endpoints serve manual runs unchanged.
        """

        async def hook(payload: dict) -> None:
            if not isinstance(payload, dict):
                return
            event = payload.get("event")
            try:
                if event == "waiting":
                    self._run_progress.update(
                        {
                            "waiting_for_user": True,
                            "current_step": "waiting_for_user",
                            "current_question": payload.get("question"),
                            "pending_question_id": payload.get("pending_question_id"),
                        }
                    )
                    if self._run_token:
                        coordinator.set_waiting(
                            self._run_token, payload.get("pending_question_id")
                        )
                elif event == "answer_received":
                    self._run_progress.update(
                        {
                            "waiting_for_user": False,
                            "current_step": "resuming",
                            "current_question": None,
                            "pending_question_id": None,
                        }
                    )
                    if self._run_token:
                        coordinator.clear_waiting(self._run_token)
                elif event == "job_started":
                    self._run_progress.update(
                        {
                            "current_job_id": payload.get("job_id"),
                            "current_step": "starting",
                            "waiting_for_user": False,
                        }
                    )
                elif event == "job_finished":
                    outcome = payload.get("outcome")
                    key = _OUTCOME_KEYS.get(outcome)
                    if key:
                        self._run_progress[key] = self._run_progress.get(key, 0) + 1
                    self._run_progress["processed"] = (
                        self._run_progress.get("processed", 0) + 1
                    )
                    self._run_progress["remaining"] = max(
                        0,
                        self._run_progress.get("candidates_total", 0)
                        - self._run_progress["processed"],
                    )
                    self._run_progress["current_step"] = "job_done"
                elif event == "step":
                    self._run_progress["current_step"] = payload.get("step")
                self._persist_progress()
            except Exception as exc:
                logger.warning(f"Manual apply progress hook failed: {exc}")

        return hook

    async def run(
        self, job_ids: list[int], run_token: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Execute the manual apply run, then release the coordinator lock.

        Opens its own database session (background task; the request-scoped
        session is closed by the time this runs).
        """
        global _last_manual_run

        self._run_token = run_token
        started_at = datetime.now(UTC)
        stats: dict[str, Any] = {
            "run_kind": "MANUAL_APPLY",
            "requested": len(job_ids),
            "processed": 0,
            "applied": 0,
            "submitted_unconfirmed": 0,
            "skipped": 0,
            "external": 0,
            "needs_attention": 0,
            "failed": 0,
            "attempts_started": 0,
            "auth_required": 0,
            "errors": 0,
            "dry_run": bool(dry_run),
        }
        status = "COMPLETED"
        error: Optional[str] = None

        self._run_progress = {
            "phase": "applying",
            # Marks the active run as manual so the status endpoint (and the
            # autonomous-cycle panel filter) can tell the two run kinds apart.
            "run_kind": "MANUAL_APPLY",
            "candidates_total": len(job_ids),
            "processed": 0,
            "applied": 0,
            "submitted_unconfirmed": 0,
            "skipped": 0,
            "external": 0,
            "needs_attention": 0,
            "failed": 0,
            "remaining": len(job_ids),
            "current_job_id": None,
            "current_job_title": None,
            "current_step": "starting",
            "waiting_for_user": False,
            "current_question": None,
            "pending_question_id": None,
        }
        self._persist_progress()

        db = database_module.SessionLocal()
        runner: Optional[ApplicationRunner] = None
        try:
            runner = ApplicationRunner(
                db,
                self.state_manager,
                dry_run=dry_run,
                run_token=run_token,
                progress_hook=self._make_progress_hook(),
                cancel_check=self._cancellation_requested,
                hitl=bool(run_token),
                close_session_after_run=True,
                recover_stale_state=True,
            )

            # Reconcile-first (same as the autonomous cycle): verify unresolved
            # rows against Naukri's read-only history before any new attempt so
            # duplicate protection sees the authoritative state. The browser
            # opens lazily and only when such rows exist.
            try:
                reconciled = runner.reconcile_history(db)
                if inspect.isawaitable(reconciled):
                    await reconciled
            except Exception as exc:
                logger.warning(
                    f"Pre-run application-history reconciliation skipped: {exc}"
                )

            result = await runner.run_applications(list(job_ids), dry_run=dry_run)
            if isinstance(result, dict):
                if result.get("error"):
                    status = "FAILED"
                    error = str(result["error"])
                stats["processed"] = int(result.get("processed", 0) or 0)
                for key in _STAT_KEYS:
                    try:
                        stats[key] = int(result.get(key, 0) or 0)
                    except (TypeError, ValueError):
                        pass
            else:
                status = "FAILED"
                error = "Application runner returned no result"

            if status != "FAILED":
                if stats.get("auth_required"):
                    # E5-R16 contract: a logged-out session is a terminal
                    # state, never an ordinary per-job failure.
                    status = "LOGIN_REQUIRED"
                    error = "Naukri session is signed out; sign in and retry"
                elif self._cancellation_requested():
                    status = "CANCELLED"
        except Exception as exc:
            logger.exception("manual_apply_run_failed")
            status = "FAILED"
            error = str(exc)
        finally:
            if runner is not None:
                try:
                    closed = runner.close_session()
                    if inspect.isawaitable(closed):
                        await closed
                except Exception as exc:
                    logger.warning(f"Failed to close manual apply session: {exc}")
            try:
                coordinator.complete(
                    run_token,
                    {
                        "run_id": None,
                        "status": status,
                        "stats": stats,
                        "error": error,
                    },
                )
            except Exception:
                logger.exception("manual_apply_lock_release_failed")
            try:
                db.close()
            except Exception:
                pass

        completed_at = datetime.now(UTC)
        _last_manual_run = {
            "run_token": run_token,
            "status": status,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "stats": stats,
            "error": error,
        }
        logger.info(
            "manual_apply_run_completed",
            extra={"status": status, "applied": stats.get("applied", 0)},
        )
        return _last_manual_run
