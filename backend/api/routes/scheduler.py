from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from backend.schemas.scheduler import (
    SchedulerStatusResponse,
    SchedulerConfigRequest,
    SchedulerConfigResponse,
    SchedulerActionResponse
)
from backend.services.scheduler.service import SchedulerService
from backend.database.database import get_session
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/scheduler", tags=["Scheduler"])

# Global scheduler service instance - shared with main.py
_scheduler_service_instance: SchedulerService | None = None


def get_scheduler_service() -> SchedulerService:
    """Dependency to get the scheduler service instance."""
    global _scheduler_service_instance
    if _scheduler_service_instance is None:
        raise HTTPException(status_code=503, detail="Scheduler service not initialized")
    return _scheduler_service_instance


def set_scheduler_service_instance(service: SchedulerService) -> None:
    """Set the global scheduler service instance (called from main.py)."""
    global _scheduler_service_instance
    _scheduler_service_instance = service


@router.get("/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status(
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Get the current status of the scheduler.
    """
    status = service.get_status()
    return SchedulerStatusResponse(**status)


@router.post("/start", response_model=SchedulerActionResponse)
async def start_scheduler(
    db: Session = Depends(get_session),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Start the scheduler. Discovery will run at the configured interval.
    """
    try:
        await service.start(db)
        status = service.get_status()
        return SchedulerActionResponse(
            success=True,
            message="Scheduler started successfully",
            status=SchedulerStatusResponse(**status)
        )
    except Exception as e:
        logger.error("start_scheduler_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {str(e)}")


@router.post("/stop", response_model=SchedulerActionResponse)
async def stop_scheduler(
    db: Session = Depends(get_session),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Stop the scheduler. No more scheduled discovery runs will occur.
    """
    try:
        await service.stop(db)
        status = service.get_status()
        return SchedulerActionResponse(
            success=True,
            message="Scheduler stopped successfully",
            status=SchedulerStatusResponse(**status)
        )
    except Exception as e:
        logger.error("stop_scheduler_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to stop scheduler: {str(e)}")


@router.post("/pause", response_model=SchedulerActionResponse)
async def pause_scheduler(
    db: Session = Depends(get_session),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Pause the scheduler. Keeps it running but pauses job execution.
    """
    try:
        await service.pause(db)
        status = service.get_status()
        return SchedulerActionResponse(
            success=True,
            message="Scheduler paused successfully",
            status=SchedulerStatusResponse(**status)
        )
    except Exception as e:
        logger.error("pause_scheduler_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to pause scheduler: {str(e)}")


@router.post("/resume", response_model=SchedulerActionResponse)
async def resume_scheduler(
    db: Session = Depends(get_session),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Resume the scheduler from paused state.
    """
    try:
        await service.resume(db)
        status = service.get_status()
        return SchedulerActionResponse(
            success=True,
            message="Scheduler resumed successfully",
            status=SchedulerStatusResponse(**status)
        )
    except Exception as e:
        logger.error("resume_scheduler_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to resume scheduler: {str(e)}")


@router.put("/config", response_model=SchedulerConfigResponse)
async def update_scheduler_config(
    config: SchedulerConfigRequest,
    db: Session = Depends(get_session),
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Update scheduler configuration (enabled state and/or interval).
    """
    try:
        if config.enabled is not None:
            await service.update_enabled(db, config.enabled)
        
        if config.interval_minutes is not None:
            await service.update_interval(db, config.interval_minutes)
        
        status = service.get_status()
        return SchedulerConfigResponse(**status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("update_scheduler_config_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to update scheduler config: {str(e)}")


@router.post("/process-ai-queue")
async def process_ai_queue(
    profile_context: str,
    service: SchedulerService = Depends(get_scheduler_service)
):
    """
    Process the AI queue by analyzing queued jobs.

    This method processes queue items sequentially, respecting quota limits
    and retry policies. It's designed to be called from the scheduler or
    manually from the API.

    Returns statistics about the processing run.
    """
    try:
        stats = await service.process_ai_queue(profile_context)
        return stats
    except Exception as e:
        logger.error("process_ai_queue_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Failed to process AI queue: {str(e)}")
