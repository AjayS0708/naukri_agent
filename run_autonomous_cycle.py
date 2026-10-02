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
from backend.schemas.agent import AgentState
from backend.core.logging import get_logger

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
    ):
        self.max_applications = max_applications
        self.dry_run = dry_run
        self.max_jobs = max_jobs
        self.state_manager = AgentStateManager()
        self.tracker = DecisionTracker()
        self.applications_count = 0
        self.stop_reason: Optional[str] = None

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
            discovery_service = DiscoveryService(self.state_manager)
            await discovery_service.run_discovery(db)

            if self.state_manager.current_state in (AgentState.AUTH_REQUIRED, AgentState.SECURITY_REQUIRED):
                print(f"ERROR: Discovery stopped - {self.state_manager.current_state.value}")
                return 2

            if self.state_manager.current_state == AgentState.CRITICAL_ERROR:
                print("ERROR: Discovery encountered critical error")
                return 3

            # Step 2: Hard filters and enqueue
            print("\n[2/5] Applying hard filters and enqueuing...")
            enqueue_stats = await self._apply_hard_filters_and_enqueue(db, profile, preferences)
            print(f"  Discovered: {enqueue_stats['discovered']}")
            print(f"  Hard filtered: {enqueue_stats['hard_filtered']}")
            print(f"  Queued for AI: {enqueue_stats['queued']}")

            if enqueue_stats["queued"] == 0:
                print("\n0 eligible jobs found")
                self.tracker.print_table()
                return 0

            # Step 3: Process AI queue
            print("\n[3/5] Processing AI queue...")
            ai_stats = await self._process_ai_queue(db, profile)
            print(f"  AI processed: {ai_stats['processed']}")
            print(f"  AI completed: {ai_stats['completed']}")
            print(f"  AI blocked: {ai_stats['quota_blocked']}")

            if ai_stats["completed"] == 0:
                print("\nNo jobs completed AI analysis")
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
            print(f"Total jobs discovered: {enqueue_stats['discovered']}")
            print(f"Hard filtered: {enqueue_stats['hard_filtered']}")
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
        stats = {"discovered": 0, "hard_filtered": 0, "queued": 0, "errors": []}

        # Get discovered jobs
        stmt = select(Job).where(Job.status == "DISCOVERED")
        if self.max_jobs:
            stmt = stmt.limit(self.max_jobs)
        stmt = stmt.order_by(Job.discovered_at.desc())

        jobs = db.execute(stmt).scalars().all()
        stats["discovered"] = len(jobs)

        if not jobs:
            return stats

        match_engine = MatchEngine(db)
        ai_queue_service = AIQueueService(db)

        for job in jobs:
            # Skip excluded job
            if job.external_job_id == EXCLUDED_JOB_ID:
                stats["hard_filtered"] += 1
                self.tracker.add_decision(
                    job.id, job.company, job.title, "EXCLUDED", False, False, False, "N/A", "N/A", "EXCLUDED"
                )
                continue

            # Check if already analyzed or queued
            existing_analysis = db.execute(
                select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
            ).scalars().first()

            if existing_analysis:
                stats["hard_filtered"] += 1
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
                queue_item = ai_queue_service.enqueue_job(
                    job_id=job.id,
                    priority=match_decision.match_score or 50,
                    priority_reason="Hard filters passed, ready for AI analysis",
                    queue_source="AUTONOMOUS_CYCLE",
                )

                if queue_item:
                    stats["queued"] += 1
                    self.tracker.add_decision(
                        job.id, job.company, job.title, "N/A", salary_pass, experience_pass, employment_pass, "PENDING", "PENDING", "QUEUED"
                    )
            else:
                stats["hard_filtered"] += 1
                self.tracker.add_decision(
                    job.id, job.company, job.title, "N/A", salary_pass, experience_pass, employment_pass, "N/A", match_decision.reason, "HARD_FILTERED"
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
        ).order_by(Job.discovered_at.desc())

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

        # Run final safety gate
        application_service = ApplicationService(db)
        allowed, reason = application_service.run_final_safety_gate(
            job, profile, preferences,
            type("obj", (object,), {
                "recommendation": analysis_model.recommendation,
                "match_score": analysis_model.match_score,
            })()
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

    args = parser.parse_args()

    cycle = AutonomousCycle(
        max_applications=args.max_applications,
        dry_run=args.dry_run,
        max_jobs=args.max_jobs,
    )

    exit_code = asyncio.run(cycle.run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
