from datetime import datetime, UTC
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.core.scheduler import JobScheduler
from backend.core.config import get_settings
from backend.core.logging import get_logger
from backend.models.scheduler import SchedulerConfig, utc_now
from backend.models.ai_queue import AIQueueItem
from backend.services.discovery.service import DiscoveryService
from backend.services.agent_state import AgentStateManager
from backend.services.applications.limits import ApplicationLimitService
from backend.services.gemini.queue import AIQueueService
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

        # Initialize AI queue service
        self._ai_queue_service = AIQueueService(db)

        # Recover any stale queue items on startup
        recovered = self._ai_queue_service.recover_stale_items()
        if recovered > 0:
            logger.info(f"scheduler_recovered_stale_queue_items", extra={"count": recovered})
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
        Execute scheduled discovery task.

        This method is called by the scheduler core on each scheduled run.
        It integrates with existing DiscoveryService - business rules are there.
        The scheduler only handles timing/orchestration.
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

        try:
            logger.info("scheduler_starting_discovery")

            await self.discovery_service.run_discovery()

            if self._config:
                self._config.last_run_at = utc_now()

            logger.info("scheduler_discovery_completed")

            # Enqueue newly discovered jobs for AI analysis
            await self._enqueue_discovered_jobs()

        except Exception as e:
            logger.error("scheduler_discovery_failed", extra={"error": str(e)}, exc_info=True)

    async def _enqueue_discovered_jobs(self) -> None:
        """
        Enqueue newly discovered jobs for AI analysis.

        This method finds jobs that have been discovered but not yet analyzed
        and enqueues them in the AI queue for processing.
        """
        db = SessionLocal()
        try:
            from backend.models.job import Job
            from backend.models.ai import JobAnalysisModel

            # Find jobs without analysis
            stmt = select(Job).where(
                Job.status == "DISCOVERED"
            ).order_by(Job.discovered_at.desc())

            jobs = db.execute(stmt).scalars().all()

            enqueued_count = 0
            for job in jobs:
                # Check if job already has analysis
                existing_analysis = db.execute(
                    select(JobAnalysisModel).where(JobAnalysisModel.job_id == job.id)
                ).scalars().first()

                if existing_analysis:
                    continue

                # Check if job is already in queue
                existing_queue = db.execute(
                    select(AIQueueItem).where(AIQueueItem.job_id == job.id)
                ).scalars().first()

                if existing_queue:
                    continue

                # Enqueue the job
                queue_item = self._ai_queue_service.enqueue_job(
                    job_id=job.id,
                    priority=50,  # Default priority
                    priority_reason="Discovered by scheduler",
                    queue_source="SCHEDULER"
                )

                if queue_item:
                    enqueued_count += 1

            if enqueued_count > 0:
                logger.info(f"scheduler_enqueued_jobs_for_ai", extra={"count": enqueued_count})

        except Exception as e:
            logger.error("scheduler_enqueue_failed", extra={"error": str(e)}, exc_info=True)
        finally:
            db.close()

    async def process_ai_queue(self, profile_context: str) -> dict:
        """
        Process the AI queue by analyzing queued jobs.

        This method processes queue items sequentially, respecting quota limits
        and retry policies. It's designed to be called from the scheduler or
        manually from the API.

        Returns statistics about the processing run.
        """
        db = SessionLocal()
        try:
            # Recover stale items first
            recovered = self._ai_queue_service.recover_stale_items()

            stats = {
                "recovered": recovered,
                "processed": 0,
                "completed": 0,
                "retry_pending": 0,
                "quota_blocked": 0,
                "needs_attention": 0,
                "failed": 0,
                "errors": 0
            }

            # Process up to 5 items per run to avoid long-running tasks
            max_items_per_run = 5
            items_processed = 0

            while items_processed < max_items_per_run:
                next_item = self._ai_queue_service.get_next_item()
                if not next_item:
                    logger.info("scheduler_no_more_queue_items")
                    break

                try:
                    result = self._ai_queue_service.process_item(next_item.id, profile_context)
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
                    logger.error(f"Error processing queue item {next_item.id}: {e}", exc_info=True)
                    stats["errors"] += 1
                    items_processed += 1

            logger.info("scheduler_ai_queue_processing_completed", extra=stats)
            return stats

        except Exception as e:
            logger.error("scheduler_ai_queue_processing_failed", extra={"error": str(e)}, exc_info=True)
            return {"error": str(e)}
        finally:
            db.close()
