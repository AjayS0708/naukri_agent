from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from backend.database.database import get_session
from backend.schemas.application import (
    ApplicationSchema, ApplicationCreate, ApplicationUpdate,
    ApplicationStartRequest, ApplicationStartResponse, ApplicationHistoryResponse,
    ApplicationLimitsUpdate, ApplicationLimitsResponse, LimitCheckResponse
)
from backend.services.applications import ApplicationService, ApplicationRunner
from backend.services.applications.limits import ApplicationLimitService
from backend.services.agent_state import AgentStateManager
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Global state manager (in production, this should be dependency-injected)
_state_manager = AgentStateManager()


@router.post("/start", response_model=ApplicationStartResponse)
async def start_application(
    request: ApplicationStartRequest,
    db: Session = Depends(get_session)
):
    """
    Start an application for a specific job.
    This is a simplified endpoint that creates an application record.
    Full automation requires the runner.
    """
    service = ApplicationService(db)
    
    # Check if job exists
    from backend.models.job import Job
    job = db.get(Job, request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Create application
    application = service.create_application(
        ApplicationCreate(job_id=request.job_id)
    )
    
    return ApplicationStartResponse(
        application_id=application.id,
        status=application.status,
        message="Application record created"
    )


@router.get("/history", response_model=ApplicationHistoryResponse)
async def get_application_history(
    limit: int = 100,
    db: Session = Depends(get_session)
):
    """Get application history."""
    if limit > 1000:
        limit = 1000
    
    service = ApplicationService(db)
    applications = service.get_application_history(limit)
    
    return ApplicationHistoryResponse(
        applications=applications,
        total=len(applications)
    )


@router.get("/job/{job_id}", response_model=ApplicationSchema)
async def get_application_by_job(job_id: int, db: Session = Depends(get_session)):
    """Get the most recent application for a job."""
    service = ApplicationService(db)
    application = service.get_application_by_job(job_id)
    if not application:
        raise HTTPException(status_code=404, detail="No application found for this job")
    return application


@router.get("/{application_id}", response_model=ApplicationSchema)
async def get_application(application_id: int, db: Session = Depends(get_session)):
    """Get an application by ID."""
    service = ApplicationService(db)
    application = service.get_application(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@router.put("/{application_id}", response_model=ApplicationSchema)
async def update_application(
    application_id: int,
    update: ApplicationUpdate,
    db: Session = Depends(get_session)
):
    """Update an application."""
    service = ApplicationService(db)
    application = service.update_application(application_id, update)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@router.post("/run")
async def run_applications(
    job_ids: list[int],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session)
):
    """
    Start the application runner for a list of job IDs.
    This runs in the background.
    """
    if _state_manager.current_state.value != "IDLE":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start applications from state {_state_manager.current_state.value}"
        )
    
    runner = ApplicationRunner(db, _state_manager)
    
    # Run in background
    background_tasks.add_task(runner.run_applications, job_ids)
    
    return {
        "message": "Application runner started",
        "job_ids": job_ids,
        "total": len(job_ids)
    }


@router.post("/stop")
async def stop_applications():
    """Request a graceful stop of the application runner."""
    # Note: This is a simplified implementation
    # In production, you'd need to track the runner instance
    return {"message": "Stop requested (not fully implemented in this version)"}


@router.get("/limits", response_model=ApplicationLimitsResponse)
async def get_application_limits(db: Session = Depends(get_session)):
    """Get current application limits and usage."""
    limit_service = ApplicationLimitService(db)
    status = limit_service.get_limit_status()
    return ApplicationLimitsResponse(**status)


@router.put("/limits", response_model=ApplicationLimitsResponse)
async def update_application_limits(
    update: ApplicationLimitsUpdate,
    db: Session = Depends(get_session)
):
    """Update application limits."""
    limit_service = ApplicationLimitService(db)
    limit_service.update_limits(
        max_hourly=update.max_hourly_applications,
        max_daily=update.max_daily_applications
    )
    status = limit_service.get_limit_status()
    return ApplicationLimitsResponse(**status)


@router.get("/limits/check", response_model=LimitCheckResponse)
async def check_application_limits(db: Session = Depends(get_session)):
    """Check if another application is allowed based on current limits."""
    limit_service = ApplicationLimitService(db)
    result = limit_service.check_limits()
    return LimitCheckResponse(
        allowed=result.allowed,
        reason=result.reason,
        hourly_used=result.hourly_used,
        daily_used=result.daily_used,
        hourly_remaining=result.hourly_remaining,
        daily_remaining=result.daily_remaining
    )
