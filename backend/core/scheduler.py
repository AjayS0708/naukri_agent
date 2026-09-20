from datetime import datetime, UTC
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from backend.core.logging import get_logger

logger = get_logger(__name__)


class JobScheduler:
    """
    Core scheduler using APScheduler for job discovery orchestration.
    
    Responsibilities:
    - Manage scheduler lifecycle (start, stop, pause, resume)
    - Prevent overlapping scheduled runs
    - Track scheduler state
    - Execute scheduled tasks via callbacks
    
    The scheduler is timing/orchestration only - business rules are handled by services.
    """
    
    def __init__(self, interval_minutes: int = 60, max_instances: int = 1):
        self.interval_minutes = interval_minutes
        self.max_instances = max_instances
        
        jobstores = {
            'default': MemoryJobStore()
        }
        
        executors = {
            'default': AsyncIOExecutor()
        }
        
        job_defaults = {
            'coalesce': True,
            'max_instances': max_instances,
            'misfire_grace_time': 300
        }
        
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=UTC
        )
        
        self._task_callback: Optional[Callable] = None
        self._is_running = False
        self._is_paused = False
        self._last_run_at: Optional[datetime] = None
        self._next_run_at: Optional[datetime] = None
        
    def set_task_callback(self, callback: Callable) -> None:
        """Set the callback function to execute on scheduled runs."""
        self._task_callback = callback
        
    async def start(self) -> None:
        """Start the scheduler."""
        if self._is_running:
            logger.warning("scheduler_already_running")
            return
            
        if self._task_callback is None:
            logger.warning("scheduler_no_callback_set")
            return
            
        try:
            self.scheduler.add_job(
                self._execute_task,
                trigger=IntervalTrigger(minutes=self.interval_minutes, timezone=UTC),
                id='discovery_job',
                name='Job Discovery Task',
                replace_existing=True
            )
            
            self.scheduler.start()
            self._is_running = True
            self._is_paused = False
            self._update_next_run()
            logger.info("scheduler_started", extra={"interval_minutes": self.interval_minutes})
            
        except Exception as e:
            logger.error("scheduler_start_failed", extra={"error": str(e)})
            raise
            
    async def stop(self) -> None:
        """Stop the scheduler."""
        if not self._is_running:
            logger.warning("scheduler_not_running")
            return
            
        try:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            self._is_paused = False
            self._next_run_at = None
            logger.info("scheduler_stopped")
            
        except Exception as e:
            logger.error("scheduler_stop_failed", extra={"error": str(e)})
            raise
            
    async def pause(self) -> None:
        """Pause the scheduler (keeps it running but pauses job execution)."""
        if not self._is_running:
            logger.warning("scheduler_not_running")
            return
            
        if self._is_paused:
            logger.warning("scheduler_already_paused")
            return
            
        try:
            self.scheduler.pause_job('discovery_job')
            self._is_paused = True
            self._next_run_at = None
            logger.info("scheduler_paused")
            
        except Exception as e:
            logger.error("scheduler_pause_failed", extra={"error": str(e)})
            raise
            
    async def resume(self) -> None:
        """Resume the scheduler from paused state."""
        if not self._is_running:
            logger.warning("scheduler_not_running")
            return
            
        if not self._is_paused:
            logger.warning("scheduler_not_paused")
            return
            
        try:
            self.scheduler.resume_job('discovery_job')
            self._is_paused = False
            self._update_next_run()
            logger.info("scheduler_resumed")
            
        except Exception as e:
            logger.error("scheduler_resume_failed", extra={"error": str(e)})
            raise
            
    async def update_interval(self, interval_minutes: int) -> None:
        """Update the scheduling interval."""
        if interval_minutes < 1:
            raise ValueError("Interval must be at least 1 minute")
            
        self.interval_minutes = interval_minutes
        
        if self._is_running and not self._is_paused:
            try:
                self.scheduler.remove_job('discovery_job')
                self.scheduler.add_job(
                    self._execute_task,
                    trigger=IntervalTrigger(minutes=interval_minutes, timezone=UTC),
                    id='discovery_job',
                    name='Job Discovery Task',
                    replace_existing=True
                )
                self._update_next_run()
                logger.info("scheduler_interval_updated", extra={"interval_minutes": interval_minutes})
                
            except Exception as e:
                logger.error("scheduler_interval_update_failed", extra={"error": str(e)})
                raise
                
    def get_status(self) -> dict:
        """Get current scheduler status."""
        job = self.scheduler.get_job('discovery_job') if self._is_running else None
        
        return {
            "is_running": self._is_running,
            "is_paused": self._is_paused,
            "interval_minutes": self.interval_minutes,
            "max_instances": self.max_instances,
            "last_run_at": self._last_run_at,
            "next_run_at": job.next_run_time if job else self._next_run_at
        }
        
    async def _execute_task(self) -> None:
        """Execute the scheduled task callback."""
        if self._task_callback is None:
            logger.warning("scheduler_no_callback_during_execution")
            return
            
        try:
            self._last_run_at = datetime.now(UTC)
            logger.info("scheduler_task_executing")
            
            await self._task_callback()
            
            logger.info("scheduler_task_completed")
            self._update_next_run()
            
        except Exception as e:
            logger.error("scheduler_task_failed", extra={"error": str(e)}, exc_info=True)
            
    def _update_next_run(self) -> None:
        """Update the next run time from the scheduler job."""
        job = self.scheduler.get_job('discovery_job')
        if job:
            self._next_run_at = job.next_run_time
