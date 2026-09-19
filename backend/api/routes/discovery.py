from typing import Optional
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from backend.database.database import get_session
from backend.schemas.discovery import DiscoveryStatusResponse, DiscoveryRunStats, DiscoveryRunResponse
from backend.services.agent_state import AgentStateManager
from backend.schemas.agent import AgentState
from backend.services.discovery.service import DiscoveryService
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/discovery", tags=["Discovery"])

# In Phase 5, we only manage a single instance for local Desktop architecture 
# as per PRD for V1
state_manager = AgentStateManager(initial_state=AgentState.IDLE)
discovery_service = DiscoveryService(state_manager=state_manager)


@router.post("/start", response_model=DiscoveryStatusResponse)
async def start_discovery(background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    """
    Start the Naukri job discovery process using user's job preferences.
    """
    if discovery_service.is_running:
        return _get_status()

    # Launch background task
    background_tasks.add_task(discovery_service.run_discovery, db)
    
    return _get_status()


@router.post("/stop", response_model=DiscoveryStatusResponse)
async def stop_discovery():
    """
    Stop an active discovery run gracefully.
    """
    if discovery_service.is_running:
        await discovery_service.stop_safely()
        
    return _get_status()


@router.get("/status", response_model=DiscoveryStatusResponse)
async def get_status():
    """
    Returns the real-time status of the discovery service.
    """
    return _get_status()


def _get_status() -> DiscoveryStatusResponse:
    # Build active run response if available
    active_run = None
    if discovery_service.current_run:
        active_run = DiscoveryRunResponse(
            id=discovery_service.current_run.id,
            status=discovery_service.current_run.status,
            started_at=discovery_service.current_run.started_at,
            completed_at=discovery_service.current_run.completed_at,
            error_message=discovery_service.current_run.error_message,
            stats=DiscoveryRunStats(
                searches_attempted=discovery_service.current_run.searches_attempted,
                jobs_discovered=discovery_service.current_run.jobs_discovered,
                new_jobs=discovery_service.current_run.new_jobs,
                duplicate_jobs=discovery_service.current_run.duplicate_jobs,
                errors=discovery_service.current_run.errors,
                pages_processed=discovery_service.current_run.pages_processed,
            )
        )

    return DiscoveryStatusResponse(
        is_running=discovery_service.is_running,
        agent_state=state_manager.current_state,
        current_search=discovery_service.current_search,
        active_run=active_run,
    )
