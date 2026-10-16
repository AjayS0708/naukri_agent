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
from backend.services.applications.protection import (
    protected_job_ids,
    user_skipped_job_ids,
)
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
    # E5-R31: jobs never started (Stop/session halt between jobs), the sum
    # of every terminal outcome bucket (reconciliation guard).
    "cancelled_remaining",
    "outcome_total",
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
    # E5-R31: the captcha path writes a NEEDS_ATTENTION row and reports
    # SECURITY_REQUIRED — count it where its row landed.
    "SECURITY_REQUIRED": "needs_attention",
}

# Process-local summary of the most recent completed manual apply run
# (display only; the durable record is always the applications table).
_last_manual_run: Optional[dict[str, Any]] = None

# E5-R32: the currently running manual apply service (if any), so the skip
# endpoint can queue a per-job skip request for the live batch instead of
# touching a page mid-submission. Set for the duration of run() only.
_active_manual_service: Optional["ManualApplyService"] = None


def _now_iso() -> str:
    """E5-R31: UTC timestamp for progress-doc clock fields (job/step start)."""
    return datetime.now(UTC).isoformat()


def get_last_manual_run() -> Optional[dict[str, Any]]:
    """Summary of the last completed manual apply run, if any."""
    return dict(_last_manual_run) if _last_manual_run else None


def request_job_skip(job_id: int, db: Session) -> dict[str, Any]:
    """E5-R32: skip one job from the Apply Queue ("Skip This Job").

    - An active batch queues the request; the runner honors it at the next
      job boundary (never mid-submission).
    - With no batch running the skip is recorded immediately.
    - A job with blocking application history (already applied / unresolved
      attempt) or an existing user skip is refused honestly — no fake rows.

    Returns ``{"job_id", "mode", "message"}`` with mode one of
    RECORDED / QUEUED / ALREADY_SKIPPED / ALREADY_PROCESSED / NOT_ELIGIBLE.
    """
    from backend.services.applications.protection import (
        USER_SKIP_PREFIX,
        user_skipped_job_ids,
    )
    from backend.services.applications.service import ApplicationService

    job = db.get(Job, int(job_id))
    if job is None:
        return {
            "job_id": job_id,
            "mode": "NOT_ELIGIBLE",
            "message": f"Job {job_id} no longer exists.",
        }

    if job.id in user_skipped_job_ids(db, [job.id]):
        return {
            "job_id": job.id,
            "mode": "ALREADY_SKIPPED",
            "message": "This job was already skipped by you.",
        }

    active = _active_manual_service
    if active is not None and active._run_token:
        if job.id in active._processed_job_ids:
            return {
                "job_id": job.id,
                "mode": "ALREADY_PROCESSED",
                "message": "The run already processed this job; the skip was not queued.",
            }
        active._skip_requests.add(job.id)
        logger.info(
            "manual_apply_skip_queued",
            extra={"job_id": job.id, "run_token": active._run_token},
        )
        return {
            "job_id": job.id,
            "mode": "QUEUED",
            "message": (
                "Queued — the run will skip this job at the next job boundary "
                "(an in-progress submission is never interrupted)."
            ),
        }

    # No active batch: refuse to append a skip row over blocking history,
    # otherwise record the user skip immediately.
    existing = ApplicationService(db).get_application_by_job(job.id)
    existing_status = getattr(existing, "status", None)
    existing_status = (
        existing_status.value if hasattr(existing_status, "value") else existing_status
    )
    if existing and existing_status in (
        "DISCOVERED",
        "PRE_APPLY",
        "APPLICATION_STARTED",
        "APPLIED",
        "SUBMITTED",
        "NEEDS_ATTENTION",
    ):
        return {
            "job_id": job.id,
            "mode": "NOT_ELIGIBLE",
            "message": (
                f"This job has an existing '{existing_status}' record; "
                "a skip would not change it."
            ),
        }
    ApplicationService(db).record_application_skip(
        job, f"{USER_SKIP_PREFIX}: skipped by the user in the apply queue"
    )
    logger.info("manual_apply_skip_recorded", extra={"job_id": job.id})
    return {
        "job_id": job.id,
        "mode": "RECORDED",
        "message": "Job skipped — it is excluded from future apply runs.",
    }


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
        # E5-R32: per-job user skip requests for the live batch.
        self._skip_requests: set[int] = set()
        self._accepted_job_ids: set[int] = set()
        self._processed_job_ids: set[int] = set()

    def _is_skip_requested(self, job_id: int) -> bool:
        """E5-R32: runner callback — is a user skip queued for this job?"""
        return int(job_id) in self._skip_requests

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
        user_skipped_ids: Optional[set[int]] = None,
    ) -> tuple[bool, Optional[str]]:
        """The single eligibility rule for the manual queue (and start-time
        re-validation). Returns ``(eligible, exclusion_reason)``.

        EXTERNAL jobs are never selectable — the manual queue only ever
        submits native Naukri applications through the same runner the
        autonomous cycle uses. AMBIGUOUS / unclassified modes stay eligible:
        the runner re-verifies them live and never forces native without an
        Apply-button evidence.
        E5-R32: user-skipped jobs are excluded with their own reason before
        the generic application-history one.
        """
        mode = (getattr(job, "application_mode", None) or "").strip().upper()
        if mode == "EXTERNAL":
            return False, "external_application"
        if (getattr(job, "status", None) or "").strip().upper() == "EXPIRED":
            # E5-R30: the runner confirmed from visible evidence that this
            # listing expired; every candidate stage now excludes it.
            return False, "listing_expired"
        if user_skipped_ids and job.id in user_skipped_ids:
            return False, "user_skipped"
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
        q: str = "",
    ) -> dict[str, Any]:
        """Previously discovered jobs with a per-job eligibility verdict.

        E5-R30: server-side pagination and search. ``total`` and
        ``eligible_count`` are computed over the whole search-matched set
        (not the page), so page boundaries never change the counts;
        ``eligible_job_ids`` carries every eligible id of the matched set so
        the "Apply to all eligible" action is not silently limited to the
        first page. Ordering includes ``id`` as a tiebreaker so offset pages
        are stable (no duplicates, no gaps).
        """
        jobs = (
            self.session.execute(
                select(Job).order_by(Job.discovered_at.desc(), Job.id.desc())
            )
            .scalars()
            .all()
        )
        needle = (q or "").strip().lower()
        if needle:
            jobs = [
                job
                for job in jobs
                if needle in (job.title or "").lower()
                or needle in (job.company or "").lower()
            ]
        profile, preferences, match_engine = self._load_context(self.session)
        protected = protected_job_ids(self.session, [job.id for job in jobs])
        # E5-R32: user-initiated skips get their own exclusion reason (and
        # protection) distinct from automated eligibility history.
        user_skipped = user_skipped_job_ids(self.session, [job.id for job in jobs])

        latest_status: dict[int, str] = {}
        latest_skip_reason: dict[int, Optional[str]] = {}
        if jobs:
            rows = self.session.execute(
                select(Application.job_id, Application.status, Application.skip_reason)
                .where(Application.job_id.in_([job.id for job in jobs]))
                .order_by(Application.id.desc())
            ).all()
            for job_id, status_value, skip_reason in rows:
                latest_status.setdefault(job_id, status_value or None)
                latest_skip_reason.setdefault(job_id, skip_reason or None)

        items: list[dict[str, Any]] = []
        eligible_count = 0
        eligible_job_ids: list[int] = []
        for job in jobs:
            eligible, reason = self._eligibility(
                job, protected, profile, preferences, match_engine, user_skipped
            )
            if eligible:
                eligible_count += 1
                eligible_job_ids.append(job.id)
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
                    "skip_reason": latest_skip_reason.get(job.id),
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
            "eligible_job_ids": eligible_job_ids,
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
        user_skipped = user_skipped_job_ids(self.session, normalized)

        accepted: list[int] = []
        dropped: list[int] = []
        for job_id in normalized:
            job = by_id.get(job_id)
            if job is None:
                dropped.append(job_id)
                continue
            eligible, reason = self._eligibility(
                job, protected, profile, preferences, match_engine, user_skipped
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
                            "current_step_started_at": _now_iso(),
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
                            "current_step_started_at": _now_iso(),
                            "current_question": None,
                            "pending_question_id": None,
                        }
                    )
                    if self._run_token:
                        coordinator.clear_waiting(self._run_token)
                elif event == "job_started":
                    # E5-R31: surface WHICH job is running and when it (and
                    # the current step) started so the dashboard can show
                    # the job title, per-job elapsed time and staleness.
                    self._run_progress.update(
                        {
                            "current_job_id": payload.get("job_id"),
                            "current_job_title": payload.get("job_title"),
                            "current_job_started_at": _now_iso(),
                            "current_step": "starting",
                            "current_step_started_at": _now_iso(),
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
                    # E5-R32: remember which jobs the runner actually handled
                    # so the end-of-run skip drain never overwrites a real
                    # outcome with a user-skip record.
                    if payload.get("job_id") is not None:
                        try:
                            self._processed_job_ids.add(int(payload["job_id"]))
                        except (TypeError, ValueError):
                            pass
                    self._run_progress["remaining"] = max(
                        0,
                        self._run_progress.get("candidates_total", 0)
                        - self._run_progress["processed"],
                    )
                    self._run_progress["current_step"] = "job_done"
                    self._run_progress["current_step_started_at"] = _now_iso()
                elif event == "step":
                    self._run_progress["current_step"] = payload.get("step")
                    self._run_progress["current_step_started_at"] = _now_iso()
                self._persist_progress()
            except Exception as exc:
                logger.warning(f"Manual apply progress hook failed: {exc}")

        return hook

    def _ensure_fallback_analyses(self, db: Session, job_ids: list[int]) -> list[int]:
        """E5-R30: bring every accepted job to runner-readiness.

        The autonomous cycle persists a conservative deterministic-fallback
        ``JobAnalysisModel`` row for candidates that pass the shared
        deterministic gates but have no AI analysis (E5-R12); the runner then
        finds that row and processes the job. The manual path previously
        called the runner directly, so every no-analysis job was skipped with
        "No AI analysis available" before any page opened (17 of the 26
        outcomes in the first real manual run).

        This mirrors the cycle exactly: re-check the shared deterministic
        gate, persist the same fallback row when it passes, and drop (with a
        recorded skip reason) the rare job that no longer passes. No AI
        content, no fabricated analysis — only the same conservative
        fallback the autonomous cycle already writes.
        """
        from backend.models.ai import JobAnalysisModel

        if not job_ids:
            return []

        profile, preferences, match_engine = self._load_context(db)

        existing = {
            row.job_id
            for row in db.execute(
                select(JobAnalysisModel.job_id).where(JobAnalysisModel.job_id.in_(job_ids))
            ).all()
        }

        ready: list[int] = []
        for job_id in job_ids:
            if job_id in existing:
                ready.append(job_id)
                continue
            job = db.get(Job, job_id)
            if job is None:
                self._count_prep_drop(job_id, f"Job {job_id} not found")
                continue
            if profile is None or preferences is None or match_engine is None:
                self._count_prep_drop(job_id, "Profile or preferences unavailable at run time")
                continue
            decision = match_engine.evaluate_job_deterministic(job, profile, preferences)
            if decision.decision.value != "APPLY":
                self._count_prep_drop(job_id, f"Deterministic gate not passed: {decision.reason}")
                continue
            db.add(
                JobAnalysisModel(
                    job_id=job.id,
                    match_score=50,  # same conservative default as the cycle
                    role_match=True,
                    skill_match=True,
                    experience_match=True,
                    location_match=True,
                    salary_match=True,
                    job_quality="GOOD",
                    duplicate_probability=0.0,
                    suspicious=False,
                    recommendation="APPLY",
                    short_reason="Deterministic filter pass (no AI analysis)",
                    model="deterministic_fallback",
                    prompt_version="n/a",
                )
            )
            db.commit()
            logger.info(
                "manual_apply_deterministic_fallback_analysis_created",
                extra={"job_id": job.id},
            )
            ready.append(job_id)
        return ready

    def _count_prep_drop(self, job_id: int, reason: str) -> None:
        """Record a pre-run drop in progress + a durable skip row."""
        logger.info("manual_apply_job_dropped_pre_run", extra={"job_id": job_id, "reason": reason})
        try:
            db = database_module.SessionLocal()
            job = db.get(Job, job_id)
            if job is not None:
                from backend.services.applications.service import ApplicationService

                ApplicationService(db).record_application_skip(job, reason)
        except Exception:
            logger.exception("manual_apply_prep_drop_record_failed", extra={"job_id": job_id})
        finally:
            try:
                db.close()
            except Exception:
                pass
        self._run_progress["processed"] = self._run_progress.get("processed", 0) + 1
        self._run_progress["skipped"] = self._run_progress.get("skipped", 0) + 1
        self._run_progress["remaining"] = max(
            0, self._run_progress.get("candidates_total", 0) - self._run_progress["processed"]
        )
        self._persist_progress()

    def _drain_skip_requests(self, db: Session) -> None:
        """E5-R32: record user skip requests the runner never reached.

        Jobs the runner processed keep their real outcome (requests for them
        are dropped); every other queued request becomes a durable
        USER_SKIPPED row so an operator's skip survives a stopped batch.
        """
        from backend.services.applications.protection import USER_SKIP_PREFIX
        from backend.services.applications.service import ApplicationService

        pending = [
            job_id
            for job_id in set(self._skip_requests)
            if job_id not in self._processed_job_ids
        ]
        self._skip_requests.clear()
        if not pending:
            return
        service = ApplicationService(db)
        for job_id in pending:
            try:
                job = db.get(Job, job_id)
                if job is None:
                    continue
                service.record_application_skip(
                    job, f"{USER_SKIP_PREFIX}: skipped by the user in the apply queue"
                )
                logger.info(
                    "manual_apply_skip_drained",
                    extra={"job_id": job_id, "run_token": self._run_token},
                )
            except Exception:
                logger.exception("manual_apply_skip_drain_item_failed", extra={"job_id": job_id})

    async def run(
        self, job_ids: list[int], run_token: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Execute the manual apply run, then release the coordinator lock.

        Opens its own database session (background task; the request-scoped
        session is closed by the time this runs).
        """
        global _last_manual_run, _active_manual_service

        self._run_token = run_token
        # E5-R32: publish this instance so the skip endpoint can queue
        # per-job requests for THIS batch, and reset the per-run sets.
        _active_manual_service = self
        self._accepted_job_ids = {int(job_id) for job_id in job_ids}
        self._processed_job_ids = set()
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
            # E5-R31: preflight drops, jobs never started by the runner, the
            # terminal-outcome sum and per-stage durations for latency
            # diagnosis (requested = processed + cancelled_remaining holds;
            # dropped is the preflight subset already inside processed).
            "dropped": 0,
            "cancelled_remaining": 0,
            "outcome_total": 0,
            "stage_seconds": {},
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
            "current_job_started_at": None,
            "current_step": "starting",
            "current_step_started_at": started_at.isoformat(),
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
                skip_request_check=self._is_skip_requested,
                hitl=bool(run_token),
                close_session_after_run=True,
                recover_stale_state=True,
            )

            # E5-R30: pre-run readiness. The runner skips jobs that have no
            # persisted JobAnalysis row, so the manual path first writes the
            # same conservative deterministic-fallback analysis the
            # autonomous cycle writes (dropping only jobs that no longer pass
            # the shared deterministic gate, each with a recorded reason).
            ready_ids = self._ensure_fallback_analyses(db, list(job_ids))
            # E5-R32: prep-dropped jobs are already recorded and handled —
            # the end-of-run skip drain must not touch them again.
            self._processed_job_ids.update(set(self._accepted_job_ids) - set(ready_ids))
            prep_dropped = max(0, len(job_ids) - len(ready_ids))
            stats["dropped"] = prep_dropped
            if prep_dropped:
                logger.info(
                    "manual_apply_preflight_drops=%d of %d", prep_dropped, len(job_ids)
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

            if not ready_ids:
                # Everything was dropped in preflight (defensive path —
                # start-time validation normally guarantees at least one).
                # Never open a browser for an empty plan.
                stats["processed"] = prep_dropped
                stats["skipped"] = prep_dropped
                result = None
            else:
                result = await runner.run_applications(list(ready_ids), dry_run=dry_run)
            if isinstance(result, dict):
                if result.get("error"):
                    status = "FAILED"
                    error = str(result["error"])
                stats["processed"] = int(result.get("processed", 0) or 0) + prep_dropped
                for key in _STAT_KEYS:
                    try:
                        stats[key] = int(result.get(key, 0) or 0)
                    except (TypeError, ValueError):
                        pass
                stats["skipped"] = int(stats.get("skipped", 0) or 0) + prep_dropped
                # E5-R31: preflight drops + stage timings (a dict — never
                # int-cast like the counter keys above).
                stats["dropped"] = prep_dropped
                stage_seconds = result.get("stage_seconds")
                if isinstance(stage_seconds, dict):
                    stats["stage_seconds"] = dict(stage_seconds)
                if not error and stats.get("cancelled_remaining") == 0:
                    # Reconciliation guard: every requested job was either
                    # processed (including preflight drops) or explicitly
                    # reported as never started.
                    if stats["processed"] != stats["requested"]:
                        logger.warning(
                            "manual_apply_reconciliation_mismatch requested=%d "
                            "processed=%d outcome_total=%d",
                            stats["requested"],
                            stats["processed"],
                            stats.get("outcome_total", 0),
                        )
                    elif stats.get("outcome_total") not in (None, stats["processed"]):
                        logger.warning(
                            "manual_apply_outcome_total_mismatch processed=%d "
                            "outcome_total=%d",
                            stats["processed"],
                            stats.get("outcome_total", 0),
                        )
            elif result is None:
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
            # E5-R32: stop publishing this instance first so a skip request
            # racing in now records immediately instead of queueing into a
            # batch that is already finishing, then drain requests for jobs
            # the runner never processed (stopped batch). Draining after the
            # clear keeps both orderings idempotent (identical reasons reuse
            # the same row).
            _active_manual_service = None
            try:
                self._drain_skip_requests(db)
            except Exception:
                logger.exception("manual_apply_skip_drain_failed")
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
