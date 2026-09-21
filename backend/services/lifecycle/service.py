from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.services.agent_state import AgentStateManager
from backend.services.scheduler.service import SchedulerService
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.schemas.agent import AgentState
from backend.core.logging import get_logger

logger = get_logger(__name__)


class AgentLifecycleService:
    """
    Service for managing agent lifecycle operations.
    
    This service extends AgentStateManager to provide safe lifecycle control
    including start, stop, pause, resume operations with prerequisite validation.
    It integrates with SchedulerService without duplicating state management logic.
    
    Lifecycle states follow existing AgentState enum:
    - IDLE: Agent ready to start
    - RUNNING: Agent actively processing
    - PAUSED: Agent paused, queue preserved
    - STOPPED: Agent stopped, queue preserved
    - AUTH_REQUIRED: Naukri authentication needed
    - SECURITY_REQUIRED: CAPTCHA/security challenge needed
    - AI_QUOTA_EXHAUSTED: Gemini quota exhausted
    - NEEDS_ATTENTION: Manual intervention needed
    - CRITICAL_ERROR: Critical system error
    """
    
    def __init__(
        self,
        state_manager: AgentStateManager,
        scheduler_service: Optional[SchedulerService] = None
    ):
        self.state_manager = state_manager
        self.scheduler_service = scheduler_service
    
    def get_lifecycle_status(self, db: Session) -> dict:
        """
        Get comprehensive lifecycle status including agent state,
        scheduler state, and AI queue state.
        """
        from backend.services.gemini.queue import AIQueueService
        
        status = {
            "agent_state": self.state_manager.current_state.value,
            "scheduler": None,
            "ai_queue": None,
            "prerequisites": self._check_prerequisites(db)
        }
        
        if self.scheduler_service:
            status["scheduler"] = self.scheduler_service.get_status()
        
        # Get AI queue status
        ai_queue_service = AIQueueService(db)
        status["ai_queue"] = ai_queue_service.get_queue_status().model_dump()
        
        return status
    
    async def start(self, db: Session) -> dict:
        """
        Start the agent safely.
        
        Validates prerequisites, starts scheduler, and transitions to RUNNING state.
        Does NOT automatically submit applications - only enables scheduled discovery.
        """
        if self.state_manager.current_state != AgentState.IDLE:
            logger.warning(f"Cannot start from state {self.state_manager.current_state.value}")
            return {
                "success": False,
                "reason": f"Cannot start from {self.state_manager.current_state.value} state",
                "current_state": self.state_manager.current_state.value
            }
        
        # Validate prerequisites
        prerequisites = self._check_prerequisites(db)
        if not prerequisites["valid"]:
            logger.warning(f"Prerequisites not met: {prerequisites['missing']}")
            return {
                "success": False,
                "reason": "Prerequisites not met",
                "prerequisites": prerequisites
            }
        
        try:
            # Start scheduler if available
            if self.scheduler_service:
                await self.scheduler_service.start(db)
            
            # Transition to RUNNING
            self.state_manager.transition_to(AgentState.RUNNING)
            
            logger.info("agent_started")
            return {
                "success": True,
                "state": AgentState.RUNNING.value,
                "message": "Agent started successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to start agent: {e}", exc_info=True)
            self.state_manager.transition_to(AgentState.CRITICAL_ERROR)
            return {
                "success": False,
                "reason": f"Failed to start: {str(e)}",
                "state": AgentState.CRITICAL_ERROR.value
            }
    
    async def stop(self, db: Session) -> dict:
        """
        Stop the agent safely.
        
        Stops scheduler, prevents new processing, preserves queue state.
        Does NOT delete queued work.
        """
        if self.state_manager.current_state == AgentState.STOPPED:
            logger.warning("Agent already stopped")
            return {
                "success": True,
                "state": AgentState.STOPPED.value,
                "message": "Agent already stopped"
            }
        
        try:
            # Stop scheduler if available
            if self.scheduler_service:
                await self.scheduler_service.stop(db)
            
            # Transition to STOPPED
            self.state_manager.transition_to(AgentState.STOPPED)
            
            logger.info("agent_stopped")
            return {
                "success": True,
                "state": AgentState.STOPPED.value,
                "message": "Agent stopped successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to stop agent: {e}", exc_info=True)
            return {
                "success": False,
                "reason": f"Failed to stop: {str(e)}",
                "current_state": self.state_manager.current_state.value
            }
    
    async def pause(self, db: Session) -> dict:
        """
        Pause the agent.
        
        Stops new processing, preserves queue state.
        Does NOT delete queued work.
        """
        if self.state_manager.current_state not in [AgentState.RUNNING, AgentState.SEARCHING, AgentState.FILTERING, AgentState.ANALYZING, AgentState.APPLYING]:
            logger.warning(f"Cannot pause from state {self.state_manager.current_state.value}")
            return {
                "success": False,
                "reason": f"Cannot pause from {self.state_manager.current_state.value} state",
                "current_state": self.state_manager.current_state.value
            }
        
        try:
            # Pause scheduler if available
            if self.scheduler_service:
                await self.scheduler_service.pause(db)
            
            # Transition to PAUSED
            self.state_manager.transition_to(AgentState.PAUSED)
            
            logger.info("agent_paused")
            return {
                "success": True,
                "state": AgentState.PAUSED.value,
                "message": "Agent paused successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to pause agent: {e}", exc_info=True)
            return {
                "success": False,
                "reason": f"Failed to pause: {str(e)}",
                "current_state": self.state_manager.current_state.value
            }
    
    async def resume(self, db: Session) -> dict:
        """
        Resume the agent from paused state.
        
        Validates prerequisites, resumes scheduler/processing.
        """
        if self.state_manager.current_state != AgentState.PAUSED:
            logger.warning(f"Cannot resume from state {self.state_manager.current_state.value}")
            return {
                "success": False,
                "reason": f"Cannot resume from {self.state_manager.current_state.value} state",
                "current_state": self.state_manager.current_state.value
            }
        
        # Validate prerequisites
        prerequisites = self._check_prerequisites(db)
        if not prerequisites["valid"]:
            logger.warning(f"Prerequisites not met: {prerequisites['missing']}")
            return {
                "success": False,
                "reason": "Prerequisites not met",
                "prerequisites": prerequisites
            }
        
        try:
            # Resume scheduler if available
            if self.scheduler_service:
                await self.scheduler_service.resume(db)
            
            # Transition to RUNNING
            self.state_manager.transition_to(AgentState.RUNNING)
            
            logger.info("agent_resumed")
            return {
                "success": True,
                "state": AgentState.RUNNING.value,
                "message": "Agent resumed successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to resume agent: {e}", exc_info=True)
            return {
                "success": False,
                "reason": f"Failed to resume: {str(e)}",
                "current_state": self.state_manager.current_state.value
            }
    
    def recover_on_startup(self, db: Session) -> dict:
        """
        Perform startup recovery.
        
        This method is called during FastAPI lifespan to:
        - Recover stale AI queue items
        - Restore scheduler configuration
        - Set agent to safe state based on persisted configuration
        
        Does NOT automatically submit applications after restart.
        Defaults to IDLE unless persisted configuration explicitly says otherwise.
        """
        from backend.services.gemini.queue import AIQueueService
        
        recovery_stats = {
            "stale_queue_items_recovered": 0,
            "scheduler_config_restored": False,
            "agent_state_restored": AgentState.IDLE.value
        }
        
        try:
            # Recover stale AI queue items
            ai_queue_service = AIQueueService(db)
            recovered = ai_queue_service.recover_stale_items()
            recovery_stats["stale_queue_items_recovered"] = recovered
            logger.info(f"recovered_stale_queue_items", extra={"count": recovered})
            
            # Scheduler configuration is already restored by SchedulerService.initialize()
            # Just log that it's available
            if self.scheduler_service:
                recovery_stats["scheduler_config_restored"] = True
                logger.info("scheduler_config_restored")
            
            # Default to IDLE state - safe startup
            # Do NOT automatically resume RUNNING state without explicit user action
            # This prevents automatic application submission after restart
            if self.state_manager.current_state in [AgentState.RUNNING, AgentState.SEARCHING, AgentState.FILTERING, AgentState.APPLYING]:
                logger.info("resetting_agent_to_idle_on_restart")
                self.state_manager.transition_to(AgentState.STOPPED)
                self.state_manager.transition_to(AgentState.IDLE)
                recovery_stats["agent_state_restored"] = AgentState.IDLE.value
            else:
                recovery_stats["agent_state_restored"] = self.state_manager.current_state.value
            
            logger.info("startup_recovery_complete", extra=recovery_stats)
            return {
                "success": True,
                "recovery_stats": recovery_stats
            }
            
        except Exception as e:
            logger.error(f"Startup recovery failed: {e}", exc_info=True)
            # Ensure we're in a safe state even if recovery fails
            self.state_manager.transition_to(AgentState.IDLE)
            return {
                "success": False,
                "reason": f"Recovery failed: {str(e)}",
                "recovery_stats": recovery_stats
            }
    
    def _check_prerequisites(self, db: Session) -> dict:
        """
        Check if prerequisites for agent operation are met.
        
        Returns dict with:
        - valid: bool
        - missing: list of missing prerequisites
        """
        missing = []
        
        # Check for confirmed profile
        profile = db.execute(select(Profile)).scalars().first()
        if not profile or not profile.confirmed:
            missing.append("confirmed_profile")
        
        # Check for job preferences
        preferences = db.execute(select(JobPreference)).scalars().first()
        if not preferences:
            missing.append("job_preferences")
        
        # Check for AI API key
        from backend.core.config import get_settings
        settings = get_settings()
        if not settings.gemini_api_key:
            missing.append("gemini_api_key")
        
        return {
            "valid": len(missing) == 0,
            "missing": missing
        }
