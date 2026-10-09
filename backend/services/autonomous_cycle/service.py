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
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import case, select

from backend.database.database import SessionLocal
from backend.services.agent_state import AgentStateManager
from backend.services.discovery.service import DiscoveryService
from backend.services.matching.engine import MatchEngine
from backend.services.gemini.queue import AIQueueService
from backend.services.applications.runner import ApplicationRunner
from backend.services.applications.limits import ApplicationLimitService
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
        max_applications: int = 1,
        dry_run: bool = False,
        max_jobs: Optional[int] = None,
        max_cards: int = 150,
        enable_cli_output: bool = True,
    ):
        self.max_applications = max_applications
        self.dry_run = dry_run
        self.max_jobs = max_jobs
        self.max_cards = max_cards
        self.enable_cli_output = enable_cli_output
        self.state_manager = AgentStateManager()
        self.tracker = DecisionTracker()
        self.applications_count = 0
        self.stop_reason: Optional[str] = None
        self.stop_is_normal = False
        self.current_discovery_run: Optional[DiscoveryRun] = None

    def _print(self, message: str):
        """Print message to stdout if CLI output is enabled."""
        if self.enable_cli_output:
            print(message)

    def _terminal_outcome(self) -> tuple[int, str]:
        """Map the recorded stop reason to the documented terminal contract.

        README, MASTER_PRD and ARCHITECTURE all state: "Exit code 0 on normal
        completion, non-zero on AUTH/SECURITY/critical stop." Reaching a
        configured application limit is a normal completion, not a failure.
        """
        if not self.stop_reason or self.stop_is_normal:
            return 0, "COMPLETED"
        reason = self.stop_reason.upper()
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

            self._print(f"\nStarting autonomous cycle (dry_run={self.dry_run}, max_applications={self.max_applications}, max_jobs={self.max_jobs})")
            self._print(f"Profile: {profile.data.get('name', 'Unknown')}")
            self._print(f"Job titles: {', '.join(preferences.job_titles or [])}")
            self._print(f"Locations: {', '.join(preferences.locations or [])}")

            # Check application limits before starting
            limit_service = ApplicationLimitService(db)
            limit_check = limit_service.check_limits()
            if not limit_check.allowed:
                self._print(f"ERROR: Application limits reached: {limit_check.reason}")
                return {"exit_code": 2, "run_id": None, "status": "FAILED", "stats": {}}

            # Step 1: Discovery
            self._print("\n[1/5] Running discovery...")
            discovery_service = DiscoveryService(self.state_manager, max_cards=self.max_cards)
            await discovery_service.run_discovery(db)

            if self.state_manager.current_state in (AgentState.AUTH_REQUIRED, AgentState.SECURITY_REQUIRED):
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

            # Step 4: Run applications with max-applications limit
            self._print("\n[4/5] Running applications...")
            app_stats = await self._run_applications(db, profile, preferences)
            self._print(f"  Candidates: {app_stats['candidates']}")
            self._print(f"  Applied: {app_stats['applied']}")
            self._print(f"  Skipped: {app_stats['skipped']}")
            self._print(f"  External: {app_stats['external']}")
            self._print(f"  Needs attention: {app_stats['needs_attention']}")

            # Step 5: Print summary
            self._print("\n[5/5] Cycle complete")
            self.tracker.print_table()

            self._print("\nSUMMARY")
            self._print("=" * 60)
            self._print(f"max_applications: {self.max_applications}")
            self._print(f"Gemini candidate budget: {self.max_applications * 2}")
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

            if existing_queue:
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
            # Freshness-first: newest grounded posting dates win, then the
            # most recently discovered jobs, then the highest match score.
            # Jobs with an unknown posting date never outrank known-fresh jobs.
            eligible_jobs.sort(
                key=lambda x: (
                    job_freshness_key(x["job"]),
                    -x["match_score"],
                )
            )

            gemini_budget = max(1, self.max_applications * 2)
            selected_jobs = eligible_jobs[:gemini_budget]
            capped_jobs = eligible_jobs[gemini_budget:]

            for selected in selected_jobs:
                queue_item = ai_queue_service.enqueue_job(
                    job_id=selected["job"].id,
                    priority=selected["match_score"],
                    priority_reason=f"Selected as top candidate (Gemini budget={gemini_budget}, max_applications={self.max_applications})",
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

            for other in capped_jobs:
                stats["capped"] += 1
                self.tracker.add_decision(
                    other["job"].id, other["job"].company, other["job"].title, "N/A",
                    other["salary_pass"], other["experience_pass"], other["employment_pass"],
                    "N/A", f"D6.2 Gemini budget cap (budget={gemini_budget})", "CAPPED"
                )

        stats["enqueued_queue_item_ids"] = enqueued_queue_item_ids
        return stats

    async def _process_ai_queue(self, db: Session, profile: Profile, enqueued_queue_item_ids: list[int]) -> dict:
        """Process AI queue items enqueued by this autonomous cycle only."""
        stats = {"processed": 0, "completed": 0, "quota_blocked": 0, "errors": []}

        ai_queue_service = AIQueueService(db)
        ai_queue_service.recover_stale_items()

        profile_context = str(profile.data) if profile and profile.data else ""

        for queue_item_id in enqueued_queue_item_ids:
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
        """Run applications for eligible jobs with max-applications limit."""
        stats = {"candidates": 0, "applied": 0, "skipped": 0, "external": 0, "needs_attention": 0, "failed": 0, "errors": []}

        stmt = select(Job).where(
            Job.id.in_(select(JobAnalysisModel.job_id))
        ).outerjoin(
            Application, Application.job_id == Job.id
        ).where(
            (Application.id == None) | (Application.status == ApplicationStatus.SKIPPED.value)
        )

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

        # Freshness-first: process the most recently posted jobs first, and
        # place jobs with an unknown posting date after all known-fresh jobs.
        stmt = stmt.order_by(
            case((Job.posted_at.is_(None), 1), else_=0),
            Job.posted_at.desc(),
            Job.discovered_at.desc(),
        )

        if self.max_jobs:
            stmt = stmt.limit(self.max_jobs)

        eligible_jobs = db.execute(stmt).scalars().all()
        stats["candidates"] = len(eligible_jobs)

        if not eligible_jobs:
            return stats

        for job in eligible_jobs:
            if self.applications_count >= self.max_applications:
                self.stop_reason = f"Reached max-applications limit ({self.max_applications})"
                self.stop_is_normal = True
                break

            try:
                result = await self._process_single_job(db, job, profile, preferences)

                if result == "APPLIED":
                    stats["applied"] += 1
                    self.applications_count += 1
                elif result == "SKIPPED":
                    stats["skipped"] += 1
                elif result == "EXTERNAL":
                    stats["external"] += 1
                elif result == "NEEDS_ATTENTION":
                    stats["needs_attention"] += 1
                elif result == "FAILED":
                    stats["failed"] += 1
                elif result == "ERROR":
                    # The runner never inspected this job (browser session or
                    # agent state unavailable). Stop instead of attempting the
                    # remaining candidates, which would only produce bogus
                    # skip outcomes while the runtime stays unusable.
                    stats["failed"] += 1
                    self.stop_reason = "Application execution unavailable for remaining candidates"
                    return stats
                elif result == "SECURITY_REQUIRED":
                    self.stop_reason = "Security challenge encountered"
                    return stats
                elif result == "AUTH_REQUIRED":
                    self.stop_reason = "Authentication required"
                    return stats

            except Exception as e:
                logger.error(f"Error processing job {job.id}: {e}", exc_info=True)
                stats["errors"].append(str(e))
                stats["failed"] += 1

        return stats

    async def _process_single_job(
        self, db: Session, job: Job, profile: Profile, preferences: JobPreference
    ) -> str:
        """Process a single job through the application flow."""
        analysis_model = db.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
        ).scalars().first()

        if not analysis_model:
            return "SKIPPED"

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
                analysis_model.recommendation or "N/A", reason, "SKIPPED"
            )
            return "SKIPPED"

        if application_service.check_duplicate_application(job):
            self.tracker.add_decision(
                job.id, job.company, job.title, "N/A", False, False, False,
                analysis_model.recommendation or "N/A", "Duplicate", "SKIPPED"
            )
            return "SKIPPED"

        limit_service = ApplicationLimitService(db)
        limit_check = limit_service.check_limits()
        if not limit_check.allowed:
            self.stop_reason = f"Application limits reached: {limit_check.reason}"
            self.tracker.add_decision(
                job.id, job.company, job.title, "N/A", False, False, False,
                analysis_model.recommendation or "N/A", limit_check.reason, "SKIPPED"
            )
            return "SKIPPED"

        runner = ApplicationRunner(db, self.state_manager, dry_run=self.dry_run)
        app_results = await runner.run_applications([job.id], dry_run=self.dry_run)

        # The runner only reports a real per-job outcome when it actually
        # inspected this job. A browser-session startup failure returns zeroed
        # stats and an unusable agent state returns {"error": ...}; neither is a
        # blocked/skipped candidate and neither may be recorded as one.
        reported_outcomes = ("applied", "external", "needs_attention", "skipped", "failed", "dry_run")
        if app_results.get("error") or not any(app_results.get(k, 0) for k in reported_outcomes):
            reason = app_results.get("error") or "Application runner returned no outcome for this job"
            logger.warning("Job %s produced no application outcome: %s", job.id, reason)
            self.tracker.add_decision(
                job.id, job.company, job.title, "UNKNOWN", False, False, False,
                analysis_model.recommendation or "N/A", "PASSED", "ERROR"
            )
            return "ERROR"

        app_type = "UNKNOWN"
        outcome = "UNKNOWN"

        if app_results.get("applied", 0) > 0:
            app_type = "NATIVE"
            outcome = "APPLIED"
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
            analysis_model.recommendation or "N/A", "PASSED", outcome
        )

        if app_results.get("applied", 0) > 0:
            return "APPLIED"
        elif app_results.get("external", 0) > 0:
            return "EXTERNAL"
        elif app_results.get("needs_attention", 0) > 0:
            return "NEEDS_ATTENTION"
        elif app_results.get("skipped", 0) > 0:
            return "SKIPPED"
        elif app_results.get("failed", 0) > 0:
            return "FAILED"

        return "SKIPPED"
