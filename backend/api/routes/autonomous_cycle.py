"""Autonomous-cycle control and strictly read-only runtime diagnostics."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.core.logging import get_logger
from backend.schemas.autonomous_cycle import (
    AutonomousCycleRunResponse,
    AutonomousCycleStartRequest,
    AutonomousCycleStartResponse,
    AutonomousCycleStatusResponse,
)
from backend.services.autonomous_cycle import AutonomousCycle
from backend.services.autonomous_cycle.runtime import AutonomousCycleRuntime

logger = get_logger(__name__)
router = APIRouter(prefix="/autonomous-cycle", tags=["autonomous-cycle"])

# Process-local by design. A fresh backend process begins IDLE; completed
# history is retained separately and never represented as an active execution.
_runtime = AutonomousCycleRuntime()


@router.post("/run", response_model=AutonomousCycleStartResponse)
async def start_autonomous_cycle(
    request: AutonomousCycleStartRequest, db: Session = Depends(get_db)
) -> AutonomousCycleStartResponse:
    del db  # The cycle owns its session; dependency keeps route conventions consistent.
    active = _runtime.start(request.max_applications)
    if active is None:
        current = _runtime.snapshot()["active_run"] or {}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AUTONOMOUS_CYCLE_RUNNING", "message": "An autonomous cycle is already running", "run_id": current.get("run_id")},
        )

    try:
        cycle = AutonomousCycle(max_applications=request.max_applications, dry_run=False, enable_cli_output=False)
    except Exception:
        _runtime.fail("Unable to initialize autonomous cycle.")
        logger.exception("autonomous_cycle_initialization_failed")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": "Failed to start autonomous cycle"})

    async def run_cycle_background() -> None:
        try:
            result = await cycle.run()
            _runtime.complete(result)
            logger.info("autonomous_cycle_completed", extra={"status": result.get("status"), "run_id": result.get("run_id")})
        except Exception:
            _runtime.fail("Autonomous cycle execution failed unexpectedly.")
            logger.exception("autonomous_cycle_failed")

    asyncio.create_task(run_cycle_background())
    return AutonomousCycleStartResponse(run_id=None, status="RUNNING", max_applications=request.max_applications, message="Autonomous cycle started")


@router.get("/status", response_model=AutonomousCycleStatusResponse)
async def get_autonomous_cycle_status() -> AutonomousCycleStatusResponse:
    """Read runtime diagnostics only; this endpoint cannot start a cycle."""
    snapshot = _runtime.snapshot()
    return AutonomousCycleStatusResponse(
        active_state=snapshot["active_state"],
        lock_held=snapshot["lock_held"],
        active_run=AutonomousCycleRunResponse(**snapshot["active_run"]) if snapshot["active_run"] else None,
        last_run=AutonomousCycleRunResponse(**snapshot["last_run"]) if snapshot["last_run"] else None,
    )
