from datetime import datetime, UTC
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.core.scheduler import JobScheduler
from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.models.scheduler import SchedulerConfig, utc_now
from backend.models.ai_queue import AIQueueItem
from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.services.discovery.service import DiscoveryService
from backend.services.agent_state import AgentStateManager
from backend.services.applications.limits import ApplicationLimitService
from backend.services.applications.runner import ApplicationRunner
from backend.services.gemini.queue import AIQueueService
from backend.services.gemini.provider import GeminiProvider
from backend.services.matching.engine import MatchEngine
from backend.database.database import SessionLocal

logger = get_logger(__name__)


class SchedulerService:
    """
    Service layer for scheduler management.
    
    Responsibilities:
    - Manage scheduler lifecycle with persistence
    - Load/save scheduler configuration from database
    - Orchestrate scheduled discovery runs
    - Provide scheduler status and control
    
    The scheduler does NOT implement business rules - it only handles timing.
    It integrates with existing services (DiscoveryService) for actual work.
    """
    
    def __init__(
        self,
        state_manager: AgentStateManager,
        discovery_service: DiscoveryService
    ):
        self.state_manager = state_manager
        self.discovery_service = discovery_service
        self.settings = get_settings()
        
        self._scheduler: Optional[JobScheduler] = None
        self._config: Optional[SchedulerConfig] = None
        self._ai_queue_service: Optional[AIQueueService] = None
        self._gemini_provider: Optional[GeminiProvider] = None
        
    def initialize(self, db: Session) -> None:
        """Initialize scheduler with configuration from database or defaults."""
        self._config = db.execute(select(SchedulerConfig)).scalars().first()
        
        if not self._config:
            self._config = SchedulerConfig(
                enabled=self.settings.scheduler_enabled,
                interval_minutes=self.settings.scheduler_interval_minutes,
                max_instances=self.settings.scheduler_max_instances
            )
            db.add(self._config)
            db.commit()
            db.refresh(self._config)
            logger.info("scheduler_config_created", extra={"interval_minutes": self._config.interval_minutes})
        else:
            logger.info("scheduler_config_loaded", extra={"interval_minutes": self._config.interval_minutes})
            
        self._scheduler = JobScheduler(
            interval_minutes=self._config.interval_minutes,
            max_instances=self._config.max_instances
        )
        
        self._scheduler.set_task_callback(self._run_discovery_task)
        
        # Initialize Gemini provider
        self._gemini_provider = GeminiProvider()
    async def start(self, db: Session) -> None:
        """Start the scheduler."""
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized")
            
        if not self._config:
            raise RuntimeError("Scheduler configuration not loaded")
            
        if not self._config.enabled:
            logger.warning("scheduler_disabled_in_config")
            return
            
        if self._config.is_running:
            logger.warning("scheduler_already_running")
            return
            
        await self._scheduler.start()
        
        self._config.is_running = True
        self._config.is_paused = False
        self._config.updated_at = utc_now()
        db.commit()
        
        logger.info("scheduler_service_started")
        
    async def stop(self, db: Session) -> None:
        """Stop the scheduler."""
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized")
            
        if not self._config:
            raise RuntimeError("Scheduler configuration not loaded")
            
        if not self._config.is_running:
            logger.warning("scheduler_not_running")
            return
            
        await self._scheduler.stop()
        
        self._config.is_running = False
        self._config.is_paused = False
        self._config.next_run_at = None
        self._config.updated_at = utc_now()
        db.commit()
        
        logger.info("scheduler_service_stopped")
        
    async def pause(self, db: Session) -> None:
        """Pause the scheduler."""
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized")
            
        if not self._config:
            raise RuntimeError("Scheduler configuration not loaded")
            
        if not self._config.is_running:
            logger.warning("scheduler_not_running")
            return
            
        if self._config.is_paused:
            logger.warning("scheduler_already_paused")
            return
            
        await self._scheduler.pause()
        
        self._config.is_paused = True
        self._config.next_run_at = None
        self._config.updated_at = utc_now()
        db.commit()
        
        logger.info("scheduler_service_paused")
        
    async def resume(self, db: Session) -> None:
        """Resume the scheduler."""
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized")
            
        if not self._config:
            raise RuntimeError("Scheduler configuration not loaded")
            
        if not self._config.is_running:
            logger.warning("scheduler_not_running")
            return
            
        if not self._config.is_paused:
            logger.warning("scheduler_not_paused")
            return
            
        await self._scheduler.resume()
        
        self._config.is_paused = False
        self._config.updated_at = utc_now()
        db.commit()
        
        logger.info("scheduler_service_resumed")
        
    async def update_interval(self, db: Session, interval_minutes: int) -> None:
        """Update the scheduler interval."""
        if not self._scheduler:
            raise RuntimeError("Scheduler not initialized")
            
        if not self._config:
            raise RuntimeError("Scheduler configuration not loaded")
            
        if interval_minutes < 1:
            raise ValueError("Interval must be at least 1 minute")
            
        await self._scheduler.update_interval(interval_minutes)
        
        self._config.interval_minutes = interval_minutes
        self._config.updated_at = utc_now()
        db.commit()
        
        logger.info("scheduler_interval_updated", extra={"interval_minutes": interval_minutes})
        
    async def update_enabled(self, db: Session, enabled: bool) -> None:
        """Update the scheduler enabled state."""
        if not self._config:
            raise RuntimeError("Scheduler configuration not loaded")
            
        self._config.enabled = enabled
        self._config.updated_at = utc_now()
        db.commit()
        
        if enabled and not self._config.is_running:
            await self.start(db)
        elif not enabled and self._config.is_running:
            await self.stop(db)
            
        logger.info("scheduler_enabled_updated", extra={"enabled": enabled})
        
    def get_status(self) -> dict:
        """Get current scheduler status."""
        if not self._scheduler:
            return {
                "is_running": False,
                "is_paused": False,
                "interval_minutes": self.settings.scheduler_interval_minutes,
                "max_instances": self.settings.scheduler_max_instances,
                "last_run_at": None,
                "next_run_at": None,
                "enabled": self.settings.scheduler_enabled
            }
            
        status = self._scheduler.get_status()
        
        if self._config:
            status["enabled"] = self._config.enabled
            status["last_run_at"] = self._config.last_run_at
            status["next_run_at"] = self._config.next_run_at
            
        return status
        
    async def shutdown(self) -> None:
        """Shutdown the scheduler during application shutdown."""
        if self._scheduler and self._scheduler._is_running:
            await self._scheduler.stop()
            logger.info("scheduler_shutdown_complete")
            
    async def _run_discovery_task(self) -> None:
        """
        Execute complete Phase 9A scheduler automation loop.

        This is the main orchestration method called by the scheduler core.
        It implements the full flow:
        1. Discover jobs
        2. Persist discovered jobs
        3. Evaluate deterministic matching (hard filters)
        4. Enqueue eligible jobs to AI queue
        5. Process AI queue items
        6. Pass completed analysis to ApplicationRunner
        7. Record cycle statistics

        Failure isolation: Single job failures do not kill the entire cycle.
        """
        if not self.state_manager:
            logger.warning("scheduler_no_state_manager")
            return

        current_state = self.state_manager.current_state

        if current_state.value in ["RUNNING", "SEARCHING", "FILTERING", "APPLYING"]:
            logger.info("scheduler_skip_discovery_agent_busy", extra={"state": current_state.value})
            return

        # Check application limits before starting discovery
        db = SessionLocal()
        try:
            limit_service = ApplicationLimitService(db)
            limit_check = limit_service.check_limits()

            if not limit_check.allowed:
                logger.info("scheduler_skip_discovery_limits_reached", extra={
                    "reason": limit_check.reason,
                    "hourly_used": limit_check.hourly_used,
                    "daily_used": limit_check.daily_used
                })
                return
        finally:
            db.close()

        # Initialize cycle statistics
        cycle_stats = {
            "discovered": 0,
            "hard_filtered": 0,
            "queued": 0,
            "ai_processed": 0,
            "ai_blocked": 0,
            "application_candidates": 0,
            "applied": 0,
            "skipped": 0,
            "needs_attention": 0,
            "failed": 0,
            "errors": []
        }

        db = SessionLocal()
        try:
            logger.info("scheduler_phase_9a_cycle_starting")

            # ===== STEP 1-2: DISCOVER & PERSIST JOBS =====
            logger.info("scheduler_step_1_discovery")
            await self.discovery_service.run_discovery(db)

            if self._config:
                self._config.last_run_at = utc_now()
                db.commit()

            logger.info("scheduler_discovery_completed")

            # ===== STEP 3: APPLY DETERMINISTIC HARD FILTERS & ENQUEUE =====
            logger.info("scheduler_step_2_hard_filter_and_enqueue")
            enqueue_stats = await self._apply_hard_filters_and_enqueue(db)
            cycle_stats["discovered"] = enqueue_stats["discovered"]
            cycle_stats["hard_filtered"] = enqueue_stats["hard_filtered"]
            cycle_stats["queued"] = enqueue_stats["queued"]
            cycle_stats["errors"].extend(enqueue_stats.get("errors", []))

            # ===== STEP 4: PROCESS AI QUEUE =====
            logger.info("scheduler_step_3_process_ai_queue")
            ai_stats = await self._process_ai_queue_items(db)
            cycle_stats["ai_processed"] = ai_stats["processed"]
            cycle_stats["ai_blocked"] = ai_stats["quota_blocked"]
            cycle_stats["errors"].extend(ai_stats.get("errors", []))

            # ===== STEP 5: INVOKE APPLICATION RUNNER =====
            logger.info("scheduler_step_4_invoke_application_runner")
            app_stats = await self._invoke_application_runner(db)
            cycle_stats["application_candidates"] = app_stats["candidates"]
            cycle_stats["applied"] = app_stats["applied"]
            cycle_stats["skipped"] = app_stats["skipped"]
            cycle_stats["needs_attention"] = app_stats["needs_attention"]
            cycle_stats["failed"] = app_stats["failed"]
            cycle_stats["errors"].extend(app_stats.get("errors", []))

            logger.info("scheduler_phase_9a_cycle_completed", extra=cycle_stats)

        except Exception as e:
            logger.error("scheduler_discovery_failed", extra={"error": str(e)}, exc_info=True)
            cycle_stats["errors"].append(str(e))
        finally:
            db.close()

    async def _apply_hard_filters_and_enqueue(self, db: Session) -> dict:
        """
        Apply deterministic hard filters to discovered jobs and enqueue eligible ones.

        This method:
        1. Finds all DISCOVERED jobs not yet processed
        2. Evaluates deterministic matching (hard filters)
        3. Enqueues jobs that pass hard filters to AI queue

        Returns statistics about the filtering and queueing process.
        """
        stats = {
            "discovered": 0,
            "hard_filtered": 0,
            "queued": 0,
            "errors": []
        }

        try:
            # Get profile and preferences (required for matching)
            profile = db.execute(select(Profile)).scalars().first()
            if not profile or not profile.confirmed:
                logger.warning("scheduler_no_confirmed_profile_for_matching")
                return stats

            preference = db.execute(select(JobPreference)).scalars().first()
            if not preference:
                logger.warning("scheduler_no_preferences_for_matching")
                return stats

            # Find jobs that need to be processed
            stmt = select(Job).where(
                Job.status == "DISCOVERED"
            ).order_by(Job.discovered_at.desc())

            jobs = db.execute(stmt).scalars().all()
            stats["discovered"] = len(jobs)

            if len(jobs) == 0:
                logger.info("scheduler_no_discovered_jobs_to_process")
                return stats

            # Initialize services
            match_engine = MatchEngine(db)
            ai_queue_service = AIQueueService(db)

            for job in jobs:
                try:
                    # Check if job already has analysis or is queued
                    existing_analysis = db.execute(
                        select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
                    ).scalars().first()

                    if existing_analysis:
                        logger.debug(f"Job {job.id} already analyzed, skipping")
                        stats["hard_filtered"] += 1
                        continue

                    existing_queue = db.execute(
                        select(AIQueueItem).where(AIQueueItem.job_id == job.id)
                    ).scalars().first()

                    if existing_queue:
                        logger.debug(f"Job {job.id} already in queue, skipping")
                        stats["hard_filtered"] += 1
                        continue

                    # Evaluate hard filters using MatchEngine
                    match_decision = match_engine.evaluate_job(job, profile, preference)

                    # If hard filters pass, enqueue for AI analysis
                    if match_decision.decision.value == "APPLY":
                        queue_item = ai_queue_service.enqueue_job(
                            job_id=job.id,
                            priority=match_decision.match_score if match_decision.match_score else 50,
                            priority_reason="Hard filters passed, ready for AI analysis",
                            queue_source="SCHEDULER"
                        )

                        if queue_item:
                            stats["queued"] += 1
                            logger.debug(f"Job {job.id} queued for AI analysis")
                        else:
                            logger.warning(f"Failed to enqueue job {job.id}")
                    else:
                        # Hard filters failed - mark as filtered out
                        stats["hard_filtered"] += 1
                        logger.debug(f"Job {job.id} failed hard filters: {match_decision.reason}")

                except Exception as e:
                    error_msg = f"Error processing job {job.id}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    stats["errors"].append(error_msg)
                    # Continue processing other jobs

            logger.info("scheduler_hard_filter_complete", extra={
                "discovered": stats["discovered"],
                "hard_filtered": stats["hard_filtered"],
                "queued": stats["queued"]
            })

        except Exception as e:
            error_msg = f"Error in hard filter and enqueue: {str(e)}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

        return stats

    async def _process_ai_queue_items(self, db: Session) -> dict:
        """
        Process queued jobs through Gemini analysis.

        This method:
        1. Recovers stale items
        2. Gets profile context
        3. Processes queue items sequentially
        4. Respects quota limits and retry policies

        Returns statistics about the processing run.
        """
        stats = {
            "processed": 0,
            "completed": 0,
            "retry_pending": 0,
            "quota_blocked": 0,
            "needs_attention": 0,
            "failed": 0,
            "errors": []
        }

        try:
            # Initialize AI queue service
            ai_queue_service = AIQueueService(db)

            # Recover stale items first
            recovered = ai_queue_service.recover_stale_items()
            logger.info("scheduler_recovered_stale_queue_items", extra={"count": recovered})

            # Get profile context
            profile = db.execute(select(Profile)).scalars().first()
            profile_context = str(profile.data) if profile and profile.data else ""

            # Process up to 5 items per run to avoid long-running tasks
            max_items_per_run = 5
            items_processed = 0

            while items_processed < max_items_per_run:
                next_item = ai_queue_service.get_next_item()
                if not next_item:
                    logger.info("scheduler_no_more_queue_items")
                    break

                try:
                    result = ai_queue_service.process_item(next_item.id, profile_context)
                    stats["processed"] += 1

                    if result.status.value == "COMPLETED":
                        stats["completed"] += 1
                    elif result.status.value == "RETRY_PENDING":
                        stats["retry_pending"] += 1
                    elif result.status.value == "QUOTA_BLOCKED":
                        stats["quota_blocked"] += 1
                        # Stop processing when quota is blocked
                        logger.info("scheduler_quota_exhausted_stopping_queue")
                        break
                    elif result.status.value == "NEEDS_ATTENTION":
                        stats["needs_attention"] += 1
                    elif result.status.value == "FAILED":
                        stats["failed"] += 1

                    items_processed += 1

                except Exception as e:
                    error_msg = f"Error processing queue item {next_item.id}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    stats["errors"].append(error_msg)
                    stats["failed"] += 1
                    items_processed += 1

            logger.info("scheduler_ai_queue_processing_completed", extra=stats)

        except Exception as e:
            error_msg = f"Error processing AI queue: {str(e)}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

        return stats

    async def _invoke_application_runner(self, db: Session) -> dict:
        """
        Invoke ApplicationRunner for jobs with completed AI analysis.

        This method:
        1. Finds jobs with completed AI analysis
        2. Filters out jobs with failed analysis
        3. Passes them to ApplicationRunner for execution

        Returns statistics about application execution.
        """
        stats = {
            "candidates": 0,
            "applied": 0,
            "skipped": 0,
            "needs_attention": 0,
            "failed": 0,
            "errors": []
        }

        try:
            # Find jobs with completed AI analysis that haven't been applied yet
            from backend.models.application import Application
            from backend.schemas.application import ApplicationStatus

            stmt = select(Job).where(
                Job.id.in_(
                    select(JobAnalysisModel.job_id)
                )
            ).outerjoin(
                Application, Application.job_id == Job.id
            ).where(
                (Application.id == None) |  # Not yet applied
                (Application.status == ApplicationStatus.SKIPPED.value)  # Previously skipped
            ).order_by(Job.discovered_at.desc())

            eligible_jobs = db.execute(stmt).scalars().all()
            stats["candidates"] = len(eligible_jobs)

            if len(eligible_jobs) == 0:
                logger.info("scheduler_no_eligible_jobs_for_application")
                return stats

            # Extract job IDs for ApplicationRunner
            job_ids = [job.id for job in eligible_jobs if job.id]

            if not job_ids:
                logger.info("scheduler_no_valid_job_ids_for_application")
                return stats

            logger.info("scheduler_invoking_application_runner", extra={"job_count": len(job_ids)})

            # Invoke ApplicationRunner
            runner = ApplicationRunner(db, self.state_manager)
            app_results = await runner.run_applications(job_ids)

            # Extract results from ApplicationRunner
            stats["applied"] = app_results.get("applied", 0)
            stats["skipped"] = app_results.get("skipped", 0)
            stats["needs_attention"] = app_results.get("needs_attention", 0)
            stats["failed"] = app_results.get("failed", 0)

            logger.info("scheduler_application_runner_completed", extra=app_results)

        except Exception as e:
            error_msg = f"Error invoking application runner: {str(e)}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

        return stats
