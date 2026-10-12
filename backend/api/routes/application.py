from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from backend.database.database import get_session
from backend.schemas.agent import AgentState
from backend.schemas.application import (
    ApplicationSchema, ApplicationCreate, ApplicationUpdate,
    ApplicationStartRequest, ApplicationStartResponse, ApplicationHistoryResponse,
    ReconcileStaleExternalsResponse, ReconcileHistoryResponse
)
from backend.services.applications import ApplicationService, ApplicationRunner
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


@router.post("/reconcile-stale-externals", response_model=ReconcileStaleExternalsResponse)
async def reconcile_stale_externals(db: Session = Depends(get_session)):
    """
    Human-triggered reconciliation of proven-false external classifications.

    Rule 1 (E5-R5.3): reclassifies only EXTERNAL_APPLICATION rows whose
    external_url exactly matches the known Naukri page-chrome signature
    captured before the E5-R4.1 detector fix. Rule 2 (E5-R6): reclassifies
    EXTERNAL_APPLICATION rows whose external_url matches the linked job's
    own canonical Naukri URL after safe normalization (pre-E5-R5.4
    body-scan-first misclassification). Idempotent, never touches other
    statuses, not scheduled, and never invoked automatically by the
    autonomous cycle.
    """
    service = ApplicationService(db)
    result = service.reconcile_stale_externals()
    return ReconcileStaleExternalsResponse(**result)


@router.post("/reconcile-history", response_model=ReconcileHistoryResponse)
async def reconcile_history(db: Session = Depends(get_session)):
    """Read-only reconciliation of local records against Naukri history.

    E5-R16: opens the existing persistent browser profile, reads the
    authenticated applied-jobs page and compares it with local rows. It never
    clicks Apply, never submits, withdraws or modifies a Naukri application,
    and never deletes a local record. Refuses while an autonomous cycle holds
    the browser profile, and reports LOGIN_REQUIRED without reading anything
    when the session is not authenticated.
    """
    from backend.core.config import get_settings
    from backend.services.autonomous_cycle.coordinator import coordinator
    from backend.services.naukri.adapter import NaukriAdapter

    snapshot = coordinator.snapshot(db=db)
    if snapshot.get("active_state") == "RUNNING":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AUTONOMOUS_CYCLE_RUNNING",
                "message": "Wait for the active autonomous cycle to finish",
            },
        )

    service = ApplicationService(db)
    settings = get_settings()
    adapter = NaukriAdapter(browser_type=settings.browser_type)
    started = await adapter.start_session()
    if not started:
        return ReconcileHistoryResponse(
            status="SESSION_UNAVAILABLE",
            message=adapter.last_startup_error or "Browser session could not start",
        )
    try:
        auth = await adapter.check_session_authenticated()
        if auth.get("authenticated") is False:
            return ReconcileHistoryResponse(
                status="LOGIN_REQUIRED",
                message=(
                    "Naukri session is not authenticated; sign in manually in "
                    "the agent browser and retry. No history was read."
                ),
            )
        try:
            entries = await adapter.fetch_application_history()
        except Exception as exc:
            if "login required" in str(exc).lower():
                return ReconcileHistoryResponse(
                    status="LOGIN_REQUIRED",
                    message="Naukri session is not authenticated; no history was read.",
                )
            logger.exception("naukri_history_read_failed")
            return ReconcileHistoryResponse(
                status="FAILED",
                message=f"History read failed: {type(exc).__name__}",
            )
        result = service.reconcile_from_history(entries)
        return ReconcileHistoryResponse(status="OK", **result)
    finally:
        await adapter.stop_session()


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
    if _state_manager.current_state == AgentState.AUTH_REQUIRED:
        # E5-R16: the previous run stopped on a logged-out session. Once the
        # operator has signed in again, the retry starts from a clean state.
        _state_manager.transition_to(AgentState.STOPPED)
        _state_manager.transition_to(AgentState.IDLE)
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
