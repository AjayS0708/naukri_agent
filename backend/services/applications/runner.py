import asyncio
import inspect
import time
from datetime import UTC, datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, select

from backend.models.application import Application
from backend.models.job import Job, utc_now
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.models.ai_queue import AIQueueItem
from backend.models.screening import PendingQuestion
from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.services.applications.service import ApplicationService, SafetyGateError
from backend.services.applications.protection import protected_job_ids
from backend.services.applications.answer_memory import (
    ScreeningAnswerService,
    normalize_question,
)
from backend.schemas.application import (
    ApplicationStatus,
    ApplicationMethod,
    ApplicationCreate,
    ApplicationUpdate,
    ApplicationStartResult,
)
from backend.services.naukri.adapter import NaukriAdapter
from backend.services.matching.normalizer import compute_profile_experience_years
from backend.services.gemini.provider import GeminiProvider
from backend.services.notifications import NotificationService
from backend.schemas.ai import JobAnalysis
from backend.schemas.ai_queue import AIQueueStatus
from backend.core.logging import get_logger
from backend.core.config import get_settings

logger = get_logger(__name__)


class ApplicationRunner:
    """
    Coordinates the application flow for eligible jobs.
    Processes jobs sequentially with safety gate enforcement.
    """

    # E5-R31: session-level browser death (the persistent context or its
    # pages were closed) — matched on the caught error's message before any
    # attempt row exists, so a dead session can never be confused with a
    # job-level failure (and an ambiguous mid-attempt death is never
    # retried, because the attempt row exists by then).
    _SESSION_LOST_SIGNATURES = (
        "target page, context or browser has been closed",
        "target page, context or browser is closed",
        "browser has been closed",
        "browser is closed",
        "browser is not connected",
        "the browser is not connected",
        "target closed",
        "connection closed",
        "browser session not started",
    )

    # E5-R31: at most this many mid-run session restarts per
    # run_applications() call — a browser that keeps dying must not
    # restart forever.
    _SESSION_RESTART_LIMIT = 3

    def __init__(
        self,
        session: Session,
        state_manager: AgentStateManager,
        dry_run: bool = False,
        supervise_form: bool = False,
        # E5-R21: shared multi-job session, progress reporting, cooperative
        # cancellation and human-in-the-loop screening answers.
        run_token: Optional[str] = None,
        progress_hook: Optional[Callable[[dict], Any]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        hitl: bool = False,
        close_session_after_run: bool = True,
        recover_stale_state: bool = False,
    ):
        self.session = session
        self.state_manager = state_manager
        self.application_service = ApplicationService(session)
        self.adapter = NaukriAdapter(browser_type=get_settings().browser_type)
        self.ai_provider = GeminiProvider()
        self._stop_requested = False
        self._session_started = False
        # E5-R28: real (non-dry-run) APPLICATION_STARTED rows created by the
        # current run_applications() call; exposed as "attempts_started".
        self._attempts_started = 0
        self.dry_run = dry_run
        self.supervise_form = supervise_form
        self.answer_questions = get_settings().answer_questions
        self.dry_run_result = None
        # E5-R21: human-in-the-loop + shared-session controls.
        self.run_token = run_token
        self.progress_hook = progress_hook
        self.cancel_check = cancel_check
        self.hitl = hitl
        self.close_session_after_run = close_session_after_run
        self.recover_stale_state = recover_stale_state
        # "invalid_state" | "browser_start" | None â€” distinguishes why
        # open_session() failed for the caller of run_applications().
        self._open_failure: Optional[str] = None
        self._hitl_poll_interval = 1.5
        self._hitl_timeout_seconds = 3600.0
        # E5-R31: per-job browser/session lifecycle + stage timing.
        # ``_browser_used_this_job`` gates the inter-job pacing delay (a
        # pre-attempt rejection opens no page, so the pause would be dead
        # time); ``_session_restart_attempts`` caps mid-run restarts per
        # run; the stage fields accumulate per-job timings that are merged
        # into ``_stage_totals`` at each job's end.
        self._browser_used_this_job = False
        self._session_restart_attempts = 0
        self._stage_current: Optional[str] = None
        self._stage_mark: Optional[float] = None
        self._stage_seconds: dict[str, float] = {}
        self._stage_totals: dict[str, float] = {}

    async def stop_safely(self):
        """Request a graceful stop to the application runner."""
        self._stop_requested = True
        logger.info("application_runner_stop_requested")

    async def open_session(self) -> bool:
        """Start (or reuse) the browser session and enter the APPLYING state.

        E5-R21: one session serves many jobs. With ``recover_stale_state``
        (shared multi-job runs) a stale non-auth state left behind by an
        earlier job is recovered so a single failure cannot poison every
        remaining candidate; AUTH/SECURITY still stop immediately.
        ``_open_failure`` records why the open failed ("invalid_state" vs
        "browser_start") for run_applications() to map to its contract.
        """
        if self.recover_stale_state:
            state_ok = self.state_manager.ensure_idle()
        else:
            state_ok = self.state_manager.current_state == AgentState.IDLE
        if not state_ok:
            logger.warning("Application runner can only start from IDLE state")
            self._open_failure = "invalid_state"
            return False

        # Enter RUNNING before the browser start so a start failure lands in
        # CRITICAL_ERROR through a legal transition (IDLE -> CRITICAL_ERROR is
        # not an allowed edge).
        self.state_manager.transition_to(AgentState.RUNNING)

        if not self._session_started:
            try:
                started = await self.adapter.start_session()
            except Exception as exc:
                logger.error("Browser session start raised: %s", exc)
                started = False
            if not started:
                logger.error("Failed to start browser session")
                self.state_manager.transition_to(AgentState.CRITICAL_ERROR)
                self._open_failure = "browser_start"
                return False
            self._session_started = True

        self.state_manager.transition_to(AgentState.SEARCHING)
        self.state_manager.transition_to(AgentState.FILTERING)
        self.state_manager.transition_to(AgentState.APPLYING)
        self._open_failure = None
        return True

    async def close_session(self) -> None:
        """Stop the browser session if it is open (idempotent)."""
        if not self._session_started:
            return
        try:
            await self.adapter.stop_session()
        except Exception as exc:
            logger.warning("Browser session stop failed: %s", exc)
        finally:
            self._session_started = False

    def _empty_stats(self, job_ids: list[int], dry_run: bool) -> dict:
        return {
            "total": len(job_ids),
            "processed": 0,
            "applied": 0,
            "submitted_unconfirmed": 0,
            "skipped": 0,
            "needs_attention": 0,
            "external": 0,
            "failed": 0,
            "errors": 0,
            "auth_required": 0,
            "dry_run": 0,
            "dry_run_mode": dry_run,
            # E5-R28: real application attempts started (page reached and a
            # non-dry-run APPLICATION_STARTED row written) — the difference
            # between "candidates seen" and "attempts actually begun".
            "attempts_started": 0,
            # E5-R31: jobs in the batch that were never started (Stop or a
            # session-level halt between jobs), the sum of every terminal
            # outcome bucket (reconciliation guard), and accumulated
            # per-stage durations for latency diagnosis.
            "cancelled_remaining": 0,
            "outcome_total": 0,
            "stage_seconds": {},
        }

    async def run_applications(self, job_ids: list[int], dry_run: bool = False) -> dict:
        """
        Process a list of eligible job IDs sequentially.
        Returns statistics about the run.

        Args:
            job_ids: List of job IDs to process
            dry_run: If True, inspect application form but do not submit (default: False)

        E5-R21: when ``close_session_after_run`` is False (shared multi-job
        runs) the browser session stays open after this call returns so the
        next job reuses it; state still returns to IDLE between jobs.
        """
        self.dry_run = dry_run
        if not await self.open_session():
            if self._open_failure == "invalid_state":
                return {"error": "Invalid state"}
            # Browser session could not start: zeroed stats and no outcome.
            return self._empty_stats(job_ids, dry_run)

        self._stop_requested = False
        # E5-R28: fresh per-call attempt counter (the shared runner serves
        # several run_applications() calls in one cycle).
        self._attempts_started = 0
        # E5-R31: fresh per-call session-restart budget and stage totals.
        self._session_restart_attempts = 0
        self._stage_totals = {}
        stats = self._empty_stats(job_ids, dry_run)

        try:
            # Get profile and preferences
            profile = self.session.execute(select(Profile)).scalars().first()
            if not profile or not profile.confirmed:
                logger.error("No confirmed profile found")
                stats["errors"] = len(job_ids)
                self._return_to_idle_from_active()
                return stats

            preferences = self.session.execute(select(JobPreference)).scalars().first()
            if not preferences:
                logger.error("No job preferences found")
                stats["errors"] = len(job_ids)
                self._return_to_idle_from_active()
                return stats

            # Process jobs sequentially
            for job_id in job_ids:
                # E5-R31: a Stop is honored at the job boundary — between
                # jobs, before a session restart, and before an attempt
                # starts (checked again inside _execute_single_job). Before
                # this, only HITL waits ever noticed a Stop.
                if self._stop_requested or self._cancellation_requested_safely():
                    if not self._stop_requested:
                        logger.info(
                            "Cancellation requested; stopping before job %s", job_id
                        )
                    self._stop_requested = True
                    logger.info("Application runner stopped by user request")
                    break

                try:
                    result = await self._process_single_job(job_id, profile, preferences)
                    stats["processed"] += 1

                    if result == "APPLIED":
                        stats["applied"] += 1
                    elif result == "SUBMITTED_UNCONFIRMED":
                        stats["submitted_unconfirmed"] += 1
                    elif result == "SKIPPED":
                        stats["skipped"] += 1
                    elif result in ("NEEDS_ATTENTION", "SECURITY_REQUIRED"):
                        # E5-R31: every path that writes a NEEDS_ATTENTION
                        # row reports it here too — the captcha path used to
                        # count FAILED while its row said NEEDS_ATTENTION.
                        stats["needs_attention"] += 1
                    elif result == "EXTERNAL":
                        stats["external"] += 1
                    elif result == "FAILED":
                        stats["failed"] += 1
                    elif result == "ERROR":
                        stats["errors"] += 1
                    elif result == "AUTH_REQUIRED":
                        # E5-R16: logged-out session — halt immediately; the
                        # caller surfaces LOGIN_REQUIRED to the dashboard.
                        stats["auth_required"] += 1
                        break
                    elif result == "DRY_RUN_COMPLETE":
                        stats["dry_run"] += 1
                    else:
                        # Unknown outcome (SESSION_LOST is converted inside
                        # _process_single_job and must never reach here):
                        # count it so outcome_total still reconciles, shout.
                        logger.error(
                            "Unexpected application outcome %r for job %s",
                            result,
                            job_id,
                        )
                        stats["errors"] += 1

                    # E5-R31: pace only after a job that actually used the
                    # browser. Pre-attempt rejections (gate, duplicate,
                    # session unavailable) open no page, so the fixed pause
                    # between them was pure dead time in large batches.
                    # Navigation/settle pauses inside the adapter are
                    # untouched — submission reliability depends on them.
                    if self._browser_used_this_job and not self._stop_requested:
                        await asyncio.sleep(2)

                except Exception as e:
                    logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
                    stats["processed"] += 1
                    stats["errors"] += 1
                    if self.state_manager.current_state in (
                        AgentState.SECURITY_REQUIRED,
                        AgentState.AUTH_REQUIRED,
                        AgentState.CRITICAL_ERROR,
                    ):
                        break

            # E5-R31: jobs in the batch that were never started (Stop or an
            # AUTH halt between jobs) are reported explicitly so
            # requested = processed + cancelled_remaining holds.
            stats["cancelled_remaining"] = len(job_ids) - stats["processed"]

            # Return to IDLE, except after a logged-out session (E5-R16):
            # AUTH_REQUIRED stays visible so the operator sees why the workflow
            # stopped instead of an unexplained idle state.
            if self.state_manager.current_state != AgentState.AUTH_REQUIRED:
                self.state_manager.transition_to(AgentState.STOPPED)
                self.state_manager.transition_to(AgentState.IDLE)

        except Exception as e:
            logger.error(f"Application runner failed: {e}", exc_info=True)
            self.state_manager.transition_to(AgentState.CRITICAL_ERROR)

        finally:
            if self.close_session_after_run:
                await self.close_session()

        # E5-R28: publish the attempt count for this call (paths that returned
        # earlier never started an attempt, and _empty_stats already reports 0).
        stats["attempts_started"] = self._attempts_started
        # E5-R31: stage timings + terminal-outcome reconciliation. Every
        # processed job lands in exactly one bucket, so outcome_total must
        # equal processed — a mismatch means a new outcome was added to the
        # loop without a counter (the exact drift that hid 59 failures).
        stats["stage_seconds"] = dict(self._stage_totals)
        stats["outcome_total"] = (
            stats["applied"]
            + stats["submitted_unconfirmed"]
            + stats["skipped"]
            + stats["external"]
            + stats["needs_attention"]
            + stats["failed"]
            + stats["errors"]
            + stats["auth_required"]
            + stats["dry_run"]
        )
        if stats["outcome_total"] != stats["processed"]:
            logger.error(
                "run_applications outcome totals do not reconcile: "
                "processed=%d outcome_total=%d",
                stats["processed"],
                stats["outcome_total"],
            )
        logger.info(
            "run_applications_totals total=%d processed=%d cancelled_remaining=%d "
            "outcome_total=%d applied=%d skipped=%d needs_attention=%d failed=%d "
            "errors=%d",
            stats["total"],
            stats["processed"],
            stats["cancelled_remaining"],
            stats["outcome_total"],
            stats["applied"],
            stats["skipped"],
            stats["needs_attention"],
            stats["failed"],
            stats["errors"],
        )
        return stats

    def _return_to_idle_from_active(self) -> None:
        """Leave the active state machine after an early, non-job exit."""
        if self.state_manager.current_state in (AgentState.APPLYING, AgentState.FILTERING):
            self.state_manager.transition_to(AgentState.STOPPED)
            self.state_manager.transition_to(AgentState.IDLE)

    async def reconcile_history(self, db: Session) -> Optional[dict]:
        """E5-R21: reconcile unresolved rows against Naukri's history first.

        Called by the cycle before the first job. Opens the shared session
        lazily — and only when unresolved rows exist — reviews the read-only
        application history, reconciles through ApplicationService (idempotent,
        never touches protected jobs) and returns the state machine to IDLE so
        the first run_applications() call starts cleanly. The browser session
        stays open for the jobs that follow.
        """
        unresolved = (
            db.execute(
                select(func.count())
                .select_from(Application)
                .where(
                    Application.status.in_(
                        [
                            ApplicationStatus.NEEDS_ATTENTION.value,
                            ApplicationStatus.SUBMITTED.value,
                        ]
                    )
                )
            ).scalar()
            or 0
        )
        if not unresolved:
            return None

        if not await self.open_session():
            return None

        history = None
        try:
            history = await self.adapter.fetch_application_history()
        except Exception as exc:
            logger.warning("Application-history reconciliation unavailable: %s", exc)
        finally:
            if self.state_manager.current_state == AgentState.APPLYING:
                self.state_manager.transition_to(AgentState.STOPPED)
                self.state_manager.transition_to(AgentState.IDLE)

        if not isinstance(history, list):
            return None
        try:
            return self.application_service.reconcile_from_history(history)
        except Exception as exc:
            logger.warning("reconcile_from_history failed: %s", exc)
            return None

    async def _emit(self, payload: dict) -> None:
        """Report a progress event to the owner of the shared session."""
        if self.progress_hook is None:
            return
        try:
            result = self.progress_hook(payload)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning("progress hook failed: %s", exc)

    def _is_session_lost_error(self, message: str) -> bool:
        """E5-R31: True when the error means the browser session died
        (persistent context terminated) rather than the job itself failing."""
        lowered = (message or "").lower()
        return any(sig in lowered for sig in self._SESSION_LOST_SIGNATURES)

    def _cancellation_requested_safely(self) -> bool:
        """E5-R31: poll the owner's cancel_check without ever breaking the
        run on a faulty check (matching the autonomous cycle's behaviour)."""
        if not self.cancel_check:
            return False
        try:
            return bool(self.cancel_check())
        except Exception as exc:
            logger.warning("Cancellation check failed (continuing run): %s", exc)
            return False

    def _record_job_outcome(self, job_id: int, reason: str) -> str:
        """E5-R31: record a truthful skip row for a job the session could not
        attempt (or could no longer attempt) and report SKIPPED."""
        job = self.session.get(Job, job_id)
        if job is None:
            logger.warning("Job %s missing while recording session outcome", job_id)
            return "ERROR"
        self.application_service.record_application_skip(job, reason)
        return "SKIPPED"

    async def _restart_browser_session(self) -> bool:
        """E5-R31: restore a dead browser session so the batch can continue.

        Operates directly on the adapter (the state machine is already in
        APPLYING mid-run, so open_session()'s IDLE-only transition cannot be
        reused). The profile lock is released by stop_session and re-acquired
        by start_session; if another process grabs it meanwhile, this fails
        and the caller records truthful skip rows instead of looping.
        """
        try:
            await self.adapter.stop_session()
        except Exception as exc:
            logger.warning("Stale session stop failed during restart: %s", exc)
        self._session_started = False
        try:
            started = await self.adapter.start_session()
        except Exception as exc:
            logger.error("Browser session restart raised: %s", exc)
            started = False
        if not started:
            logger.error(
                "Browser session restart failed: %s",
                self.adapter.last_startup_error,
            )
            return False
        self._session_started = True
        return True

    async def _recover_session_and_retry(
        self,
        job_id: int,
        profile: Profile,
        preferences: JobPreference,
    ) -> str:
        """E5-R31: after a pre-attempt session death, restart once and retry
        this same job; never retry when the session cannot come back, when
        Stop is pending, or when the fresh session dies again (bounded).

        Only reached when NO attempt row exists for this job — an
        ambiguous mid-attempt death returns NEEDS_ATTENTION from
        _execute_single_job and is never retried from here.
        """
        if self._stop_requested or self._cancellation_requested_safely():
            self._stop_requested = True
            return self._record_job_outcome(
                job_id, "Run stopped before the job was attempted"
            )
        if self._session_restart_attempts >= self._SESSION_RESTART_LIMIT:
            return self._record_job_outcome(
                job_id,
                "Browser session unavailable — job not attempted "
                "(restart attempts exhausted for this run)",
            )
        self._session_restart_attempts += 1
        if not await self._restart_browser_session():
            return self._record_job_outcome(
                job_id, "Browser session unavailable — job not attempted"
            )
        logger.warning(
            "Browser session restarted mid-run job=%s attempt=%d",
            job_id,
            self._session_restart_attempts,
        )
        outcome = await self._execute_single_job(job_id, profile, preferences)
        if outcome == "SESSION_LOST":
            return self._record_job_outcome(
                job_id, "Browser session unavailable — job not attempted"
            )
        return outcome

    def _begin_stage(self, name: str) -> None:
        """E5-R31: close the pending stage (if any) and start timing ``name``."""
        now = time.monotonic()
        prev, mark = self._stage_current, self._stage_mark
        self._stage_current, self._stage_mark = name, now
        if prev is not None and mark is not None:
            self._stage_seconds[prev] = self._stage_seconds.get(prev, 0.0) + (
                now - mark
            )

    def _finish_stages(self, job_id: int) -> None:
        """E5-R31: close the pending stage, log the per-stage breakdown and
        merge it into the run-level totals."""
        if self._stage_current is not None and self._stage_mark is not None:
            self._stage_seconds[self._stage_current] = (
                self._stage_seconds.get(self._stage_current, 0.0)
                + (time.monotonic() - self._stage_mark)
            )
        self._stage_current = None
        self._stage_mark = None
        if self._stage_seconds:
            breakdown = " ".join(
                f"{name}={seconds:.2f}"
                for name, seconds in sorted(self._stage_seconds.items())
            )
            logger.info("stage_timing job=%s %s", job_id, breakdown)
            for name, seconds in self._stage_seconds.items():
                self._stage_totals[name] = self._stage_totals.get(name, 0.0) + seconds
        self._stage_seconds = {}

    async def _process_single_job(
        self,
        job_id: int,
        profile: Profile,
        preferences: JobPreference
    ) -> str:
        """E5-R21: emit per-job progress around the actual job execution.

        E5-R31: when execution ends with the SESSION_LOST sentinel (the
        browser died before any attempt was made), restart the session and
        retry this same job so one death cannot silently discard the rest of
        the batch.
        """
        job_title = None
        try:
            job = self.session.get(Job, job_id)
            job_title = job.title if job is not None else None
        except Exception:
            pass
        await self._emit(
            {"event": "job_started", "job_id": job_id, "job_title": job_title}
        )
        outcome = await self._execute_single_job(job_id, profile, preferences)
        if outcome == "SESSION_LOST":
            outcome = await self._recover_session_and_retry(
                job_id, profile, preferences
            )
        await self._emit({"event": "job_finished", "job_id": job_id, "outcome": outcome})
        return outcome

    async def _execute_single_job(
        self,
        job_id: int,
        profile: Profile,
        preferences: JobPreference
    ) -> str:
        """
        Process a single job through the complete application flow.
        Returns: "APPLIED", "SUBMITTED_UNCONFIRMED", "SKIPPED", "NEEDS_ATTENTION",
        "EXTERNAL", "FAILED", "ERROR", "SECURITY_REQUIRED", "AUTH_REQUIRED",
        "DRY_RUN_COMPLETE", "SESSION_LOST" (session died before any attempt;
        consumed by _process_single_job — never seen by the batch loop).
        """
        # E5-R31: per-job reset — stage timing and the browser-use flag that
        # gates the inter-job pacing delay.
        self._browser_used_this_job = False
        self._stage_seconds = {}
        self._stage_current = None
        self._stage_mark = None

        job = self.session.get(Job, job_id)
        if not job:
            logger.warning(f"Job {job_id} not found")
            return "ERROR"

        queue_item = self.session.execute(
            select(AIQueueItem).where(AIQueueItem.job_id == job_id)
        ).scalars().first()

        # Get AI analysis if available
        job_analysis = None
        analysis_model = self.session.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == job_id)
        ).scalars().first()

        # E5-R21: skip on an incomplete queue item ONLY when there is also no
        # persisted analysis. The autonomous cycle writes a deterministic
        # fallback analysis for quota-blocked candidates; honoring it means a
        # single QUOTA_BLOCKED queue row no longer discards the job.
        if queue_item and queue_item.status != AIQueueStatus.COMPLETED.value and analysis_model is None:
            logger.info(f"Job {job_id} has incomplete AI analysis (status: {queue_item.status})")
            self.application_service.record_application_skip(job, f"AI analysis not completed: {queue_item.status}")
            return "SKIPPED"

        if analysis_model:
            job_analysis = JobAnalysis(
                match_score=analysis_model.match_score,
                role_match=analysis_model.role_match,
                skill_match=analysis_model.skill_match,
                experience_match=analysis_model.experience_match,
                location_match=analysis_model.location_match,
                salary_match=analysis_model.salary_match,
                job_quality=analysis_model.job_quality,
                duplicate_probability=analysis_model.duplicate_probability,
                suspicious=analysis_model.suspicious,
                recommendation=analysis_model.recommendation,
                short_reason=analysis_model.short_reason
            )
        else:
            # No AI analysis available - skip job
            logger.info(f"Job {job_id} has no AI analysis")
            self.application_service.record_application_skip(job, "No AI analysis available")
            return "SKIPPED"

        # Run final safety gate
        allowed, reason = self.application_service.run_final_safety_gate(
            job, profile, preferences, job_analysis
        )

        if not allowed:
            logger.info(f"Job {job_id} blocked by safety gate: {reason}")
            self.application_service.record_application_skip(job, reason)
            return "SKIPPED"

        # Check duplicate
        if self.application_service.check_duplicate_application(job):
            logger.info(f"Job {job_id} already applied to")
            self.application_service.record_application_skip(job, "Duplicate application")
            return "SKIPPED"

        latest = self.application_service.get_application_by_job(job.id)
        if latest and latest.status in (
            ApplicationStatus.EXTERNAL_APPLICATION,
            ApplicationStatus.NEEDS_ATTENTION,
        ):
            logger.info(f"Job {job_id} has an unresolved prior attempt; manual reset required")
            return "SKIPPED"

        # E5-R28: shared application-history protection, in union with — never
        # in place of — the latest-row guard above (the external/needs-
        # attention guard keeps its semantics even when a SKIPPED row is the
        # newest row). This stops a job whose history blocks a new attempt
        # before any browser page is opened: the candidate stage can no longer
        # hand such jobs over (shared predicate), but a direct runner call or
        # a job written between candidate selection and execution must not
        # slip through either.
        if protected_job_ids(self.session, [job_id]):
            logger.info(f"Job {job_id} has blocking application history; manual reset required")
            return "SKIPPED"

        # E5-R30: external boundary — a job already classified EXTERNAL is
        # excluded here, before any application page is opened. The stored
        # mode is never changed (that requires live destination evidence),
        # the page is never opened, and no external site is ever visited —
        # the exclusion reason is recorded instead.
        if (job.application_mode or "").strip().upper() == "EXTERNAL":
            logger.info(
                "Job %s excluded before page open: application mode EXTERNAL", job_id
            )
            self.application_service.record_application_skip(
                job,
                "External application - excluded before opening the job page "
                "(native Naukri applications only)",
            )
            return "EXTERNAL"

        # Open job page
        page = None
        application = None
        try:
            self._begin_stage("open_job_page")
            await self._emit({"event": "step", "job_id": job_id, "step": "opening_job_page"})
            result = await self.adapter.open_job_page(job.url)
            page = result.page
            # E5-R31: the page is open — this job consumed browser time, so
            # the inter-job pacing delay applies to it.
            self._browser_used_this_job = True
            self._begin_stage("page_detection")
            await self._emit(
                {"event": "step", "job_id": job_id, "step": "detecting_job_state"}
            )

            # Check if security intervention is required
            if result.security_required:
                logger.warning(f"Security challenge encountered for job {job_id}: {result.security_reason}")
                self.application_service.record_application_failure(
                    job, f"Security challenge: {result.security_reason}"
                )
                self._notify_safely(
                    lambda: NotificationService(self.session).security_challenge(
                        f"Security challenge while opening job {job_id}: {result.security_reason}"
                    )
                )
                return "SECURITY_REQUIRED"

            # Phase 10: Detect application type BEFORE creating APPLICATION_STARTED
            # E5-R16: authentication state is checked first and kept separate
            # from application mode. A logged-out session must stop this job
            # without producing an application record of any kind.
            login_state = await self.adapter.detect_login_state(page)
            if login_state.get("authenticated") is False:
                logger.warning(
                    "Naukri session logged out for job %s (evidence: %s); "
                    "stopping application processing",
                    job_id,
                    login_state.get("evidence"),
                )
                self.state_manager.transition_to(AgentState.AUTH_REQUIRED)
                return "AUTH_REQUIRED"

            # E5-R30: revalidate listing availability from positive visible
            # evidence before any attempt. An expired listing is marked on
            # the job row (removing it from every candidate stage) and
            # excluded with the matched phrase as the reason. A transient
            # browser error never reaches this check (open_job_page raised).
            expired_evidence = await self.adapter.detect_expired_listing(page)
            if expired_evidence:
                logger.info(
                    "Job %s listing expired (evidence: %s)", job_id, expired_evidence
                )
                job.status = "EXPIRED"
                self.session.commit()
                self.application_service.record_application_skip(
                    job, f"Listing expired - {expired_evidence}"
                )
                return "SKIPPED"

            app_type = await self.adapter.detect_application_type(page)

            # E5-R25: evidence-based application-mode correction for jobs
            # recovered from the existing-job backlog whose stored mode is
            # AMBIGUOUS / NULL. Detection ran live on the open page above; the
            # result only ever *upgrades* an unclassified row — a stored
            # NAUKRI_NATIVE or EXTERNAL is never overwritten here. NAUKRI_NATIVE
            # is stamped only when the page returned positive native evidence
            # (visible Apply control); EXTERNAL only with a destination URL.
            stored_mode = (job.application_mode or "").strip().upper()
            if stored_mode in ("", "AMBIGUOUS", "NULL"):
                if app_type == "NAUKRI_NATIVE":
                    job.application_mode = "NAUKRI_NATIVE"
                    job.mode_reverified_at = utc_now()
                    self.session.commit()
                    logger.info(
                        "Job %s re-classified NAUKRI_NATIVE from live evidence",
                        job_id,
                    )
                elif app_type == "EXTERNAL":
                    # Confirmation requires the destination URL, checked below
                    # in the EXTERNAL branch; stamp it there so no EXTERNAL is
                    # written without evidence.
                    pass

            if app_type == "EXTERNAL":
                external_url = await self.adapter.get_external_redirect_url(page)
                if not external_url:
                    # E5-R16: no positive destination evidence. The page is
                    # not provably external (a logged-out or incomplete page
                    # is not evidence either), so this is unresolved.
                    logger.warning(
                        "Job %s classified EXTERNAL without destination "
                        "evidence; recording unresolved instead",
                        job_id,
                    )
                    self.application_service.record_application_failure(
                        job, "Application destination unresolved (no external link evidence)"
                    )
                    return "NEEDS_ATTENTION"
                # E5-R25: positive destination evidence upgrades an
                # unclassified row to EXTERNAL and records when the live
                # re-verification happened (used by the recovery cooldown).
                # Set before record_external_application so its commit
                # persists the correction.
                if stored_mode in ("", "AMBIGUOUS", "NULL"):
                    job.application_mode = "EXTERNAL"
                job.mode_reverified_at = utc_now()
                self.application_service.record_external_application(
                    job,
                    external_url,
                    "external - needs review",
                    is_dry_run=self.dry_run,
                )
                self._notify_safely(
                    lambda: NotificationService(self.session).external_application(
                        job.title, external_url
                    )
                )
                logger.info(
                    "Job %s requires external application (external_url=%s)",
                    job_id,
                    external_url,
                )
                return "EXTERNAL"

            if app_type == "AMBIGUOUS":
                # E5-R25: stamp the re-verification time so the recovery
                # cooldown stops this still-ambiguous posting from being
                # re-visited on every subsequent run. No application row is
                # created on this path, so commit the stamp directly.
                job.mode_reverified_at = utc_now()
                self.session.commit()
                logger.warning("Application type is ambiguous for job %s", job_id)
                return "NEEDS_ATTENTION"

            # Phase 10: Re-classify immediately before the click (non-dry-run only)
            if not self.dry_run:
                recheck_type = await self.adapter.detect_application_type(page)
                if recheck_type == "EXTERNAL":
                    external_url = await self.adapter.get_external_redirect_url(page)
                    if external_url:
                        logger.warning(
                            "Application type changed before Apply click: %s",
                            recheck_type,
                        )
                        self.application_service.record_external_application(
                            job,
                            external_url,
                            "external - needs review",
                            is_dry_run=False,
                        )
                        return "EXTERNAL"
                    logger.warning(
                        "Re-check reported EXTERNAL for job %s without "
                        "destination evidence; not recording EXTERNAL",
                        job_id,
                    )
                elif recheck_type != "NAUKRI_NATIVE":
                    # E5-R16: AMBIGUOUS (e.g. Apply hidden while logged out)
                    # is NOT evidence of an external destination. Never record
                    # an external application for an unresolved re-check.
                    logger.warning(
                        "Application type changed before Apply click: %s "
                        "(unresolved; no external record created)",
                        recheck_type,
                    )
                    return "NEEDS_ATTENTION"

            # E5-R31: last safe boundary before an attempt begins — a Stop
            # must not start a new application. No attempt row exists yet,
            # so a truthful skip row is written and the batch stops after
            # this job (the remainder is reported as cancelled_remaining).
            if self._stop_requested or self._cancellation_requested_safely():
                self._stop_requested = True
                self.application_service.record_application_skip(
                    job, "Run cancelled before the attempt started"
                )
                return "SKIPPED"

            # Phase 10: Create APPLICATION_STARTED only after classification is confirmed
            application = self.application_service.create_application(
                ApplicationCreate(
                    job_id=job_id,
                    status=ApplicationStatus.PRE_APPLY if self.dry_run else ApplicationStatus.APPLICATION_STARTED,
                    application_method=ApplicationMethod.NAUKRI_NATIVE,
                    is_dry_run=self.dry_run,
                )
            )
            if not self.dry_run:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        started_at=datetime.now(UTC),
                        application_method=ApplicationMethod.NAUKRI_NATIVE,
                    ),
                )
                # E5-R28: a real attempt began only on the non-dry-run native
                # path — dry runs inspect a form and never submit.
                self._attempts_started += 1

            if self.dry_run:
                self.dry_run_result = {
                    "job_id": job.id,
                    "job_title": job.title,
                    "job_company": job.company,
                    "job_url": job.url,
                    "application_type": app_type,
                    "inspection_only": True,
                    "native_apply_clicked": False,
                    "start_application_called": False,
                    "submit_application_called": False,
                }
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.NEEDS_ATTENTION,
                        skip_reason="Dry run mode: pre-Apply inspection only",
                    ),
                )
                logger.info(
                    f"DRY RUN: Job {job.id} inspected before native Apply; no remote action"
                )
                return "DRY_RUN_COMPLETE"

            # Start Naukri-native application
            self._begin_stage("start_application")
            await self._emit(
                {"event": "step", "job_id": job_id, "step": "starting_application"}
            )
            start_result = await self.adapter.start_application(page)
            if start_result == ApplicationStartResult.APPLIED:
                evidence = await self.adapter.detect_applied_state(page)
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.APPLIED,
                        applied_at=datetime.now(UTC),
                        application_method=ApplicationMethod.NAUKRI_NATIVE,
                        confirmation_evidence=evidence[1],
                    ),
                )
                return "APPLIED"
            if start_result != ApplicationStartResult.FORM_OPENED:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.NEEDS_ATTENTION,
                        needs_attention=True,
                        skip_reason="Application form did not open within bounded wait",
                    ),
                )
                return "NEEDS_ATTENTION"

            # E5-R7: Naukri's native Apply opens a multi-step *conversational*
            # drawer (chatbot_Drawer) that asks one screening question at a time
            # and submits on the final Save. Drive it to completion here; the
            # legacy single-form path below cannot model this flow.
            if await self.adapter.is_conversational_apply(page):
                self._begin_stage("questions")
                return await self._complete_conversational_application(
                    page, application, job, profile
                )

            # Detect and answer questions
            self._begin_stage("questions")
            questions = await self.adapter.detect_application_questions(page)
            # E5-R21: with human-in-the-loop enabled, saved answers and human
            # answers keep the form moving even when AI answering
            # (answer_questions) is disabled â€” only the AI step is gated.
            if questions and not self.answer_questions and not self.hitl:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.NEEDS_ATTENTION,
                        needs_attention=True,
                        skip_reason="questions - needs review",
                    ),
                )
                return "NEEDS_ATTENTION"
            if self.supervise_form:
                visible_fields = [
                    {
                        "question": question.get("question", ""),
                        "required": question.get("required", False),
                        "type": question.get("type"),
                    }
                    for question in questions
                ]
                logger.warning(
                    "Supervised form stop for job %s; visible editable fields: %s",
                    job_id,
                    visible_fields,
                )
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.NEEDS_ATTENTION,
                        needs_attention=True,
                        skip_reason="Supervised stop at FORM_OPENED; no fields filled",
                    ),
                )
                return "NEEDS_ATTENTION"

            prepared_answers = []

            for q in questions:
                question_text = q.get("question", "")
                if not question_text:
                    continue

                await self._emit({
                    "event": "step",
                    "job_id": job_id,
                    "step": "answering_questions",
                    "question": question_text,
                })

                # E5-R21: reuse an approved saved answer first, then profile.
                answer = self._lookup_saved_answer(
                    question_text,
                    options=q.get("options"),
                    employer=job.company,
                    job_id=job.id,
                    profile=profile,
                )
                answer_source = "SAVED" if answer else None

                if not answer:
                    # Try to answer from profile
                    answer = self._get_answer_from_profile(question_text, profile)
                    answer_source = "PROFILE" if answer else None

                if not answer and self.answer_questions:
                    # Try AI-generated answer
                    answer = self._get_ai_answer(question_text, job, profile)
                    if answer:
                        answer_source = "GEMINI"

                if not answer:
                    # E5-R21: ask the human before giving up on the job.
                    status, human_answer = await self._await_user_answer(
                        job=job,
                        application=application,
                        question_text=question_text,
                        options=q.get("options"),
                        question_type=_question_type_for(q.get("options")),
                    )
                    if status == "ANSWERED" and human_answer:
                        if not await self._auth_ok_after_wait(page, job):
                            return "AUTH_REQUIRED"
                        answer = human_answer
                        answer_source = "USER"
                    elif status == "SKIPPED":
                        return self._record_user_skip(application, job)
                    elif status == "CANCELLED":
                        return self._record_stop_while_waiting(application, job)

                if answer:
                    prepared_answers.append({
                        "question": question_text,
                        "answer": answer,
                        "source": answer_source,
                        "required": q.get("required", False)
                    })
                    if not self.dry_run:
                        await self.adapter.answer_question(page, question_text, answer)
                else:
                    # Cannot answer - needs attention
                    self.application_service.update_application(
                        application.id,
                        ApplicationUpdate(
                            status=ApplicationStatus.NEEDS_ATTENTION,
                            skip_reason=f"Could not answer question: {question_text}"
                        )
                    )
                    return "NEEDS_ATTENTION"

            # Submit application (production path only)
            self._begin_stage("submit")
            await self._emit({"event": "step", "job_id": job_id, "step": "submitting"})
            submitted = await self.adapter.submit_application(page)
            if not submitted:
                if self.adapter.last_submit_outcome == "AMBIGUOUS":
                    # E5-R20: a timed-out/intercepted click leaves the true
                    # state unknown â€” reconcile against Naukri's application
                    # history before recording any outcome.
                    return await self._reconcile_unconfirmed_attempt(
                        application,
                        job,
                        "Form submit click timed out or was intercepted (ambiguous)",
                    )
                self.application_service.record_application_failure(
                    job, "Failed to submit application"
                )
                return "FAILED"

            # Confirm submission
            self._begin_stage("confirm")
            await self._emit(
                {"event": "step", "job_id": job_id, "step": "confirming_submission"}
            )
            confirmed = await self.adapter.confirm_submission(page)
            if confirmed:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.APPLIED,
                        applied_at=datetime.now(UTC)
                    )
                )
                logger.info(f"Job {job_id} applied successfully")
                return "APPLIED"
            else:
                # Submission may have succeeded even without confirmation.
                # E5-R5.2: this is NOT a confirmed application. Persist the
                # truthful SUBMITTED status (no retry, no resubmission) and
                # report a distinct outcome so callers never count it as
                # APPLIED or consume the successful-application budget.
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.SUBMITTED,
                        applied_at=datetime.now(UTC)
                    )
                )
                logger.info(
                    f"Job {job_id} submitted without confirmation "
                    f"(confirmation_unclear)"
                )
                return "SUBMITTED_UNCONFIRMED"

        except Exception as e:
            error_msg = str(e).lower()

            # Check for security/authentication issues
            if "captcha" in error_msg or "security" in error_msg:
                self.application_service.record_application_failure(
                    job, "Security verification required"
                )
                self.state_manager.transition_to(AgentState.SECURITY_REQUIRED)
                self._notify_safely(
                    lambda: NotificationService(self.session).security_challenge(
                        "Security verification required during application processing"
                    )
                )
                # E5-R31: the row written above is NEEDS_ATTENTION, so the
                # outcome must say so — counting FAILED here was one of the
                # counter/row mismatches.
                return "SECURITY_REQUIRED"

            if "login" in error_msg or "auth" in error_msg:
                # E5-R16: a session-level failure says nothing about this job.
                # Resolve an attempt row if one is already open; otherwise
                # create no application record at all.
                self.application_service.resolve_open_attempt(
                    job, "Authentication required"
                )
                self.state_manager.transition_to(AgentState.AUTH_REQUIRED)
                self._notify_safely(
                    lambda: NotificationService(self.session).authentication_required(
                        "Authentication required during application processing"
                    )
                )
                return "AUTH_REQUIRED"

            logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
            # E5-R30: distinguish "the page never got far enough for an
            # attempt" from an ambiguous mid-attempt failure. Without an
            # application row (and without an open row from a previous run)
            # nothing was attempted, so the failure is recorded as a
            # retryable skip with the navigation/page error as its reason —
            # it must not create a blocking NEEDS_ATTENTION row. An open
            # prior attempt stays NEEDS_ATTENTION (its true state is
            # unknown and must never be blindly retried).
            resolved = self.application_service.resolve_open_attempt(
                job, f"Application error: {str(e)}"
            )
            if resolved is None and application is None:
                # E5-R31: a dead browser session (context terminated) before
                # any attempt is not a job failure — no row is written and
                # the caller restarts the session and retries this job once.
                if self._is_session_lost_error(str(e)):
                    logger.warning(
                        "Job %s: browser session lost before any attempt", job_id
                    )
                    return "SESSION_LOST"
                self.application_service.record_application_skip(
                    job, f"Page failed before any attempt started: {str(e)}"
                )
                # E5-R31: the row above is SKIPPED, so the outcome is too.
                return "SKIPPED"
            if resolved is None:
                # This invocation had an attempt row; surface it for review.
                self.application_service.record_application_failure(
                    job, f"Application error: {str(e)}"
                )
            # E5-R31: an attempt row exists (this invocation's or a prior
            # run's) and it is NEEDS_ATTENTION — report the same thing. A
            # session death here is ambiguous mid-attempt death: never
            # retried, never reported as FAILED.
            return "NEEDS_ATTENTION"

        finally:
            if page:
                self._begin_stage("cleanup")
                # E5-R31: adapter.close_page never terminates the persistent
                # context (bare page.close() did — see its docstring). Test
                # doubles may lack it or return non-awaitable sentinels, so
                # the call is guarded exactly like _emit guards the hook.
                closer = getattr(self.adapter, "close_page", None)
                try:
                    result = closer(page) if callable(closer) else page.close()
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:
                    logger.debug("job page cleanup failed: %s", exc)
            # E5-R31: close the pending stage and publish the breakdown even
            # on paths that returned early inside the try.
            self._finish_stages(job_id)

    def _notify_safely(self, callback: Callable[[], object]) -> None:
        try:
            callback()
        except Exception as exc:
            logger.error(
                "application_notification_failed",
                extra={"error_type": type(exc).__name__},
            )

    def _get_answer_from_profile(self, question: str, profile: Profile) -> Optional[str]:
        """Try to answer a question from confirmed profile data."""
        question_lower = question.lower()
        profile_data = profile.data if isinstance(profile.data, dict) else {}

        # E5-R14: Handle specific screening questions based on profile skills/projects
        # Data Cleaning/EDA question - check for relevant skills and projects
        if "data cleaning" in question_lower or "eda" in question_lower or "exploratory data analysis" in question_lower:
            skills = profile_data.get("skills", [])
            projects = profile_data.get("projects", [])
            
            # Check for data cleaning/EDA skills
            relevant_skills = [s for s in skills if any(term in s.lower() for term in ["pandas", "numpy", "data", "analysis", "cleaning"])]
            
            # Check projects for data cleaning work
            has_data_project = False
            for project in projects:
                if isinstance(project, dict):
                    desc = project.get("description", "").lower()
                    if "clean" in desc or "process" in desc or "data" in desc:
                        has_data_project = True
                        break
            
            if relevant_skills or has_data_project:
                return "Yes"

        # Common factual questions
        if "experience" in question_lower or "years" in question_lower:
            exp_count = compute_profile_experience_years(profile_data.get("experience", []))
            return str(exp_count)

        if "current ctc" in question_lower or "salary" in question_lower:
            ctc = profile_data.get("current_ctc")
            if ctc:
                return str(ctc)

        if "notice period" in question_lower:
            notice = profile_data.get("notice_period")
            if notice:
                return str(notice)

        if "location" in question_lower:
            location = profile_data.get("location")
            if location:
                return str(location)

        if "education" in question_lower or "degree" in question_lower:
            education = profile_data.get("education", [])
            if education:
                return str(education[0]) if isinstance(education, list) else str(education)

        return None

    def _get_ai_answer(self, question: str, job: Job, profile: Profile) -> Optional[str]:
        """Get AI-generated answer for open-ended questions."""
        try:
            job_context = f"Title: {job.title}\nCompany: {job.company}\nDescription: {job.description or ''}"
            profile_context = str(profile.data)

            answer = self.ai_provider.answer_question(job_context, profile_context, question)
            if answer and answer.answer and not answer.needs_attention:
                return answer.answer
        except Exception as e:
            logger.warning(f"AI answer generation failed: {e}")

        return None

    # E5-R7: conversational (chatbot_Drawer) application support ----------------

    _CONVERSATIONAL_MAX_STEPS = 12
    # E5-R20: the same prompt may be interacted with at most this many times
    # before the attempt terminates with a specific reason (previously the
    # same nudge was "answered" 12 times in a row with no progress).
    _CONVERSATIONAL_MAX_PROMPT_HANDLES = 2
    # E5-R20: global bound on answer interactions per attempt.
    _CONVERSATIONAL_MAX_ANSWERS = 8

    async def _complete_conversational_application(
        self, page, application, job: Job, profile: Profile
    ) -> str:
        """Drive Naukri's multi-step conversational apply drawer to completion.

        The drawer shows one prompt at a time: an answerable question, an
        informational nudge (e.g. "update your profile") or a confirmation.

        E5-R20 rules:
        - questions are answered at most ``_CONVERSATIONAL_MAX_PROMPT_HANDLES``
          times per distinct prompt; an unchanged repeat terminates the
          attempt with a specific reason instead of looping.
        - nudges/prompts with no answer options are NEVER answered: they are
          observed once (with at most one supported dismissal click) and a
          second unchanged observation terminates with a specific reason.
        - Applied is recorded only on explicit confirmation evidence; every
          other ending is reconciled against Naukri's application history
          first (history is authoritative over an intercepted/timed-out
          click) before NEEDS_ATTENTION is written.
        """
        prompt_handles: dict[tuple, int] = {}
        total_answers = 0

        for step in range(1, self._CONVERSATIONAL_MAX_STEPS + 1):
            applied, evidence = await self.adapter.detect_applied_state(page)
            if applied:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.APPLIED,
                        applied_at=datetime.now(UTC),
                        application_method=ApplicationMethod.NAUKRI_NATIVE,
                        confirmation_evidence=evidence,
                    ),
                )
                logger.info("Conversational apply confirmed (step %d): %s", step, evidence)
                return "APPLIED"

            questions = await self.adapter.detect_application_questions(page)
            if not questions:
                logger.info("Conversational drawer has no more questions (step %d)", step)
                break

            question = questions[0]
            question_text = question.get("question", "")
            options = question.get("options") or []
            # E5-R20: detection tags conversational prompts with an explicit
            # kind ("question" | "nudge" | "info"). Dicts without a kind are
            # legacy-shaped form questions and stay answerable.
            kind = question.get("kind") or (
                "question"
                if options or question.get("type") in ("text", "radio", "select")
                else "info"
            )
            signature = (
                self.adapter._normalize_choice(question_text),
                tuple(self.adapter._normalize_choice(o) for o in options),
            )
            handles = prompt_handles.get(signature, 0)

            if kind != "question":
                # E5-R20: informational prompt (nudge) â€” never answer it.
                if handles == 0:
                    prompt_handles[signature] = 1
                    if await self.adapter.dismiss_conversational_nudge(page):
                        logger.info(
                            "Dismissed conversational prompt (step %d): %r",
                            step,
                            question_text,
                        )
                    else:
                        logger.info(
                            "Observed conversational prompt without answer options "
                            "(step %d): %r",
                            step,
                            question_text,
                        )
                    await asyncio.sleep(2.0)
                    continue
                return await self._reconcile_unconfirmed_attempt(
                    application,
                    job,
                    "Persistent conversational nudge with no answer options "
                    f"(unanswered): {question_text}",
                )

            if handles >= self._CONVERSATIONAL_MAX_PROMPT_HANDLES:
                return await self._reconcile_unconfirmed_attempt(
                    application,
                    job,
                    "Conversational prompt unchanged after answering "
                    f"(possible stale UI): {question_text}",
                )

            # Answerable question: saved answer â†’ profile â†’ AI â†’ human.
            saved = self._lookup_saved_answer(
                question_text,
                options=options or None,
                employer=job.company,
                job_id=job.id,
                profile=profile,
            )
            answer = saved
            if not answer:
                answer = self._get_answer_from_profile(question_text, profile)
            if options:
                if not answer or self.adapter._normalize_choice(answer) not in [
                    self.adapter._normalize_choice(o) for o in options
                ]:
                    answer = self._answer_radio_via_ai(question_text, options, job, profile)
                if not answer:
                    status, human_answer = await self._await_user_answer(
                        job=job,
                        application=application,
                        question_text=question_text,
                        options=options,
                        question_type="SINGLE_CHOICE",
                    )
                    if status == "ANSWERED" and human_answer:
                        if not await self._auth_ok_after_wait(page, job):
                            return "AUTH_REQUIRED"
                        answer = human_answer
                    elif status == "SKIPPED":
                        return self._record_user_skip(application, job)
                    elif status == "CANCELLED":
                        return self._record_stop_while_waiting(application, job)
                    if not answer:
                        return await self._reconcile_unconfirmed_attempt(
                            application, job,
                            f"Could not choose an option for: {question_text}",
                        )
            else:
                if not answer:
                    answer = self._get_ai_answer(question_text, job, profile)
                if not answer:
                    status, human_answer = await self._await_user_answer(
                        job=job,
                        application=application,
                        question_text=question_text,
                        question_type="TEXT",
                    )
                    if status == "ANSWERED" and human_answer:
                        if not await self._auth_ok_after_wait(page, job):
                            return "AUTH_REQUIRED"
                        answer = human_answer
                    elif status == "SKIPPED":
                        return self._record_user_skip(application, job)
                    elif status == "CANCELLED":
                        return self._record_stop_while_waiting(application, job)
                    if not answer:
                        return await self._reconcile_unconfirmed_attempt(
                            application, job,
                            f"Could not answer question: {question_text}",
                        )

            if not await self.adapter.answer_conversational_question(
                page, answer, expected_question=question_text
            ):
                return await self._reconcile_unconfirmed_attempt(
                    application, job,
                    f"Failed to answer question: {question_text}",
                )

            prompt_handles[signature] = handles + 1
            total_answers += 1
            logger.info(
                "Conversational step %d answered %r with %r", step, question_text, answer
            )
            if total_answers >= self._CONVERSATIONAL_MAX_ANSWERS:
                return await self._reconcile_unconfirmed_attempt(
                    application,
                    job,
                    "Conversational interaction bound reached before Applied confirmation",
                )
            await asyncio.sleep(2.0)

        # Final explicit confirmation, then a bounded submit attempt whose
        # result is reconciled against Naukri's application history.
        self._begin_stage("confirm")
        applied, evidence = await self.adapter.detect_applied_state(page)
        if applied:
            self.application_service.update_application(
                application.id,
                ApplicationUpdate(
                    status=ApplicationStatus.APPLIED,
                    applied_at=datetime.now(UTC),
                    application_method=ApplicationMethod.NAUKRI_NATIVE,
                    confirmation_evidence=evidence,
                ),
            )
            logger.info("Conversational apply confirmed after loop: %s", evidence)
            return "APPLIED"

        # E5-R20: click only a supported Apply/Submit control (never .sendMsg)
        # and treat every non-confirmed result â€” including a timed-out or
        # intercepted click â€” as unconfirmed pending history reconciliation.
        self._begin_stage("submit")
        outcome = await self.adapter.submit_conversational_application(page)
        if outcome == "SUBMITTED":
            await asyncio.sleep(2.0)
            self._begin_stage("confirm")
            applied, evidence = await self.adapter.detect_applied_state(page)
            if applied:
                self.application_service.update_application(
                    application.id,
                    ApplicationUpdate(
                        status=ApplicationStatus.APPLIED,
                        applied_at=datetime.now(UTC),
                        application_method=ApplicationMethod.NAUKRI_NATIVE,
                        confirmation_evidence=evidence,
                    ),
                )
                logger.info("Conversational apply confirmed after submit: %s", evidence)
                return "APPLIED"
            return await self._reconcile_unconfirmed_attempt(
                application,
                job,
                "Conversational submit clicked without Applied confirmation",
            )
        if outcome == "AMBIGUOUS":
            return await self._reconcile_unconfirmed_attempt(
                application,
                job,
                "Conversational submit click timed out or was intercepted (ambiguous)",
            )
        return await self._reconcile_unconfirmed_attempt(
            application,
            job,
            "Conversational apply completed without Applied confirmation "
            "and no supported submit control was found",
        )

    async def _reconcile_unconfirmed_attempt(
        self, application, job: Job, reason: str
    ) -> str:
        """E5-R20: reconcile an unconfirmed ending against Naukri's
        application history before recording NEEDS_ATTENTION.

        History is authoritative: when the applied-jobs page lists this job,
        ApplicationService.reconcile_from_history (idempotent, never touches
        protected jobs) records/keeps the APPLIED row, the current attempt
        row is annotated for audit but never rewritten to APPLIED, and the
        outcome reported is "APPLIED". When history does not list it, the
        attempt is annotated NEEDS_ATTENTION with the specific reason â€” no
        retry is attempted from here.
        """
        history_entries = None
        try:
            self._begin_stage("history_reconcile")
            history_entries = await self.adapter.fetch_application_history()
        except Exception as exc:
            logger.warning(
                "Job %s: application-history reconciliation unavailable: %s",
                job.id,
                exc,
            )

        if history_entries is not None:
            try:
                result = self.application_service.reconcile_from_history(history_entries)
            except Exception as exc:
                logger.warning(
                    "Job %s: reconcile_from_history failed: %s", job.id, exc
                )
                result = None
            if result is not None:
                confirmed_ids = set(result.get("confirmed_local_job_ids") or [])
                reconciled_ids = set(result.get("reconciled_job_ids") or [])
                if job.id in confirmed_ids or job.id in reconciled_ids:
                    self.application_service.update_application(
                        application.id,
                        ApplicationUpdate(
                            status=ApplicationStatus.NEEDS_ATTENTION,
                            needs_attention=True,
                            skip_reason=(
                                f"{reason}; application confirmed via Naukri "
                                "application history (no in-page confirmation)"
                            ),
                        ),
                    )
                    logger.info(
                        "Job %s confirmed via application-history reconciliation",
                        job.id,
                    )
                    return "APPLIED"
                logger.info(
                    "Job %s: history does not list this application "
                    "(reconciled=%d, confirmed=%d, ambiguous=%d, unmatched=%d)",
                    job.id,
                    len(reconciled_ids),
                    len(confirmed_ids),
                    len(result.get("ambiguous") or []),
                    len(result.get("unmatched") or []),
                )

        self.application_service.update_application(
            application.id,
            ApplicationUpdate(
                status=ApplicationStatus.NEEDS_ATTENTION,
                needs_attention=True,
                skip_reason=(
                    f"{reason}; not confirmed in Naukri application history"
                    if history_entries is not None
                    else f"{reason}; application history unavailable for verification"
                ),
            ),
        )
        logger.warning("Job %s unconfirmed: %s", job.id, reason)
        return "NEEDS_ATTENTION"

    def _answer_radio_via_ai(
        self, question: str, options: list[str], job: Job, profile: Profile
    ) -> Optional[str]:
        """Ask the AI to pick exactly one of the provided radio options.

        Returns the matched option (normalized back to its original casing) or
        None when no option can be chosen confidently. Never fabricates a choice.
        """
        try:
            constrained = (
                f"{question}\n"
                f"Options: {', '.join(options)}. "
                "Reply with exactly one option word/phrase from the list."
            )
            raw = self._get_ai_answer(constrained, job, profile)
            if not raw:
                return None
            norm_raw = self.adapter._normalize_choice(raw)
            for option in options:
                if self.adapter._normalize_choice(option) == norm_raw:
                    return option
            for option in options:
                norm_opt = self.adapter._normalize_choice(option)
                if norm_opt and (norm_opt in norm_raw or norm_raw in norm_opt):
                    return option
        except Exception as exc:
            logger.warning("Radio AI answer failed: %s", exc)
        return None

    # E5-R21: human-in-the-loop screening answers ---------------------------------

    def _lookup_saved_answer(
        self,
        question: str,
        *,
        options: Optional[list] = None,
        employer: Optional[str] = None,
        job_id: Optional[int] = None,
        profile: Any = None,
    ) -> Optional[str]:
        """Reuse an approved saved answer (scope/staleness checked) or None."""
        try:
            service = ScreeningAnswerService(self.session)
            row = service.find(
                question,
                options=options,
                employer=employer,
                job_id=job_id,
                profile=profile,
            )
            if row is None:
                return None
            service.mark_reused(row)
            logger.info(
                "Reusing saved screening answer (id=%s, scope=%s)",
                row.id,
                row.scope,
            )
            return row.answer
        except Exception as exc:
            logger.warning("Screening answer lookup failed: %s", exc)
            return None

    async def _await_user_answer(
        self,
        *,
        job: Job,
        application,
        question_text: str,
        options: Optional[list] = None,
        question_type: str = "TEXT",
    ) -> tuple[str, Optional[str]]:
        """Pause until the human answers, skips, cancels or the wait expires.

        Persists a PendingQuestion row, emits a ``waiting`` progress event and
        polls the row (short-lived session, so API commits are visible) until
        it leaves WAITING. Returns (status, answer) with status one of
        ANSWERED / SKIPPED / CANCELLED / EXPIRED / UNAVAILABLE. Without
        ``hitl`` plus a ``run_token`` this is a no-op (UNAVAILABLE) so callers
        keep the pre-E5-R21 review behaviour.
        """
        if not self.hitl or not self.run_token:
            return "UNAVAILABLE", None

        pending = PendingQuestion(
            run_token=self.run_token,
            application_id=getattr(application, "id", None),
            job_id=job.id,
            employer=job.company,
            job_title=job.title,
            question_text=question_text,
            question_fingerprint=normalize_question(question_text),
            question_type=question_type,
            options=list(options) if options else None,
            status="WAITING",
        )
        self.session.add(pending)
        self.session.commit()
        self.session.refresh(pending)
        pending_id = pending.id

        await self._emit({
            "event": "waiting",
            "pending_question_id": pending_id,
            "job_id": job.id,
            "question": question_text,
        })
        logger.info(
            "Waiting for user answer (pending_question_id=%s, job=%s)",
            pending_id,
            job.id,
        )

        deadline = time.monotonic() + self._hitl_timeout_seconds
        status = "EXPIRED"
        answer: Optional[str] = None
        try:
            while True:
                if self.cancel_check and self.cancel_check():
                    status = "CANCELLED"
                    break
                if time.monotonic() >= deadline:
                    status = "EXPIRED"
                    break
                await asyncio.sleep(self._hitl_poll_interval)
                row_status, row_answer = self._poll_pending_question(pending_id)
                if row_status is None:
                    # Row disappeared (manually deleted): stop waiting.
                    status = "EXPIRED"
                    break
                if row_status in ("ANSWERED", "SKIPPED", "CANCELLED", "EXPIRED"):
                    status = row_status
                    answer = row_answer
                    break
        finally:
            if status in ("CANCELLED", "EXPIRED"):
                self._finalize_pending_question(pending_id, status)
            await self._emit({
                "event": "answer_received",
                "pending_question_id": pending_id,
                "job_id": job.id,
                "status": status,
            })
            logger.info(
                "Wait finished (pending_question_id=%s, status=%s)",
                pending_id,
                status,
            )
        return status, answer

    def _poll_pending_question(self, pending_id: int) -> tuple[Optional[str], Optional[str]]:
        """Read the pending row on a short-lived session.

        A fresh short transaction is required: the long-lived run session may
        hold an open read snapshot that would never observe the API's commit.
        """
        from sqlalchemy.orm import Session as SASession

        poll_db = SASession(bind=self.session.get_bind())
        try:
            row = poll_db.get(PendingQuestion, pending_id)
            if row is None:
                return None, None
            return row.status, row.answer
        finally:
            poll_db.close()

    def _finalize_pending_question(self, pending_id: int, status: str) -> None:
        """Record a locally-terminal wait (cancel/expiry) on the pending row."""
        try:
            row = self.session.get(PendingQuestion, pending_id)
            if row is not None and row.status == "WAITING":
                row.status = status
                row.updated_at = datetime.now(UTC)
                self.session.commit()
        except Exception as exc:
            logger.warning("Failed to finalize pending question %s: %s", pending_id, exc)

    async def _session_still_authenticated(self, page) -> bool:
        """Re-validate the Naukri login after a human-in-the-loop wait."""
        try:
            login_state = await self.adapter.detect_login_state(page)
        except Exception as exc:
            logger.warning("Post-wait login re-check failed: %s", exc)
            return True
        return login_state.get("authenticated") is not False

    async def _auth_ok_after_wait(self, page, job: Job) -> bool:
        """E5-R21: a wait can outlive the Naukri session — never resume a
        form on a logged-out page; stop the run with AUTH_REQUIRED instead."""
        if await self._session_still_authenticated(page):
            return True
        logger.warning(
            "Naukri session logged out while waiting for an answer (job %s)",
            job.id,
        )
        self.application_service.resolve_open_attempt(
            job, "Authentication required while waiting for a screening answer"
        )
        self.state_manager.transition_to(AgentState.AUTH_REQUIRED)
        return False

    def _record_user_skip(self, application, job: Job) -> str:
        """E5-R21: the human skipped this job at a screening question."""
        try:
            self.application_service.update_application(
                application.id,
                ApplicationUpdate(
                    status=ApplicationStatus.SKIPPED,
                    needs_attention=False,
                    skip_reason="User skipped the screening question",
                ),
            )
        except Exception as exc:
            logger.warning("Failed to record user skip for job %s: %s", job.id, exc)
        logger.info("Job %s skipped by user at screening question", job.id)
        return "SKIPPED"

    def _record_stop_while_waiting(self, application, job: Job) -> str:
        """E5-R21: the run was stopped while blocked on a human answer."""
        try:
            self.application_service.update_application(
                application.id,
                ApplicationUpdate(
                    status=ApplicationStatus.NEEDS_ATTENTION,
                    needs_attention=True,
                    skip_reason="Run stopped while waiting for an answer to a screening question",
                ),
            )
        except Exception as exc:
            logger.warning("Failed to record waiting-stop for job %s: %s", job.id, exc)
        logger.info("Job %s left NEEDS_ATTENTION: run stopped while waiting for user", job.id)
        # E5-R31: "the run was stopped" must actually stop the batch — the
        # loop polls this flag at the next job boundary.
        self._stop_requested = True
        return "NEEDS_ATTENTION"


def _question_type_for(options: Optional[list]) -> str:
    """Classify a form/conversational question for the pending-question row."""
    if options:
        return "SINGLE_CHOICE"
    return "TEXT"