"""
Autonomous Cycle Control API - CHECKPOINT E3

API endpoints for controlling the autonomous cycle from the dashboard.
These endpoints provide a safe command/control interface that reuses the
existing AutonomousCycleService.

All endpoints use process-level concurrency protection (threading.Lock)
for V1 local-first execution. Distributed locking is deferred until cloud execution.
"""
import asyncio
import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.autonomous_cycle import (
    AutonomousCycleStartRequest,
    AutonomousCycleStartResponse,
    AutonomousCycleStatusResponse,
)
from backend.services.autonomous_cycle import AutonomousCycle
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/autonomous-cycle", tags=["autonomous-cycle"])

# Process-level execution lock for V1 local-first concurrency protection
# This prevents multiple autonomous cycles from running simultaneously in the same process.
# Future cloud deployment would require distributed locking.
_cycle_lock = threading.Lock()
_current_run_info: Optional[dict] = None


@router.post("/run", response_model=AutonomousCycleStartResponse)
async def start_autonomous_cycle(
    request: AutonomousCycleStartRequest,
    db: Session = Depends(get_db),
) -> AutonomousCycleStartResponse:
    """
    Start an autonomous cycle.

    This endpoint initiates the autonomous job application cycle with the
    specified max_applications limit. The cycle runs the full proven pipeline:
    discovery -> hard filters -> AI queue -> Gemini -> final safety gate -> ApplicationRunner

    All safety boundaries (D6.1, D6.2, C2, D4/D5, D7) are preserved.
    The Gemini budget is internally derived as max_applications * 2.

    Concurrency protection:
    - Only one autonomous cycle may run at a time (process-level lock)
    - Returns 409 Conflict if a cycle is already running

    The cycle runs in the background and returns immediately with run information.
    """
    global _current_run_info

    # Check if a cycle is already running
    if _cycle_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "AUTONOMOUS_CYCLE_RUNNING",
                "message": "An autonomous cycle is already running",
                "run_id": _current_run_info.get("run_id") if _current_run_info else None,
            },
        )

    # Acquire the lock
    if not _cycle_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "AUTONOMOUS_CYCLE_RUNNING",
                "message": "An autonomous cycle is already running",
            },
        )

    try:
        # Create the cycle instance
        cycle = AutonomousCycle(
            max_applications=request.max_applications,
            dry_run=False,
            enable_cli_output=False,  # Disable CLI output for API calls
        )

        # Set current run info
        _current_run_info = {
            "status": "RUNNING",
            "max_applications": request.max_applications,
            "started_at": None,
        }

        # Start the cycle in the background
        async def run_cycle_background():
            global _current_run_info
            try:
                _current_run_info["started_at"] = None  # Would set timestamp here
                result = await cycle.run()
                _current_run_info = {
                    "status": result.get("status", "FAILED"),
                    "run_id": result.get("run_id"),
                    "max_applications": request.max_applications,
                    "started_at": _current_run_info.get("started_at"),
                    "completed_at": None,  # Would set timestamp here
                    "stats": result.get("stats", {}),
                }
                logger.info(f"Autonomous cycle completed: {result}")
            except Exception as e:
                logger.error(f"Autonomous cycle failed: {e}", exc_info=True)
                _current_run_info = {
                    "status": "FAILED",
                    "run_id": None,
                    "max_applications": request.max_applications,
                    "error": str(e),
                }
            finally:
                _cycle_lock.release()

        # Schedule background task
        asyncio.create_task(run_cycle_background())

        return AutonomousCycleStartResponse(
            run_id=None,  # Will be available after discovery starts
            status="RUNNING",
            max_applications=request.max_applications,
            message="Autonomous cycle started",
        )

    except Exception as e:
        _cycle_lock.release()
        logger.error(f"Failed to start autonomous cycle: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to start autonomous cycle"},
        )


@router.get("/status", response_model=AutonomousCycleStatusResponse)
async def get_autonomous_cycle_status() -> AutonomousCycleStatusResponse:
    """
    Get the current status of the autonomous cycle.

    Returns:
    - IDLE: No cycle is running
    - RUNNING: A cycle is currently executing
    - COMPLETED: The last cycle completed successfully
    - FAILED: The last cycle failed

    This endpoint is read-only and does not trigger any automation.
    """
    global _current_run_info

    if _current_run_info is None:
        return AutonomousCycleStatusResponse(
            status="IDLE",
            run_id=None,
            started_at=None,
            completed_at=None,
            max_applications=None,
            stats={},
        )

    return AutonomousCycleStatusResponse(
        status=_current_run_info.get("status", "UNKNOWN"),
        run_id=_current_run_info.get("run_id"),
        started_at=_current_run_info.get("started_at"),
        completed_at=_current_run_info.get("completed_at"),
        max_applications=_current_run_info.get("max_applications"),
        stats=_current_run_info.get("stats", {}),
    )
