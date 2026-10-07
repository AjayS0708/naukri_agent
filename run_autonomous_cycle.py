#!/usr/bin/env python3
"""
Autonomous Cycle Command - CHECKPOINT C

This script runs the complete autonomous job application cycle by calling the existing
services in sequence with the required constraints:
discovery -> hard filters -> AI queue -> Gemini -> final safety gate -> ApplicationRunner

It supports:
- --max-applications N: limit on real applications (default 1)
- --dry-run: discovery and analysis only, no Apply clicks or application records
- --max-jobs N: cap on jobs inspected per run
--max-cards N: cap on cards scanned per run (default 150)

No input() prompts. Exit code 0 on normal completion, non-zero on AUTH/SECURITY/critical stop.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

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
    """Orchestrates the autonomous application cycle by calling existing services."""

    def __init__(
        self,
        max_applications: int = 1,
        dry_run: bool = False,
        max_jobs: Optional[int] = None,
        max_cards: int = 150,
    ):
        self.max_applications = max_applications
        self.dry_run = dry_run
        self.max_jobs = max_jobs
        self.max_cards = max_cards
        self.state_manager = AgentStateManager()
        self.tracker = DecisionTracker()
        self.applications_count = 0
        self.stop_reason: Optional[str] = None
        self.current_discovery_run: Optional[DiscoveryRun] = None

    async def run(self) -> int:
        """Run the autonomous cycle. Returns exit code."""
        db = SessionLocal()
        try:
            # Verify profile and preferences exist
            profile = db.execute(select(Profile)).scalars().first()
            if not profile or not profile.confirmed:
                print("ERROR: No confirmed profile found. Please configure profile first.")
                return 1

            preferences = db.execute(select(JobPreference)).scalars().first()
            if not preferences:
                print("ERROR: No job preferences found. Please configure preferences first.")
                return 1

            print(f"\nStarting autonomous cycle (dry_run={self.dry_run}, max_applications={self.max_applications}, max_jobs={self.max_jobs})")
            print(f"Profile: {profile.data.get('name', 'Unknown')}")
            print(f"Job titles: {', '.join(preferences.job_titles or [])}")
            print(f"Locations: {', '.join(preferences.locations or [])}")

            # Check application limits before starting
            limit_service = ApplicationLimitService(db)
            limit_check = limit_service.check_limits()
            if not limit_check.allowed:
                print(f"ERROR: Application limits reached: {limit_check.reason}")
                return 2

            # Step 1: Discovery
            print("\n[1/5] Running discovery...")
            discovery_service = DiscoveryService(self.state_manager, max_cards=self.max_cards)
            await discovery_service.run_discovery(db)

            if self.state_manager.current_state in (AgentState.AUTH_REQUIRED, AgentState.SECURITY_REQUIRED):
                print(f"ERROR: Discovery stopped - {self.state_manager.current_state.value}")
                return 2

            if self.state_manager.current_state == AgentState.CRITICAL_ERROR:
                print("ERROR: Discovery encountered critical error")
                return 3

            # Capture the current discovery run to ensure we only process jobs from THIS run
            self.current_discovery_run = db.execute(
                select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc())
            ).scalars().first()

            if not self.current_discovery_run:
                print("ERROR: No discovery run record found")
                return 3

            # Check if discovery actually found any jobs in this run
            if self.current_discovery_run.jobs_discovered == 0:
                print(f"ERROR: Discovery found 0 jobs in current run (status: {self.current_discovery_run.status})")
                if self.current_discovery_run.error_message:
                    print(f"Discovery error: {self.current_discovery_run.error_message}")
                print("Cycle stopped: No current jobs discovered")
                return 3

            print(f"Discovery run completed: {self.current_discovery_run.jobs_discovered} jobs discovered (status: {self.current_discovery_run.status})")

            # Step 2: Hard filters and enqueue
            print("\n[2/5] Applying hard filters and enqueuing...")
            enqueue_stats = await self._apply_hard_filters_and_enqueue(db, profile, preferences)
            print(f"  Discovered: {enqueue_stats['discovered']}")
            print(f"  Hard filtered: {enqueue_stats['hard_filtered']}")
            print(f"  Pre-analyzed (existing): {enqueue_stats['pre_analyzed']}")
            print(f"  Skipped on experience: {enqueue_stats['skipped_experience']}")
            print(f"  Skipped non-IT: {enqueue_stats['skipped_non_it']}")
            print(f"  Capped by max_jobs: {enqueue_stats['capped']}")
            print(f"  Queued for AI: {enqueue_stats['queued']}")

            # Only stop if nothing was newly queued AND no pre-analyzed candidates exist
            # in the current run. Pre-existing analyses from prior runs on the same jobs
            # are valid — _run_applications already enforces current_run_job_ids scope.
            if enqueue_stats["queued"] == 0 and enqueue_stats["pre_analyzed"] == 0:
                print("\n0 eligible jobs found")
                self.tracker.print_table()
                return 0

            # Step 3: Process AI queue — only when new items were freshly queued
            ai_stats: dict = {"processed": 0, "completed": 0, "quota_blocked": 0, "errors": []}
            if enqueue_stats["queued"] > 0:
                print("\n[3/5] Processing AI queue...")
                ai_stats = await self._process_ai_queue(db, profile)
                print(f"  AI processed: {ai_stats['processed']}")
                print(f"  AI completed: {ai_stats['completed']}")
                print(f"  AI blocked: {ai_stats['quota_blocked']}")
            else:
                print("\n[3/5] Skipping AI queue (all current-run candidates already analyzed)")

            # Count current-run jobs that have a completed analysis (covers both
            # freshly-processed items and pre-existing analyses from earlier runs).
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
                print("\nNo jobs have a completed AI analysis in the current run")
                self.tracker.print_table()
                return 0

            # Step 4: Run applications with max-applications limit
            print("\n[4/5] Running applications...")
            app_stats = await self._run_applications(db, profile, preferences)
            print(f"  Candidates: {app_stats['candidates']}")
            print(f"  Applied: {app_stats['applied']}")
            print(f"  Skipped: {app_stats['skipped']}")
            print(f"  External: {app_stats['external']}")
            print(f"  Needs attention: {app_stats['needs_attention']}")

            # Step 5: Print summary
            print("\n[5/5] Cycle complete")
            self.tracker.print_table()

            print("\nSUMMARY")
            print("=" * 60)
            print(f"max_applications: {self.max_applications}")
            print(f"Gemini candidate budget: {self.max_applications * 2}")
            print(f"Cards scanned: {enqueue_stats['discovered']}")
            print(f"Total jobs discovered: {enqueue_stats['discovered']}")
            print(f"Skipped on experience: {enqueue_stats['skipped_experience']}")
            print(f"Skipped non-IT: {enqueue_stats['skipped_non_it']}")
            print(f"Hard filtered: {enqueue_stats['hard_filtered']}")
            print(f"Pre-analyzed (existing): {enqueue_stats['pre_analyzed']}")
            print(f"Capped by max_jobs: {enqueue_stats['capped']}")
            print(f"Queued for AI: {enqueue_stats['queued']}")
            print(f"AI processed: {ai_stats['processed']}")
            print(f"AI completed: {ai_stats['completed']}")
            print(f"Application candidates: {app_stats['candidates']}")
            print(f"Applied: {app_stats['applied']}")
            print(f"Skipped: {app_stats['skipped']}")
            print(f"External: {app_stats['external']}")
            print(f"Needs attention: {app_stats['needs_attention']}")
            print(f"Failed: {app_stats['failed']}")
            print("=" * 60)

            if self.stop_reason:
                print(f"\nCycle stopped: {self.stop_reason}")
                return 2 if "AUTH" in self.stop_reason or "SECURITY" in self.stop_reason else 3

            return 0

        except Exception as e:
            logger.error(f"Autonomous cycle failed: {e}", exc_info=True)
            print(f"ERROR: {e}")
            return 3
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
        # This prevents processing stale/historical DB jobs when current discovery fails
        if not self.current_discovery_run:
            print("ERROR: No current discovery run available for filtering")
            return stats

        # Parse job IDs from current run
        current_run_job_ids = []
        if self.current_discovery_run.current_run_job_ids:
            try:
                current_run_job_ids = [int(jid) for jid in self.current_discovery_run.current_run_job_ids.split(",")]
            except (ValueError, AttributeError):
                pass

        if not current_run_job_ids:
            # Fallback to timestamp comparison if job IDs not available (shouldn't happen)
            print("WARNING: No current run job IDs available, using timestamp fallback")
            stmt = select(Job).where(
                Job.status == "DISCOVERED",
                Job.discovered_at >= self.current_discovery_run.started_at
            )
        else:
            # Use job IDs from current discovery run
            stmt = select(Job).where(
                Job.id.in_(current_run_job_ids)
            )

        # Do NOT apply max_jobs here - apply it AFTER hard filtering
        stmt = stmt.order_by(Job.discovered_at.desc())

        jobs = db.execute(stmt).scalars().all()
        stats["discovered"] = len(jobs)

        if not jobs:
            return stats

        match_engine = MatchEngine(db)
        ai_queue_service = AIQueueService(db)

        # Track eligible jobs to cap at max_jobs AFTER hard filtering
        eligible_count = 0

        # Collect eligible jobs first for deterministic selection
        eligible_jobs = []

        for job in jobs:
            # Check if we've reached max_jobs cap for eligible jobs
            if self.max_jobs and eligible_count >= self.max_jobs:
                # Still count remaining jobs as discovered but mark as capped
                stats["capped"] += 1
                self.tracker.add_decision(
                    job.id, job.company, job.title, "N/A", False, False, False, "N/A", "max_jobs cap", "CAPPED"
                )
                continue
            # Skip excluded job
            if job.external_job_id == EXCLUDED_JOB_ID:
                stats["hard_filtered"] += 1
                self.tracker.add_decision(
                    job.id, job.company, job.title, "EXCLUDED", False, False, False, "N/A", "N/A", "EXCLUDED"
                )
                continue

            # Check if already analyzed — count separately so the cycle can proceed
            # to applications even when all current-run jobs have prior analyses.
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

            # Evaluate hard filters
            match_decision = match_engine.evaluate_job(job, profile, preferences)

            # Track filter results
            salary_pass = match_decision.decision.value == "APPLY" or "salary" not in match_decision.reason.lower()
            experience_pass = match_decision.decision.value == "APPLY" or "experience" not in match_decision.reason.lower()
            employment_pass = match_decision.decision.value == "APPLY" or "employment" not in match_decision.reason.lower()

            if match_decision.decision.value == "APPLY":
                # Collect eligible job for deterministic selection
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

        # D6.1: Bounded Gemini look-ahead for multi-application runs
        # Separate Gemini candidate budget from actual application limit
        # max_gemini_candidates = max_applications * 2 provides backup candidates
        # while keeping Gemini usage bounded and controlled
        if eligible_jobs:
            # Sort by match_score descending, then by discovered_at descending (most recent)
            eligible_jobs.sort(key=lambda x: (-x["match_score"], x["job"].discovered_at or datetime.min), reverse=False)

            # D6.1: Bounded Gemini candidate budget (look-ahead)
            # Enqueue up to max_applications * 2 candidates to provide backup options
            # while preventing uncontrolled Gemini usage
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
                    self.tracker.add_decision(
                        selected["job"].id, selected["job"].company, selected["job"].title, "N/A",
                        selected["salary_pass"], selected["experience_pass"], selected["employment_pass"],
                        "PENDING", "PENDING", "QUEUED (SELECTED)"
                    )

            # Mark remaining eligible jobs as capped for quota safety
            for other in capped_jobs:
                stats["capped"] += 1
                self.tracker.add_decision(
                    other["job"].id, other["job"].company, other["job"].title, "N/A",
                    other["salary_pass"], other["experience_pass"], other["employment_pass"],
                    "N/A", f"Gemini budget cap (budget={gemini_budget})", "CAPPED"
                )

        return stats

    async def _process_ai_queue(self, db: Session, profile: Profile) -> dict:
        """Process AI queue items."""
        stats = {"processed": 0, "completed": 0, "quota_blocked": 0, "errors": []}

        ai_queue_service = AIQueueService(db)
        ai_queue_service.recover_stale_items()

        profile_context = str(profile.data) if profile and profile.data else ""

        # Process up to max_jobs or all if not specified
        max_items = self.max_jobs if self.max_jobs else 50
        items_processed = 0

        while items_processed < max_items:
            next_item = ai_queue_service.get_next_item()
            if not next_item:
                break

            try:
                result = ai_queue_service.process_item(next_item.id, profile_context)
                stats["processed"] += 1

                if result.status.value == "COMPLETED":
                    stats["completed"] += 1
                elif result.status.value == "QUOTA_BLOCKED":
                    stats["quota_blocked"] += 1
                    break

                items_processed += 1

            except Exception as e:
                stats["errors"].append(str(e))
                items_processed += 1

        return stats

    async def _run_applications(
        self, db: Session, profile: Profile, preferences: JobPreference
    ) -> dict:
        """Run applications for eligible jobs with max-applications limit."""
        stats = {"candidates": 0, "applied": 0, "skipped": 0, "external": 0, "needs_attention": 0, "failed": 0, "errors": []}

        # Find jobs with completed AI analysis
        stmt = select(Job).where(
            Job.id.in_(select(JobAnalysisModel.job_id))
        ).outerjoin(
            Application, Application.job_id == Job.id
        ).where(
            (Application.id == None) | (Application.status == ApplicationStatus.SKIPPED.value)
        )

        # Restrict to current discovery run to avoid processing stale historical candidates
        if self.current_discovery_run and self.current_discovery_run.current_run_job_ids:
            try:
                current_run_job_ids = [int(jid) for jid in self.current_discovery_run.current_run_job_ids.split(",")]
                stmt = stmt.where(Job.id.in_(current_run_job_ids))
            except (ValueError, AttributeError):
                # If parsing fails, return no candidates to be safe
                print("WARNING: Failed to parse current_run_job_ids, returning no application candidates")
                return stats
        else:
            # No current discovery run or no job IDs - return no candidates to be safe
            print("WARNING: No current discovery run or current_run_job_ids, returning no application candidates")
            return stats

        stmt = stmt.order_by(Job.discovered_at.desc())

        if self.max_jobs:
            stmt = stmt.limit(self.max_jobs)

        eligible_jobs = db.execute(stmt).scalars().all()
        stats["candidates"] = len(eligible_jobs)

        if not eligible_jobs:
            return stats

        # Process jobs sequentially with max-applications limit
        for job in eligible_jobs:
            if self.applications_count >= self.max_applications:
                self.stop_reason = f"Reached max-applications limit ({self.max_applications})"
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
        # Get AI analysis
        analysis_model = db.execute(
            select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
        ).scalars().first()

        if not analysis_model:
            return "SKIPPED"

        # Construct proper JobAnalysis object from persisted analysis_model
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

        # Run final safety gate
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

        # Check duplicate
        if application_service.check_duplicate_application(job):
            self.tracker.add_decision(
                job.id, job.company, job.title, "N/A", False, False, False,
                analysis_model.recommendation or "N/A", "Duplicate", "SKIPPED"
            )
            return "SKIPPED"

        # Check limits
        limit_service = ApplicationLimitService(db)
        limit_check = limit_service.check_limits()
        if not limit_check.allowed:
            self.stop_reason = f"Application limits reached: {limit_check.reason}"
            self.tracker.add_decision(
                job.id, job.company, job.title, "N/A", False, False, False,
                analysis_model.recommendation or "N/A", limit_check.reason, "SKIPPED"
            )
            return "SKIPPED"

        # Run ApplicationRunner for this single job with dry_run flag
        runner = ApplicationRunner(db, self.state_manager, dry_run=self.dry_run)
        app_results = await runner.run_applications([job.id], dry_run=self.dry_run)

        # Determine application type and outcome
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


def main():
    parser = argparse.ArgumentParser(description="Run autonomous job application cycle")
    parser.add_argument(
        "--max-applications",
        type=int,
        default=1,
        help="Maximum number of real applications to perform (default: 1)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discovery and analysis only, no Apply clicks or application records"
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Cap on jobs inspected per run (default: unlimited)"
    )
    parser.add_argument(
        "--max-cards",
        type=int,
        default=150,
        help="Maximum number of search cards to scan (default: 150)",
    )

    args = parser.parse_args()

    cycle = AutonomousCycle(
        max_applications=args.max_applications,
        dry_run=args.dry_run,
        max_jobs=args.max_jobs,
        max_cards=args.max_cards,
    )

    exit_code = asyncio.run(cycle.run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
