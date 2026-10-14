"""
Autonomous Cycle Service - CHECKPOINT E3

This service orchestrates the complete autonomous job application cycle by calling existing
services in sequence with the required constraints:
discovery -> hard filters -> AI queue -> Gemini -> final safety gate -> ApplicationRunner

This service is used by:
- CLI (run_autonomous_cycle.py)
- Dashboard API (POST /api/autonomous-cycle/run)

All safety boundaries (D6.1, D6.2, C2, D4/D5, D7) are preserved.
No automation logic is duplicated.
"""

import asyncio
import inspect
import re
from datetime import UTC, datetime
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database.database import SessionLocal
from backend.services.agent_state import AgentStateManager
from backend.services.discovery.service import DiscoveryService
from backend.services.matching.engine import MatchEngine, job_relevance_check
from backend.services.gemini.queue import AIQueueService
from backend.services.applications.runner import ApplicationRunner
from backend.services.applications.service import ApplicationService
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.job import Job
from backend.models.ai import JobAnalysisModel
from backend.models.ai_queue import AIQueueItem
from backend.models.application import Application
from backend.schemas.application import ApplicationStatus
from backend.schemas.ai_queue import AIQueueStatus
from backend.schemas.ai import JobAnalysis
from backend.schemas.agent import AgentState
from backend.core.logging import get_logger
from backend.models.discovery import DiscoveryRun

logger = get_logger(__name__)


def _timestamp(value: datetime | None) -> float:
    """Timezone-tolerant timestamp; naive datetimes are treated as UTC."""
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def posted_freshness_key(posted_at: datetime | None) -> tuple[int, float]:
    """Ascending key placing known posting dates first, newest first.

    Cards whose posting date is unknown return ``(1, 0.0)`` so they always
    sort after cards with a known, grounded date.
    """
    if posted_at is None:
        return (1, 0.0)
    return (0, -_timestamp(posted_at))


def job_freshness_key(job: Job) -> tuple[tuple[int, float], float]:
    """Freshness-first ordering: posting date, then discovery recency."""
    return (posted_freshness_key(job.posted_at), -_timestamp(job.discovered_at))


def application_mode_rank(job: Job) -> int:
    """Ascending rank for native-first candidate prioritization (E5-R9).

    0 = NAUKRI_NATIVE (eligible in-page Apply)
    1 = AMBIGUOUS or unknown (NULL / unclassified) — never promoted to native
    2 = EXTERNAL (apply on company site)

    External-only listings stay eligible; they simply rank after native when
    both pass the same hard filters. Ambiguous is never labeled native just
    to fill the budget.
    """
    mode = (getattr(job, "application_mode", None) or "").strip().upper()
    if mode == "NAUKRI_NATIVE":
        return 0
    if mode == "EXTERNAL":
        return 2
    return 1


def interest_priority_rank(job: Job) -> int:
    """Ascending rank for interest-tier prioritization (E5-R10/E5-R10B).

    0 = Data Analytics / BI / reporting / visualization (highest interest)
    1 = Data Engineering / ETL / Cloud / AI-ML / Data Science
    2 = Graduate engineering / fresher software engineering / trainee / apprenticeship
    3 = Other eligible roles that passed hard filters

    E5-R10B: word-boundary multi-token phrases plus HARD role exclusions
    (Sales/Support/Admin/Managerial/Creative/Trade) that always force rank 3
    so domain keywords (data engineer, analytics, aws, tableau) cannot promote
    sales/support titles. Soft exclusions (architect/consultant) only demote
    when no clean multi-token target phrase hits. Legitimate IC target roles
    still classify by clean multi-token matches. Within a tier, native Naukri
    Apply, freshness, and match score remain the secondary ranking criteria.
    Not a count cap.
    """
    title = (job.title or "").lower().strip()
    if not title:
        return 3

    # HARD role exclusions: Sales/Support/Admin/Managerial/Creative/Trade and
    # pure non-target professions. These ALWAYS force rank 3 even when a
    # domain keyword (data engineer, analytics, aws, tableau) appears in the
    # same title — e.g. "Data Engineer Sales", "Analytics Sales Manager",
    # "Video Analytics Engineer" must never inherit a target tier.
    hard_exclusion_patterns = (
        r"\bsales\b",
        r"\bselling\b",
        r"\bbiz dev\b",
        r"\bbusiness development\b",
        r"\bsupport\b",
        r"\bhelp ?desk\b",
        r"\bcustomer (support|success|service|care)\b",
        r"\baccount (manager|executive|head)\b",
        r"\brelationship manager\b",
        r"\bchannel sales\b",
        r"\bpre-?sales\b",
        r"\bpresales\b",
        r"\bmarketing\b",
        r"\bad operations\b",
        r"\badops\b",
        r"\brecruiter\b",
        r"\brecruitment\b",
        r"\bhr\b",
        r"\bhuman resources\b",
        r"\badmin(istrator|istration)?\b",
        r"\boffice admin\b",
        r"\bfacilities\b",
        r"\breceptionist\b",
        r"\bsecretary\b",
        r"\bfinance\b",
        r"\bvideo\b",
        r"\bgraphic designer\b",
        r"\bui/?ux designer\b",
        r"\bproduct manager\b",
        r"\bdelivery manager\b",
        r"\bengineering manager\b",
        r"\btech(nical)? lead\b",
        r"\bteam lead(er)?\b",
        r"\bhead of\b",
        r"\bdirector\b",
        r"\bchief\b",
        r"\bmanager\b",
        r"\bmanaging\b",
        r"\bprincipal engineer\b",
        r"\bstaff engineer\b",
        r"\btrainer\b",
        r"\btraining\b",
        r"\binstructor\b",
        r"\bteacher\b",
        r"\bcontent writer\b",
        r"\bcopywriter\b",
        r"\btechnical writer\b",
        r"\bsecurity analyst\b",
        r"\bcyber ?security\b",
        r"\bnetwork engineer\b",
        r"\bsystem admin\b",
        r"\bsysadmin\b",
        r"\bqa engineer\b",
        r"\bquality assurance\b",
        r"\bmanual tester\b",
        r"\btest engineer\b",
        r"\bautomation tester\b",
        r"\bmobile (developer|engineer)\b",
        r"\bsalesforce\b",
        r"\bservice ?now\b",
        r"\bhubspot\b",
        r"\bdata entry\b",
        r"\bclerk\b",
        r"\bpeon\b",
        r"\bhelper\b",
        r"\blabour\b",
        r"\blabor\b",
        r"\bfield (executive|sales)\b",
        r"\btelecaller\b",
        r"\bcall cent(er|re)\b",
        r"\bchat support\b",
        r"\bvoice support\b",
        r"\bmechanical engineer\b",
        r"\bcivil engineer\b",
        r"\belectrical engineer\b",
        r"\bindustrial engineer\b",
        r"\bproduction engineer\b",
        r"\bdoctor\b",
        r"\bnurse\b",
        r"\bpharmacist\b",
        r"\baccountant\b",
        r"\baccounting\b",
        r"\binsurance\b",
        r"\bbank(er|ing)?\b",
    )

    # SOFT exclusions: advisory/consulting titles that can legitimately
    # coexist with a clean target-domain phrase (Tableau Consultant,
    # Cloud Architect, Solutions Architect). Only force rank 3 when no
    # positive multi-token phrase hits.
    soft_exclusion_patterns = (
        r"\barchitect\b",
        r"\bconsultant\b",
        r"\badvisor\b",
        r"\bstrategist\b",
    )

    # Positive multi-token phrases only (no bare 'analytics', 'aws',
    # 'dashboard', 'get ', or bare 'software engineer' in manager titles).
    p1_phrases = (
        r"\bdata analyst\b",
        r"\bdata analytics\b",
        r"\banalytics engineer\b",
        r"\banalytics developer\b",
        r"\banalytics consultant\b",
        r"\banalytics specialist\b",
        r"\banalytics scientist\b",
        r"\bproduct analyst\b",
        r"\bmarketing analyst\b",
        r"\bmarketing analytics\b",
        r"\bbusiness analyst\b",
        r"\bbusiness analytics\b",
        r"\bbusiness intelligence\b",
        r"\bbi developer\b",
        r"\bbi engineer\b",
        r"\bbi consultant\b",
        r"\bbi analyst\b",
        r"\bpower bi\b",
        r"\btableau\b(?!.*\b(sales|support|admin|manager)\b)",
        r"\blooker\b",
        r"\bqlik\b",
        r"\bqlikview\b",
        r"\bsuperset\b",
        r"\bmetabase\b",
        r"\bdata visualization\b",
        r"\bdata visualisation\b",
        r"\bdata viz\b",
        r"\breporting analyst\b",
        r"\breporting engineer\b",
        r"\breport developer\b",
        r"\bsql analyst\b",
        r"\bsql developer\b",
        r"\bsql engineer\b",
        r"\bpython analytics\b",
        r"\bdashboard developer\b",
        r"\bdashboard engineer\b",
        r"\bdashboard designer\b",
        r"\breporting specialist\b",
        r"\bdata quality analyst\b",
        r"\bmi analyst\b",
        r"\breporting developer\b",
        r"\btableau developer\b",
        r"\btableau consultant\b",
    )
    p2_phrases = (
        r"\bdata engineer\b",
        r"\bdata engineering\b",
        r"\betl\b",
        r"\bdata pipeline\b",
        r"\bdata platform\b",
        r"\bdata infrastructure\b",
        r"\bcloud engineer\b",
        r"\bcloud developer\b",
        r"\bcloud architect\b",
        r"\bsolutions architect\b",
        r"\baws engineer\b",
        r"\baws developer\b",
        r"\baws architect\b",
        r"\bazure engineer\b",
        r"\bazure developer\b",
        r"\bazure architect\b",
        r"\bgcp engineer\b",
        r"\bgcp developer\b",
        r"\bgcp architect\b",
        r"\bgoogle cloud\b",
        r"\bmachine learning\b(?!.*\bsales\b)",
        r"\bml engineer\b",
        r"\bml developer\b",
        r"\bai/ml\b",
        r"\bai engineer\b",
        r"\bai developer\b",
        r"\bdeep learning\b",
        r"\bdata science\b",
        r"\bdata scientist\b",
        r"\bartificial intelligence\b",
        r"\bmlops\b",
        r"\bnlp engineer\b",
        r"\bcomputer vision\b",
        r"\bsnowflake\b",
        r"\bbigquery\b",
        r"\bredshift\b",
        r"\bdatabricks\b",
        r"\bapache spark\b",
        r"\bkafka\b",
        r"\bairflow\b",
        r"\bdbt\b",
        r"\bhadoop\b",
    )
    p3_phrases = (
        r"\bgraduate engineer\b",
        r"\bgraduate trainee\b",
        r"\bgraduate software\b",
        r"\bfresher software\b",
        r"\bfresher engineer\b",
        r"\bsoftware engineer\b(?!.*\b(manager|head|director|vp|chief|lead|principal|staff)\b)",
        r"\bsoftware developer\b(?!.*\b(manager|head|director|vp|chief|lead|principal|staff)\b)",
        r"\bsde\b",
        r"\bswe\b",
        r"\btrainee engineer\b",
        r"\btrainee software\b",
        r"\bapprentice\b",
        r"\bapprenticeship\b",
        r"\bintern\b(?!.*\b(sales|support|admin|marketing)\b)",
        r"\bentry level\b(?!.*\b(sales|support|admin|marketing)\b)",
        r"\bentry-level\b",
        r"\bjunior software\b",
        r"\bjunior engineer\b",
        r"\bjunior developer\b",
        r"\bengineering trainee\b",
        r"\bdeveloper trainee\b",
        r"\bget engineer\b",
        r"\bget software\b",
        r"\bget trainee\b",
        r"\bgraduate developer\b",
        r"\bfresher developer\b",
        r"\btrainee developer\b",
    )

    # HARD exclusions always win: a sales/support/admin/managerial/creative
    # title can never inherit a target tier from a lone domain keyword.
    if any(re.search(p, title) for p in hard_exclusion_patterns):
        return 3

    has_soft_exclusion = any(re.search(p, title) for p in soft_exclusion_patterns)
    p1_hit = any(re.search(p, title) for p in p1_phrases)
    p2_hit = any(re.search(p, title) for p in p2_phrases)
    p3_hit = any(re.search(p, title) for p in p3_phrases)

    # Soft exclusions (architect/consultant/advisor) only demote when no
    # clean multi-token target phrase is present.
    if has_soft_exclusion and not (p1_hit or p2_hit or p3_hit):
        return 3
    if p1_hit:
        return 0
    if p2_hit:
        return 1
    if p3_hit:
        return 2
    return 3

# Excluded job ID per rules
EXCLUDED_JOB_ID = "300926927428"


class DecisionTracker:
    """Tracks per-job decisions for the decision table output."""

    def __init__(self):
        self.decisions = []

    def add_decision(
        self,
        job_id: int,
        company: str,
        title: str,
        app_type: str,
        salary_pass: bool,
        experience_pass: bool,
        employment_pass: bool,
        gemini_result: str,
        gate_result: str,
        outcome: str,
    ):
        self.decisions.append({
            "job_id": job_id,
            "company": company,
            "title": title,
            "app_type": app_type,
            "salary_pass": salary_pass,
            "experience_pass": experience_pass,
            "employment_pass": employment_pass,
            "gemini_result": gemini_result,
            "gate_result": gate_result,
            "outcome": outcome,
        })

    def print_table(self):
        """Print the decision table to stdout."""
        if not self.decisions:
            return

        print("\n" + "=" * 120)
        print("PER-JOB DECISION TABLE")
        print("=" * 120)
        print(
            f"{'ID':<6} {'Company':<20} {'Title':<25} {'Type':<10} {'Sal':<4} {'Exp':<4} {'Emp':<4} "
            f"{'Gemini':<10} {'Gate':<10} {'Outcome':<15}"
        )
        print("-" * 120)

        for d in self.decisions:
            print(
                f"{d['job_id']:<6} {d['company'][:20]:<20} {d['title'][:25]:<25} {d['app_type']:<10} "
                f"{'PASS' if d['salary_pass'] else 'FAIL':<4} {'PASS' if d['experience_pass'] else 'FAIL':<4} "
                f"{'PASS' if d['employment_pass'] else 'FAIL':<4} {d['gemini_result']:<10} {d['gate_result']:<10} "
                f"{d['outcome']:<15}"
            )

        print("=" * 120 + "\n")


class AutonomousCycle:
    """
    Orchestrates the autonomous application cycle by calling existing services.

    This is the authoritative execution path for autonomous cycles.
    Used by both CLI and Dashboard API to ensure consistent behavior.
    """

    def __init__(
        self,
        max_applications: Optional[int] = None,
        dry_run: bool = False,
        max_jobs: Optional[int] = None,
        max_cards: int = 150,
        enable_cli_output: bool = True,
        run_token: Optional[str] = None,
    ):
        # E5-R10: max_applications is accepted for API compatibility but is
        # NOT enforced as an application-count cap. Runs process every
        # eligible matching job until the queue is exhausted or a genuine
        # blocker (AUTH/SECURITY/critical error) stops the run.
        self.max_applications = max_applications
        self.dry_run = dry_run
        self.max_jobs = max_jobs
        self.max_cards = max_cards
        self.enable_cli_output = enable_cli_output
        self.run_token = run_token
        self.state_manager = AgentStateManager()
        self.tracker = DecisionTracker()
        # E5-R24: index into tracker.decisions where the candidate stage began,
        # so only candidate-stage reasons are persisted with the run result.
        self._candidate_tracker_start = 0
        self.applications_count = 0
        self.stop_reason: Optional[str] = None
        self.stop_is_normal = False
        self.current_discovery_run: Optional[DiscoveryRun] = None
        # E5-R21: one shared ApplicationRunner (one browser session) serves
        # every candidate of a run, plus the live progress document that is
        # persisted to the cycle control row for the dashboard.
        self._runner = None
        self._run_progress: dict = {}

    def _print(self, message: str):
        """Print message to stdout if CLI output is enabled."""
        if self.enable_cli_output:
            print(message)

    def _cancellation_requested(self) -> bool:
        """E5-R15: True when a Stop was requested for this run token."""
        if not self.run_token:
            return False
        try:
            from backend.services.autonomous_cycle.coordinator import coordinator

            return coordinator.is_cancellation_requested(self.run_token)
        except Exception as exc:
            logger.warning(f"Cancellation check failed (continuing run): {exc}")
            return False

    def _check_cancellation(self, boundary: str) -> bool:
        """Stop at a safe boundary when the user requested cancellation.

        Returns True if the run should stop. Never starts a new application
        after cancellation is requested (checked before each job).
        """
        if not self._cancellation_requested():
            return False
        self.stop_reason = f"Cancellation requested at {boundary}"
        self.stop_is_normal = True
        self._print(f"\nCancellation requested; stopping at {boundary}")
        return True

    def _terminal_outcome(self) -> tuple[int, str]:
        """Map the recorded stop reason to the documented terminal contract.

        README, MASTER_PRD and ARCHITECTURE all state: "Exit code 0 on normal
        completion, non-zero on AUTH/SECURITY/critical stop." E5-R10 removed
        application-count limits; a cycle that exhausts the eligible queue or
        stops on an explicit stop_is_normal reason completes with exit 0.
        E5-R15: user cancellation is reported as CANCELLED (never COMPLETED).
        """
        if self.stop_reason and "cancellation requested" in self.stop_reason.lower():
            return 0, "CANCELLED"
        if not self.stop_reason or self.stop_is_normal:
            return 0, "COMPLETED"
        reason = self.stop_reason.upper()
        # E5-R16: a logged-out session is an authentication state the user
        # must resolve; it is reported distinctly, never as COMPLETED.
        if "AUTHENTICATION" in reason or "LOGIN" in reason:
            return 2, "LOGIN_REQUIRED"
        if "AUTH" in reason or "SECURITY" in reason:
            return 2, "FAILED"
        return 3, "FAILED"

    async def run(self) -> dict:
        """
        Run the autonomous cycle. Returns result dict with exit code and stats.
        
        Returns:
            dict: {
                "exit_code": int,
                "run_id": Optional[int],
                "status": str,
                "stats": dict
            }
        """
        db = SessionLocal()
        try:
            # Verify profile and preferences exist
            profile = db.execute(select(Profile)).scalars().first()
            if not profile or not profile.confirmed:
                self._print("ERROR: No confirmed profile found. Please configure profile first.")
                return {"exit_code": 1, "run_id": None, "status": "FAILED", "stats": {}}

            preferences = db.execute(select(JobPreference)).scalars().first()
            if not preferences:
                self._print("ERROR: No job preferences found. Please configure preferences first.")
                return {"exit_code": 1, "run_id": None, "status": "FAILED", "stats": {}}

            self._print(f"\nStarting autonomous cycle (dry_run={self.dry_run}, max_jobs={self.max_jobs})")
            self._print(f"Profile: {profile.data.get('name', 'Unknown')}")
            self._print(f"Job titles: {', '.join(preferences.job_titles or [])}")
            self._print(f"Locations: {', '.join(preferences.locations or [])}")

            if self._check_cancellation("start of cycle"):
                exit_code, terminal_status = self._terminal_outcome()
                return {
                    "exit_code": exit_code,
                    "run_id": None,
                    "status": terminal_status,
                    "stats": {"stop_reason": self.stop_reason},
                }

            # E5-R16: attempts interrupted by a crash/process kill before the
            # confirmation write are surfaced as unresolved (never APPLIED)
            # before any new attempt is made for those jobs.
            try:
                from backend.services.applications.service import ApplicationService

                interrupted = ApplicationService(db).reconcile_interrupted_attempts()
                if interrupted.get("reconciled_count"):
                    self._print(
                        f"  Unresolved interrupted attempts marked for review: "
                        f"{interrupted['reconciled_count']}"
                    )
            except Exception as exc:
                logger.warning(f"Interrupted-attempt reconciliation failed: {exc}")

            # Step 1: Discovery
            self._print("\n[1/5] Running discovery...")
            discovery_service = DiscoveryService(
                self.state_manager,
                max_cards=self.max_cards,
                # E5-R16: cooperative cancellation inside the long discovery
                # pass so Stop takes effect at the next card/search boundary
                # rather than only after discovery finishes.
                cancel_check=self._cancellation_requested,
                # E5-R23: publish per-search discovery progress so the
                # dashboard shows one continuous run (search X of Y) during
                # the multi-search sweep instead of appearing stalled and
                # then restarting at page 1 on each new search.
                progress_hook=self._discovery_progress_hook,
            )
            await discovery_service.run_discovery(db)

            if self.state_manager.current_state == AgentState.AUTH_REQUIRED:
                # E5-R16: the session is logged out. This is an authentication
                # state, not a run failure and never an application-mode
                # classification. Surface it explicitly so the dashboard can
                # ask the user to sign in manually.
                self._print("STOP: Discovery paused - LOGIN_REQUIRED (Naukri session is logged out)")
                return {
                    "exit_code": 2,
                    "run_id": None,
                    "status": "LOGIN_REQUIRED",
                    "stats": {"reason": "Naukri session is not authenticated"},
                }

            if self.state_manager.current_state == AgentState.SECURITY_REQUIRED:
                self._print(f"ERROR: Discovery stopped - {self.state_manager.current_state.value}")
                return {"exit_code": 2, "run_id": None, "status": "FAILED", "stats": {}}

            if self.state_manager.current_state == AgentState.CRITICAL_ERROR:
                self._print("ERROR: Discovery encountered critical error")
                return {"exit_code": 3, "run_id": None, "status": "FAILED", "stats": {}}

            # Capture the current discovery run to ensure we only process jobs from THIS run
            self.current_discovery_run = db.execute(
                select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc())
            ).scalars().first()

            if not self.current_discovery_run:
                self._print("ERROR: No discovery run record found")
                return {"exit_code": 3, "run_id": None, "status": "FAILED", "stats": {}}

            # E5-R15: surface discovery run id on the control row for Stop/status.
            if self.run_token:
                try:
                    from backend.services.autonomous_cycle.coordinator import coordinator

                    coordinator.set_discovery_run_id(self.run_token, self.current_discovery_run.id)
                except Exception as exc:
                    logger.warning(f"Failed to attach discovery_run_id to control row: {exc}")

            # Check if discovery actually found any jobs in this run
            if self.current_discovery_run.jobs_discovered == 0:
                self._print(f"ERROR: Discovery found 0 jobs in current run (status: {self.current_discovery_run.status})")
                if self.current_discovery_run.error_message:
                    self._print(f"Discovery error: {self.current_discovery_run.error_message}")
                self._print("Cycle stopped: No current jobs discovered")
                return {
                    "exit_code": 0,
                    "run_id": self.current_discovery_run.id,
                    "status": "COMPLETED",
                    "stats": {"jobs_discovered": 0}
                }

            self._print(f"Discovery run completed: {self.current_discovery_run.jobs_discovered} jobs discovered (status: {self.current_discovery_run.status})")

            if self._check_cancellation("after discovery"):
                exit_code, terminal_status = self._terminal_outcome()
                return {
                    "exit_code": exit_code,
                    "run_id": self.current_discovery_run.id if self.current_discovery_run else None,
                    "status": terminal_status,
                    "stats": {"stop_reason": self.stop_reason},
                }

            # Step 2: Hard filters and enqueue
            self._print("\n[2/5] Applying hard filters and enqueuing...")
            enqueue_stats = await self._apply_hard_filters_and_enqueue(db, profile, preferences)
            self._print(f"  Discovered: {enqueue_stats['discovered']}")
            self._print(f"  Hard filtered: {enqueue_stats['hard_filtered']}")
            self._print(f"  Pre-analyzed (existing): {enqueue_stats['pre_analyzed']}")
            self._print(f"  Skipped on experience: {enqueue_stats['skipped_experience']}")
            self._print(f"  Skipped non-IT: {enqueue_stats['skipped_non_it']}")
            self._print(f"  Capped by max_jobs: {enqueue_stats['capped']}")
            self._print(f"  Queued for AI: {enqueue_stats['queued']}")

            # Only stop if nothing was newly queued AND no pre-analyzed candidates exist
            if enqueue_stats["queued"] == 0 and enqueue_stats["pre_analyzed"] == 0:
                self._print("\n0 eligible jobs found")
                self.tracker.print_table()
                return {
                    "exit_code": 0,
                    "run_id": self.current_discovery_run.id,
                    "status": "COMPLETED",
                    "stats": enqueue_stats
                }

            # Step 3: Process AI queue — only process items enqueued by this cycle
            ai_stats: dict = {"processed": 0, "completed": 0, "quota_blocked": 0, "errors": []}
            if enqueue_stats["queued"] > 0:
                self._print("\n[3/5] Processing AI queue...")
                ai_stats = await self._process_ai_queue(db, profile, enqueue_stats.get("enqueued_queue_item_ids", []))
                self._print(f"  AI processed: {ai_stats['processed']}")
                self._print(f"  AI completed: {ai_stats['completed']}")
                self._print(f"  AI blocked: {ai_stats['quota_blocked']}")
            else:
                self._print("\n[3/5] Skipping AI queue (all current-run candidates already analyzed)")

            # Count current-run jobs that have a completed analysis
            ready_count = 0
            if self.current_discovery_run and self.current_discovery_run.current_run_job_ids:
                try:
                    cur_ids = [int(x) for x in self.current_discovery_run.current_run_job_ids.split(",")]
                    from sqlalchemy import func as _sqlfunc
                    ready_count = db.execute(
                        select(_sqlfunc.count()).select_from(JobAnalysisModel)
                        .where(JobAnalysisModel.job_id.in_(cur_ids))
                    ).scalar() or 0
                except Exception:
                    ready_count = ai_stats["completed"]
            else:
                ready_count = ai_stats["completed"]

            if ready_count == 0:
                self._print("\nNo jobs have a completed AI analysis in the current run")
                self.tracker.print_table()
                return {
                    "exit_code": 0,
                    "run_id": self.current_discovery_run.id,
                    "status": "COMPLETED",
                    "stats": {**enqueue_stats, **ai_stats}
                }

            if self._check_cancellation("before applications"):
                exit_code, terminal_status = self._terminal_outcome()
                return {
                    "exit_code": exit_code,
                    "run_id": self.current_discovery_run.id,
                    "status": terminal_status,
                    "stats": {**enqueue_stats, **ai_stats, "stop_reason": self.stop_reason},
                }

            # E5-R16: authentication gate. The Naukri login state is detected
            # from the persistent profile before a single job page is opened
            # for application processing. A logged-out session stops the
            # workflow with LOGIN_REQUIRED instead of misreading job pages.
            login_state = await self._probe_login_state()
            if login_state.get("authenticated") is False:
                self.stop_reason = "Authentication required"
                self.stop_is_normal = False
                self._print(
                    "STOP: LOGIN_REQUIRED - Naukri session is not authenticated "
                    f"(evidence: {login_state.get('evidence')}). "
                    "Sign in manually in the agent browser, then run again."
                )
                return {
                    "exit_code": 2,
                    "run_id": self.current_discovery_run.id,
                    "status": "LOGIN_REQUIRED",
                    "stats": {
                        **enqueue_stats,
                        **ai_stats,
                        "reason": "Naukri session is not authenticated",
                        "evidence": login_state.get("evidence"),
                    },
                }
            if login_state.get("authenticated") is True:
                self._print("Naukri session authenticated; starting applications")

            # Step 4: Run applications (E5-R10: no count cap)
            self._print("\n[4/5] Running applications...")
            app_stats = await self._run_applications(db, profile, preferences)
            app_stats["candidate_decisions"] = self._candidate_stage_decisions()
            self._print(f"  Candidates: {app_stats['candidates']}")
            self._print(f"  Applied: {app_stats['applied']}")
            self._print(f"  Submitted (unconfirmed): {app_stats.get('submitted_unconfirmed', 0)}")
            self._print(f"  Skipped: {app_stats['skipped']}")
            self._print(f"  External: {app_stats['external']}")
            self._print(f"  Needs attention: {app_stats['needs_attention']}")

            # Step 5: Print summary
            self._print("\n[5/5] Cycle complete")
            self.tracker.print_table()

            self._print("\nSUMMARY")
            self._print("=" * 60)
            self._print(f"Cards scanned: {enqueue_stats['discovered']}")
            self._print(f"Total jobs discovered: {enqueue_stats['discovered']}")
            self._print(f"Skipped on experience: {enqueue_stats['skipped_experience']}")
            self._print(f"Skipped non-IT: {enqueue_stats['skipped_non_it']}")
            self._print(f"Hard filtered: {enqueue_stats['hard_filtered']}")
            self._print(f"Pre-analyzed (existing): {enqueue_stats['pre_analyzed']}")
            self._print(f"Capped by max_jobs: {enqueue_stats['capped']}")
            self._print(f"Queued for AI: {enqueue_stats['queued']}")
            self._print(f"AI processed: {ai_stats['processed']}")
            self._print(f"AI completed: {ai_stats['completed']}")
            self._print(f"Application candidates: {app_stats['candidates']}")
            self._print(f"Applied: {app_stats['applied']}")
            self._print(f"Submitted (unconfirmed): {app_stats.get('submitted_unconfirmed', 0)}")
            self._print(f"Skipped: {app_stats['skipped']}")
            self._print(f"External: {app_stats['external']}")
            self._print(f"Needs attention: {app_stats['needs_attention']}")
            self._print(f"Failed: {app_stats['failed']}")
            self._print("=" * 60)

            if self.stop_reason:
                self._print(f"\nCycle stopped: {self.stop_reason}")
                exit_code, terminal_status = self._terminal_outcome()
                return {
                    "exit_code": exit_code,
                    "run_id": self.current_discovery_run.id,
                    "status": terminal_status,
                    "stats": {**enqueue_stats, **ai_stats, **app_stats, "stop_reason": self.stop_reason},
                }

            return {
                "exit_code": 0,
                "run_id": self.current_discovery_run.id,
                "status": "COMPLETED",
                "stats": {**enqueue_stats, **ai_stats, **app_stats}
            }

        except Exception as e:
            logger.error(f"Autonomous cycle failed: {e}", exc_info=True)
            self._print(f"ERROR: {e}")
            return {
                "exit_code": 3,
                "run_id": self.current_discovery_run.id if self.current_discovery_run else None,
                "status": "FAILED",
                "stats": {}
            }
        finally:
            db.close()

    async def _apply_hard_filters_and_enqueue(
        self, db: Session, profile: Profile, preferences: JobPreference
    ) -> dict:
        """Apply hard filters and enqueue eligible jobs."""
        stats = {
            "discovered": 0, "hard_filtered": 0, "queued": 0,
            "skipped_experience": 0, "skipped_non_it": 0, "capped": 0,
            "pre_analyzed": 0, "errors": [],
        }

        # Get discovered jobs ONLY from the current discovery run
        if not self.current_discovery_run:
            self._print("ERROR: No current discovery run available for filtering")
            return stats

        # Parse job IDs from current run
        current_run_job_ids = []
        if self.current_discovery_run.current_run_job_ids:
            try:
                current_run_job_ids = [int(jid) for jid in self.current_discovery_run.current_run_job_ids.split(",")]
            except (ValueError, AttributeError):
                pass

        if not current_run_job_ids:
            self._print("WARNING: No current run job IDs available, using timestamp fallback")
            stmt = select(Job).where(
                Job.status == "DISCOVERED",
                Job.discovered_at >= self.current_discovery_run.started_at
            )
        else:
            stmt = select(Job).where(Job.id.in_(current_run_job_ids))

        stmt = stmt.order_by(Job.discovered_at.desc())

        jobs = db.execute(stmt).scalars().all()
        stats["discovered"] = len(jobs)

        if not jobs:
            return stats

        match_engine = MatchEngine(db)
        ai_queue_service = AIQueueService(db)

        eligible_count = 0
        eligible_jobs = []
        enqueued_queue_item_ids = []

        for job in jobs:
            if self.max_jobs and eligible_count >= self.max_jobs:
                stats["capped"] += 1
                self.tracker.add_decision(
                    job.id, job.company, job.title, "N/A", False, False, False, "N/A", "max_jobs cap", "CAPPED"
                )
                continue

            if job.external_job_id == EXCLUDED_JOB_ID:
                stats["hard_filtered"] += 1
                self.tracker.add_decision(
                    job.id, job.company, job.title, "EXCLUDED", False, False, False, "N/A", "N/A", "EXCLUDED"
                )
                continue

            existing_analysis = db.execute(
                select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
            ).scalars().first()

            if existing_analysis:
                stats["pre_analyzed"] += 1
                continue

            existing_queue = db.execute(
                select(AIQueueItem).where(AIQueueItem.job_id == job.id)
            ).scalars().first()

            # E5-R7: A queued item in a terminal state (analysis already stored
            # or permanently failed) is done — skip it. A reprocessable item
            # (QUEUED/RETRY_PENDING/QUOTA_BLOCKED) with no analysis is a stuck
            # prior attempt (e.g. transient Gemini "returned None"); let it fall
            # through the deterministic filter so it is re-enqueued and retried
            # this cycle instead of being silently dropped as hard_filtered.
            if existing_queue and existing_queue.status in (
                "COMPLETED", "FAILED", "NEEDS_ATTENTION"
            ):
                stats["hard_filtered"] += 1
                continue

            # D6.2: Evaluate deterministic filters ONLY (no Gemini call yet)
            match_decision = match_engine.evaluate_job_deterministic(job, profile, preferences)

            salary_pass = match_decision.decision.value == "APPLY" or "salary" not in match_decision.reason.lower()
            experience_pass = match_decision.decision.value == "APPLY" or "experience" not in match_decision.reason.lower()
            employment_pass = match_decision.decision.value == "APPLY" or "employment" not in match_decision.reason.lower()

            if match_decision.decision.value == "APPLY":
                eligible_jobs.append({
                    "job": job,
                    "match_score": match_decision.match_score or 50,
                    "salary_pass": salary_pass,
                    "experience_pass": experience_pass,
                    "employment_pass": employment_pass,
                })
                eligible_count += 1
            else:
                stats["hard_filtered"] += 1
                if match_decision.skip_reason and match_decision.skip_reason.value == "EXPERIENCE_TOO_HIGH":
                    stats["skipped_experience"] += 1
                if "IT_SCOPE" in match_decision.failed_rules:
                    stats["skipped_non_it"] += 1
                self.tracker.add_decision(
                    job.id, job.company, job.title, "N/A", salary_pass, experience_pass, employment_pass, "N/A", match_decision.reason, "HARD_FILTERED"
                )

        # D6.2: Bounded Gemini Candidate Evaluation
        if eligible_jobs:
            # E5-R10: interest priority first, then E5-R9 native-first, then
            # freshness-first (newest grounded posting dates, then most recently
            # discovered), then match score. Unknown/ambiguous application_mode
            # is never treated as native. Jobs with an unknown posting date
            # never outrank known-fresh jobs within the same interest/mode tier.
            # No application-count cap is applied here; every eligible job is
            # enqueued and the run continues until the eligible queue is empty.
            eligible_jobs.sort(
                key=lambda x: (
                    interest_priority_rank(x["job"]),
                    application_mode_rank(x["job"]),
                    job_freshness_key(x["job"]),
                    -x["match_score"],
                )
            )

            for selected in eligible_jobs:
                queue_item = ai_queue_service.enqueue_job(
                    job_id=selected["job"].id,
                    priority=selected["match_score"],
                    priority_reason="Selected as eligible candidate (E5-R10: no application-count cap)",
                    queue_source="AUTONOMOUS_CYCLE",
                )

                if queue_item:
                    stats["queued"] += 1
                    enqueued_queue_item_ids.append(queue_item.id)
                    self.tracker.add_decision(
                        selected["job"].id, selected["job"].company, selected["job"].title, "N/A",
                        selected["salary_pass"], selected["experience_pass"], selected["employment_pass"],
                        "PENDING", "PENDING", "QUEUED (SELECTED)"
                    )

        stats["enqueued_queue_item_ids"] = enqueued_queue_item_ids
        return stats

    async def _probe_login_state(self) -> dict:
        """Read-only Naukri login probe (E5-R16).

        Reuses the existing persistent browser profile: no credential is read,
        printed or stored, and nothing is clicked or submitted.
        """
        from backend.core.config import get_settings
        from backend.services.naukri.adapter import NaukriAdapter

        settings = get_settings()
        adapter = NaukriAdapter(browser_type=settings.browser_type)
        started = await adapter.start_session()
        if not started:
            return {
                "authenticated": None,
                "evidence": adapter.last_startup_error or "session_start_failed",
            }
        try:
            return await adapter.check_session_authenticated()
        finally:
            await adapter.stop_session()

    async def _process_ai_queue(self, db: Session, profile: Profile, enqueued_queue_item_ids: list[int]) -> dict:
        """Process AI queue items enqueued by this autonomous cycle only."""
        stats = {"processed": 0, "completed": 0, "quota_blocked": 0, "errors": []}

        ai_queue_service = AIQueueService(db)
        ai_queue_service.recover_stale_items()

        profile_context = str(profile.data) if profile and profile.data else ""

        for queue_item_id in enqueued_queue_item_ids:
            # E5-R16: Stop must interrupt the AI-queue step too, not only the
            # application loop.
            if self._check_cancellation(f"before AI queue item {queue_item_id}"):
                stats["stop_reason"] = self.stop_reason
                break
            try:
                from backend.models.ai_queue import AIQueueItem
                queue_item = db.execute(
                    select(AIQueueItem).where(AIQueueItem.id == queue_item_id)
                ).scalars().first()

                if not queue_item:
                    continue

                if queue_item.status not in ["QUEUED", "RETRY_PENDING", "QUOTA_BLOCKED"]:
                    continue

                result = ai_queue_service.process_item(queue_item_id, profile_context)
                stats["processed"] += 1

                if result.status.value == "COMPLETED":
                    stats["completed"] += 1
                elif result.status.value == "QUOTA_BLOCKED":
                    stats["quota_blocked"] += 1
                    break

            except Exception as e:
                stats["errors"].append(str(e))

        return stats

    async def _run_applications(
        self, db: Session, profile: Profile, preferences: JobPreference
    ) -> dict:
        """Run applications for eligible jobs (E5-R10: no count cap).

        Candidates are ordered interest_priority_rank → application_mode_rank
        → job_freshness_key → -match_score, matching enqueue order so the
        apply loop processes the same priority sequence the AI queue used.
        """
        stats = {
            "candidates": 0,
            "applied": 0,
            "submitted_unconfirmed": 0,
            "skipped": 0,
            "external": 0,
            "needs_attention": 0,
            "failed": 0,
            # E5-R22: jobs rejected by the shared relevance pre-filter before
            # they enter the candidate list / progress document.
            "relevance_rejected": 0,
            # E5-R24: jobs that reach the candidate query but fail the same
            # deterministic hard filters the enqueue stage already applied.
            "hard_filtered_candidates": 0,
            "errors": [],
        }
        # E5-R24: candidate-stage decision rows are the ones added to the
        # shared tracker from here on; run_cycle persists them so the reasons
        # survive the run instead of only reaching stdout.
        self._candidate_tracker_start = len(self.tracker.decisions)

        # E5-R12: Include jobs without AI analysis that pass deterministic filters
        # as fallback candidates. This prevents blocking native jobs when Gemini quota
        # is exhausted. Jobs without analysis get a default match_score of 50.
        # E5-R13: Restrict to NAUKRI_NATIVE jobs only for this recovery path.
        # EXTERNAL, AMBIGUOUS, and NULL application_mode jobs are excluded to prevent
        # external applications during native-only recovery.
        stmt = select(Job).outerjoin(
            JobAnalysisModel, Job.id == JobAnalysisModel.job_id
        ).outerjoin(
            Application, Application.job_id == Job.id
        ).where(
            (Application.id == None) | (Application.status == ApplicationStatus.SKIPPED.value)
        ).where(
            Job.application_mode == 'NAUKRI_NATIVE'
        ).distinct()

        if self.current_discovery_run and self.current_discovery_run.current_run_job_ids:
            try:
                current_run_job_ids = [int(jid) for jid in self.current_discovery_run.current_run_job_ids.split(",")]
                stmt = stmt.where(Job.id.in_(current_run_job_ids))
            except (ValueError, AttributeError):
                self._print("WARNING: Failed to parse current_run_job_ids, returning no application candidates")
                return stats
        else:
            self._print("WARNING: No current discovery run or current_run_job_ids, returning no application candidates")
            return stats

        if self.max_jobs:
            stmt = stmt.limit(self.max_jobs)

        eligible_jobs = db.execute(stmt).scalars().all()

        # E5-R22: pre-filter candidates through the shared relevance gate
        # before they enter the progress document or the apply loop. Without
        # this, every NAUKRI_NATIVE job with no application became a
        # candidate — BPO / voice / customer-support posts that slipped past
        # discovery's sparse-card filter entered the list (82 candidates in
        # the first controlled live run) and were only skipped late by the
        # per-job safety gate, so the dashboard showed mostly-irrelevant
        # candidates and just 1 real application. Irrelevant jobs are now
        # rejected before the candidate count and can never be reintroduced
        # by the loop.
        allowed_titles = getattr(preferences, "job_titles", None)
        relevant_jobs = []
        for job in eligible_jobs:
            if job.title:
                role_ok, role_reason = job_relevance_check(
                    job.title,
                    allowed_titles,
                    role_category=job.role_category,
                    department=job.department,
                    description=job.description,
                )
                if not role_ok:
                    stats["relevance_rejected"] += 1
                    logger.info(
                        "e5_r22_relevance_rejected_job",
                        extra={
                            "job_id": job.id,
                            "title": job.title,
                            "reason": role_reason,
                        },
                    )
                    self.tracker.add_decision(
                        job.id, job.company, job.title, "N/A",
                        False, False, False,
                        "N/A", role_reason, "RELEVANCE_REJECTED",
                    )
                    continue
            relevant_jobs.append(job)
        eligible_jobs = relevant_jobs

        # E5-R24: the enqueue stage already ran evaluate_job_deterministic on
        # every job in this run, but the candidate query below never re-applied
        # it. In run 86 that pulled 19 of 23 "candidates" into the apply loop
        # only for the runner to skip them again, so the run reported 20 skips
        # against 2 real attempts and the funnel looked like valid jobs were
        # being rejected. Re-run the shared gate here so only jobs that can
        # actually be attempted are counted as candidates.
        if eligible_jobs and profile is not None and preferences is not None:
            match_engine = MatchEngine(db)
            attempts = []
            for job in eligible_jobs:
                decision = match_engine.evaluate_job_deterministic(
                    job, profile, preferences
                )
                if decision.decision.value != "APPLY":
                    stats["hard_filtered_candidates"] += 1
                    failed = set(decision.failed_rules or [])
                    self.tracker.add_decision(
                        job.id, job.company, job.title, "N/A",
                        "SALARY" not in failed,
                        "EXPERIENCE" not in failed,
                        "EMPLOYMENT_TYPE" not in failed,
                        "N/A", decision.reason, "HARD_FILTERED",
                    )
                    logger.info(
                        "e5_r24_hard_filtered_candidate",
                        extra={
                            "job_id": job.id,
                            "title": job.title,
                            "reason": decision.reason,
                            "skip_reason": (
                                decision.skip_reason.value
                                if decision.skip_reason
                                else None
                            ),
                        },
                    )
                    continue
                attempts.append(job)
            eligible_jobs = attempts

        stats["candidates"] = len(eligible_jobs)

        if not eligible_jobs:
            return stats

        # E5-R10B: order candidates identically to enqueue — interest tier,
        # then native-first application mode, then freshness (newest grounded
        # posting first; unknown posted_at last), then higher match score.
        # Match score is read from the persisted AI analysis so the apply loop
        # does not depend on enqueue-time order alone.
        match_scores: dict[int, float] = {}
        job_ids = [job.id for job in eligible_jobs]
        analyses = db.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id.in_(job_ids))
        ).scalars().all()
        for analysis in analyses:
            match_scores[analysis.job_id] = analysis.match_score or 0

        eligible_jobs.sort(
            key=lambda job: (
                interest_priority_rank(job),
                application_mode_rank(job),
                job_freshness_key(job),
                -match_scores.get(job.id, 0),
            )
        )

        # E5-R5.2: bounded tolerance for isolated runner errors. One ordinary
        # ERROR is recorded and skipped; the second consecutive ERROR aborts
        # the remaining candidates. Any valid non-ERROR outcome resets the
        # counter. SECURITY/AUTH stops remain immediate and authoritative.
        # E5-R10: no per-run application-count cap; the loop continues until
        # every eligible candidate is processed or a genuine blocker stops it.
        consecutive_errors = 0

        # E5-R21: one shared runner for the whole run. A single browser
        # session serves every candidate; stale non-auth states left by a
        # failed job are recovered so one failure cannot poison the rest.
        self._run_progress = {
            "candidates_total": len(eligible_jobs),
            "processed": 0,
            "applied": 0,
            "submitted_unconfirmed": 0,
            "skipped": 0,
            "external": 0,
            "needs_attention": 0,
            "failed": 0,
            "remaining": len(eligible_jobs),
            "current_job_id": None,
            "current_job_title": None,
            "current_step": None,
            "waiting_for_user": False,
            "current_question": None,
            "pending_question_id": None,
        }
        self._persist_progress()
        self._runner = ApplicationRunner(
            db,
            self.state_manager,
            dry_run=self.dry_run,
            run_token=self.run_token,
            progress_hook=self._make_progress_hook(),
            cancel_check=self._cancellation_requested,
            hitl=bool(self.run_token),
            close_session_after_run=False,
            recover_stale_state=True,
        )

        # E5-R21: reconcile-first. Before any new attempt is made, unresolved
        # rows (NEEDS_ATTENTION/SUBMITTED) are verified against Naukri's
        # read-only application history so duplicate protection and the
        # dashboard see the authoritative state. Managed runs (run_token)
        # only; the browser opens lazily and only when such rows exist.
        if self.run_token:
            try:
                reconciled = self._runner.reconcile_history(db)
                if inspect.isawaitable(reconciled):
                    reconciled = await reconciled
                if isinstance(reconciled, dict) and reconciled.get("reconciled_job_ids"):
                    self._print(
                        f"  Reconciled {len(reconciled['reconciled_job_ids'])} "
                        "attempt(s) from application history"
                    )
            except Exception as exc:
                logger.warning(f"Pre-run application-history reconciliation skipped: {exc}")

        try:
            for job in eligible_jobs:
                # E5-R15: never begin a new application after Stop is requested.
                if self._check_cancellation(f"before job {job.id}"):
                    stats["stop_reason"] = self.stop_reason
                    return stats
                self._run_progress.update(
                    {
                        "current_job_id": job.id,
                        "current_job_title": job.title,
                        "current_step": "processing",
                        "waiting_for_user": False,
                        "current_question": None,
                        "pending_question_id": None,
                    }
                )
                self._persist_progress()
                try:
                    result = await self._process_single_job(db, job, profile, preferences)

                    # E5-R16: an AUTH/SECURITY blocker observed while processing a
                    # job stops the whole run — it must not be counted as an
                    # ordinary per-job failure and then retried on the next job.
                    if self.state_manager.current_state == AgentState.AUTH_REQUIRED:
                        self.stop_reason = "Authentication required"
                        return stats
                    if self.state_manager.current_state == AgentState.SECURITY_REQUIRED:
                        self.stop_reason = "Security challenge encountered"
                        return stats

                    if result == "APPLIED":
                        stats["applied"] += 1
                        self.applications_count += 1
                        consecutive_errors = 0
                    elif result == "SUBMITTED_UNCONFIRMED":
                        # Clicked submit without positive confirmation: truthful
                        # outcome, never counted toward the successful budget.
                        stats["submitted_unconfirmed"] += 1
                        consecutive_errors = 0
                    elif result == "SKIPPED":
                        stats["skipped"] += 1
                        consecutive_errors = 0
                    elif result == "EXTERNAL":
                        stats["external"] += 1
                        consecutive_errors = 0
                    elif result == "NEEDS_ATTENTION":
                        stats["needs_attention"] += 1
                        consecutive_errors = 0
                    elif result == "FAILED":
                        stats["failed"] += 1
                        consecutive_errors = 0
                    elif result == "ERROR":
                        # The runner never inspected this job (browser session or
                        # agent state unavailable). E5-R5.2: the first isolated
                        # ERROR is recorded and the loop continues so later
                        # candidates can still be considered; a second consecutive
                        # ERROR means the runtime is unusable and aborts instead
                        # of producing a run of bogus outcomes.
                        stats["failed"] += 1
                        consecutive_errors += 1
                        if consecutive_errors >= 2:
                            self.stop_reason = (
                                "Two consecutive runner errors; "
                                "aborting remaining candidates"
                            )
                            return stats
                    elif result == "SECURITY_REQUIRED":
                        self.stop_reason = "Security challenge encountered"
                        return stats
                    elif result == "AUTH_REQUIRED":
                        self.stop_reason = "Authentication required"
                        return stats

                    self._record_progress_outcome(result)

                except Exception as e:
                    logger.error(f"Error processing job {job.id}: {e}", exc_info=True)
                    stats["errors"].append(str(e))
                    stats["failed"] += 1
                    # An exception is not a valid outcome: it neither resets nor
                    # increments the consecutive runner-ERROR counter.

            return stats
        finally:
            await self._close_shared_runner()

    def _candidate_stage_decisions(self) -> list[dict]:
        """E5-R24: compact per-candidate decision rows for the run record.

        DecisionTracker only ever printed its table, so a run's skip and
        rejection reasons vanished with stdout. The cycle control row keeps
        this trimmed slice (candidate stage only — enqueue's 176 hard-filter
        rows stay out of the payload) as cycle_run_control.last_result.stats.
        """
        rows = self.tracker.decisions[self._candidate_tracker_start:]
        return [
            {
                "job_id": row["job_id"],
                "title": row["title"],
                "outcome": row["outcome"],
                "reason": row["gate_result"],
            }
            for row in rows
        ]

    def _persist_progress(self) -> None:
        """E5-R21: publish the live progress document to the control row."""
        if not self.run_token:
            return
        try:
            from backend.services.autonomous_cycle.coordinator import coordinator

            coordinator.update_progress(self.run_token, dict(self._run_progress))
        except Exception as exc:
            logger.warning(f"Failed to persist run progress: {exc}")

    def _discovery_progress_hook(self, payload: dict) -> None:
        """E5-R23: fold discovery sweep progress into the run progress doc.

        Discovery runs before any application candidates exist, so this is the
        only signal that the single run is still progressing through its
        multi-search sweep. Without it the dashboard showed no movement for the
        whole discovery pass, which read as the cycle having finished and
        restarted.
        """
        if not isinstance(payload, dict):
            return
        progress = self._run_progress
        progress.update(payload)
        search_index = payload.get("search_index")
        search_total = payload.get("search_total")
        if search_index and search_total:
            progress["current_step"] = (
                f"discovery_search_{search_index}_of_{search_total}"
            )
            progress["processed"] = search_index
            progress["remaining"] = max(0, search_total - search_index)
        self._persist_progress()

    def _record_progress_outcome(self, result: str) -> None:
        """E5-R21: fold one finished job's outcome into the progress document."""
        outcome_keys = {
            "APPLIED": "applied",
            "SUBMITTED_UNCONFIRMED": "submitted_unconfirmed",
            "SKIPPED": "skipped",
            "EXTERNAL": "external",
            "NEEDS_ATTENTION": "needs_attention",
            "FAILED": "failed",
            "ERROR": "failed",
        }
        progress = self._run_progress
        key = outcome_keys.get(result)
        if key:
            progress[key] = progress.get(key, 0) + 1
        progress["processed"] = progress.get("processed", 0) + 1
        progress["remaining"] = max(
            0, progress.get("candidates_total", 0) - progress["processed"]
        )
        progress["current_step"] = "job_done"
        self._persist_progress()

    def _make_progress_hook(self) -> Callable[[dict], Any]:
        """E5-R21: runner progress events update the progress document and
        the waiting-for-user flag on the control row."""
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
                    if self.run_token:
                        from backend.services.autonomous_cycle.coordinator import coordinator

                        coordinator.set_waiting(
                            self.run_token, payload.get("pending_question_id")
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
                    if self.run_token:
                        from backend.services.autonomous_cycle.coordinator import coordinator

                        coordinator.clear_waiting(self.run_token)
                elif event == "job_started":
                    self._run_progress.update(
                        {
                            "current_job_id": payload.get("job_id"),
                            "current_step": "starting",
                            "waiting_for_user": False,
                        }
                    )
                elif event == "job_finished":
                    self._run_progress["current_step"] = "job_done"
                elif event == "step":
                    self._run_progress["current_step"] = payload.get("step")
                self._persist_progress()
            except Exception as exc:
                logger.warning(f"Progress hook failed: {exc}")

        return hook

    async def _close_shared_runner(self) -> None:
        """E5-R21: release the shared browser session exactly once per run."""
        runner, self._runner = self._runner, None
        if runner is None:
            return
        try:
            result = runner.close_session()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(f"Failed to close shared application runner: {exc}")

    async def _process_single_job(
        self, db: Session, job: Job, profile: Profile, preferences: JobPreference
    ) -> str:
        """Process a single job through the application flow."""
        # E5-R12: Fallback path for jobs without AI analysis
        # If AI analysis is missing but job passes deterministic filters,
        # allow it to proceed with a conservative default analysis.
        analysis_model = db.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
        ).scalars().first()

        if not analysis_model:
            logger.info(f"Job {job.id} has no AI analysis, using deterministic fallback")
            
            # Run deterministic checks only
            match_engine = MatchEngine(db)
            deterministic_decision = match_engine.evaluate_job_deterministic(job, profile, preferences)
            
            if deterministic_decision.decision.value != "APPLY":
                self.tracker.add_decision(
                    job.id, job.company, job.title, "N/A", False, False, False,
                    "NO_ANALYSIS", deterministic_decision.reason, "SKIPPED"
                )
                return "SKIPPED"
            
            # Create and persist conservative default analysis for fallback path
            # This ensures the ApplicationRunner will find it in the database
            analysis_model = JobAnalysisModel(
                job_id=job.id,
                match_score=50,  # Conservative default score
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
                prompt_version="n/a"
            )
            db.add(analysis_model)
            db.commit()
            db.refresh(analysis_model)
            
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

        application_service = ApplicationService(db)
        allowed, reason = application_service.run_final_safety_gate(
            job, profile, preferences, job_analysis
        )

        if not allowed:
            self.tracker.add_decision(
                job.id, job.company, job.title, "N/A", False, False, False,
                job_analysis.recommendation, reason, "SKIPPED"
            )
            return "SKIPPED"

        if application_service.check_duplicate_application(job):
            self.tracker.add_decision(
                job.id, job.company, job.title, "N/A", False, False, False,
                job_analysis.recommendation, "Duplicate", "SKIPPED"
            )
            return "SKIPPED"

        # E5-R21: reuse the run's shared runner (one browser session for the
        # whole run) when available; direct callers fall back to a fresh
        # runner that owns its own session.
        runner = self._runner or ApplicationRunner(db, self.state_manager, dry_run=self.dry_run)
        app_results = await runner.run_applications([job.id], dry_run=self.dry_run)

        # E5-R16: a logged-out session is an authentication outcome, not an
        # error and not an application-mode decision.
        if app_results.get("auth_required", 0) > 0:
            return "AUTH_REQUIRED"

        # The runner only reports a real per-job outcome when it actually
        # inspected this job. A browser-session startup failure returns zeroed
        # stats and an unusable agent state returns {"error": ...}; neither is a
        # blocked/skipped candidate and neither may be recorded as one.
        reported_outcomes = (
            "applied",
            "submitted_unconfirmed",
            "external",
            "needs_attention",
            "skipped",
            "failed",
            "auth_required",
            "dry_run",
        )
        if app_results.get("error") or not any(app_results.get(k, 0) for k in reported_outcomes):
            reason = app_results.get("error") or "Application runner returned no outcome for this job"
            logger.warning("Job %s produced no application outcome: %s", job.id, reason)
            self.tracker.add_decision(
                job.id, job.company, job.title, "UNKNOWN", False, False, False,
                job_analysis.recommendation, "PASSED", "ERROR"
            )
            return "ERROR"

        app_type = "UNKNOWN"
        outcome = "UNKNOWN"

        if app_results.get("applied", 0) > 0:
            app_type = "NATIVE"
            outcome = "APPLIED"
        elif app_results.get("submitted_unconfirmed", 0) > 0:
            # E5-R5.2: a native submit click without positive confirmation.
            # Recorded truthfully as its own outcome; never "APPLIED".
            app_type = "NATIVE"
            outcome = "SUBMITTED_UNCONFIRMED"
        elif app_results.get("external", 0) > 0:
            app_type = "EXTERNAL"
            outcome = "EXTERNAL"
        elif app_results.get("needs_attention", 0) > 0:
            app_type = "UNKNOWN"
            outcome = "NEEDS_ATTENTION"
        elif app_results.get("skipped", 0) > 0:
            app_type = "UNKNOWN"
            outcome = "SKIPPED"

        self.tracker.add_decision(
            job.id, job.company, job.title, app_type, True, True, True,
            job_analysis.recommendation, "PASSED", outcome
        )

        if app_results.get("applied", 0) > 0:
            return "APPLIED"
        elif app_results.get("submitted_unconfirmed", 0) > 0:
            return "SUBMITTED_UNCONFIRMED"
        elif app_results.get("external", 0) > 0:
            return "EXTERNAL"
        elif app_results.get("needs_attention", 0) > 0:
            return "NEEDS_ATTENTION"
        elif app_results.get("skipped", 0) > 0:
            return "SKIPPED"
        elif app_results.get("failed", 0) > 0:
            return "FAILED"

        return "SKIPPED"
