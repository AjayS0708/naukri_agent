from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database.database import SessionLocal
from backend.services.lifecycle import AgentLifecycleService
from backend.schemas.lifecycle import (
    LifecycleStatusResponse,
    LifecycleActionResponse,
    RecoveryResponse
)
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Global lifecycle service instance (set during app startup)
_lifecycle_service: AgentLifecycleService = None


def set_lifecycle_service_instance(service: AgentLifecycleService):
    """Set the global lifecycle service instance."""
    global _lifecycle_service
    _lifecycle_service = service


def get_lifecycle_service() -> AgentLifecycleService:
    """Get the lifecycle service instance."""
    if _lifecycle_service is None:
        raise RuntimeError("Lifecycle service not initialized")
    return _lifecycle_service


def get_db():
    """Dependency for database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/agent/status", response_model=LifecycleStatusResponse)
async def get_agent_status(
    lifecycle_service: AgentLifecycleService = Depends(get_lifecycle_service),
    db: Session = Depends(get_db)
):
    """Get current agent lifecycle status."""
    try:
        status = lifecycle_service.get_lifecycle_status(db)
        return LifecycleStatusResponse(**status)
    except Exception as e:
        logger.error(f"Failed to get agent status: {e}", exc_info=True)
        raise


@router.post("/agent/start", response_model=LifecycleActionResponse)
async def start_agent(
    lifecycle_service: AgentLifecycleService = Depends(get_lifecycle_service),
    db: Session = Depends(get_db)
):
    """Start the agent."""
    try:
        result = await lifecycle_service.start(db)
        return LifecycleActionResponse(**result)
    except Exception as e:
        logger.error(f"Failed to start agent: {e}", exc_info=True)
        raise


@router.post("/agent/stop", response_model=LifecycleActionResponse)
async def stop_agent(
    lifecycle_service: AgentLifecycleService = Depends(get_lifecycle_service),
    db: Session = Depends(get_db)
):
    """Stop the agent."""
    try:
        result = await lifecycle_service.stop(db)
        return LifecycleActionResponse(**result)
    except Exception as e:
        logger.error(f"Failed to stop agent: {e}", exc_info=True)
        raise


@router.post("/agent/pause", response_model=LifecycleActionResponse)
async def pause_agent(
    lifecycle_service: AgentLifecycleService = Depends(get_lifecycle_service),
    db: Session = Depends(get_db)
):
    """Pause the agent."""
    try:
        result = await lifecycle_service.pause(db)
        return LifecycleActionResponse(**result)
    except Exception as e:
        logger.error(f"Failed to pause agent: {e}", exc_info=True)
        raise


@router.post("/agent/resume", response_model=LifecycleActionResponse)
async def resume_agent(
    lifecycle_service: AgentLifecycleService = Depends(get_lifecycle_service),
    db: Session = Depends(get_db)
):
    """Resume the agent."""
    try:
        result = await lifecycle_service.resume(db)
        return LifecycleActionResponse(**result)
    except Exception as e:
        logger.error(f"Failed to resume agent: {e}", exc_info=True)
        raise


@router.post("/agent/recovery", response_model=RecoveryResponse)
async def trigger_recovery(
    lifecycle_service: AgentLifecycleService = Depends(get_lifecycle_service),
    db: Session = Depends(get_db)
):
    """Trigger startup recovery (useful for testing)."""
    try:
        result = lifecycle_service.recover_on_startup(db)
        return RecoveryResponse(**result)
    except Exception as e:
        logger.error(f"Failed to trigger recovery: {e}", exc_info=True)
        raise
