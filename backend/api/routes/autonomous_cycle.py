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
    AutonomousCycleStopRequest,
    AutonomousCycleStopResponse,
)
from backend.services.autonomous_cycle import AutonomousCycle
from backend.services.autonomous_cycle.coordinator import coordinator

logger = get_logger(__name__)
router = APIRouter(prefix="/autonomous-cycle", tags=["autonomous-cycle"])


def _run_response_from(payload: dict | None) -> AutonomousCycleRunResponse | None:
    if not payload:
        return None
    data = dict(payload)
    stats = data.get("stats") or {}
    if not isinstance(stats, dict):
        stats = {}
    data["stats"] = stats
    allowed = set(AutonomousCycleRunResponse.model_fields)
    data = {k: v for k, v in data.items() if k in allowed}
    return AutonomousCycleRunResponse(**data)


@router.post("/run", response_model=AutonomousCycleStartResponse)
async def start_autonomous_cycle(
    request: AutonomousCycleStartRequest, db: Session = Depends(get_db)
) -> AutonomousCycleStartResponse:
    # E5-R15: DB-backed atomic claim prevents simultaneous runs even across
    # process restarts / multiple workers. max_applications is display-only.
    acquired, run_token, snap = coordinator.try_acquire(
        max_applications=request.max_applications, db=db
    )
    if not acquired:
        active = snap.get("active_run") or {}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "AUTONOMOUS_CYCLE_RUNNING",
                "message": "An autonomous cycle is already running",
                "run_id": active.get("run_id"),
                "run_token": active.get("run_token"),
            },
        )

    try:
        # E5-R10: max_applications is not enforced as an application-count
        # cap. The cycle processes every eligible matching job.
        cycle = AutonomousCycle(
            max_applications=request.max_applications,
            dry_run=False,
            enable_cli_output=False,
            run_token=run_token,
        )
    except Exception:
        coordinator.fail(run_token, "Unable to initialize autonomous cycle.", db=db)
        logger.exception("autonomous_cycle_initialization_failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to start autonomous cycle"},
        )

    async def run_cycle_background() -> None:
        try:
            result = await cycle.run()
            coordinator.complete(run_token, result)
            logger.info(
                "autonomous_cycle_completed",
                extra={"status": result.get("status"), "run_id": result.get("run_id")},
            )
        except Exception:
            coordinator.fail(run_token, "Autonomous cycle execution failed unexpectedly.")
            logger.exception("autonomous_cycle_failed")

    asyncio.create_task(run_cycle_background())
    return AutonomousCycleStartResponse(
        run_id=None,
        run_token=run_token,
        status="RUNNING",
        max_applications=request.max_applications,
        message="Autonomous cycle started",
    )


@router.post("/stop", response_model=AutonomousCycleStopResponse)
async def stop_autonomous_cycle(
    request: AutonomousCycleStopRequest | None = None,
    db: Session = Depends(get_db),
) -> AutonomousCycleStopResponse:
    """Request cancellation of the active cycle (idempotent).

    The running cycle checks this flag at safe boundaries (between jobs /
    before starting an application) and does not begin a new application
    after cancellation is requested.
    """
    result = coordinator.request_cancel(
        run_token=(request.run_token if request else None), db=db
    )
    snap = result.get("snapshot") or {}
    active = snap.get("active_run") or {}
    cancelling = active.get("status") == "CANCELLING" or active.get("cancel_requested") is True
    return AutonomousCycleStopResponse(
        cancel_requested=bool(result.get("changed") or cancelling),
        active_state=snap.get("active_state", "IDLE"),
        message=result.get("message", "Stop requested"),
        run_id=active.get("run_id"),
        run_token=active.get("run_token"),
        status=active.get("status"),
    )


@router.get("/status", response_model=AutonomousCycleStatusResponse)
async def get_autonomous_cycle_status(db: Session = Depends(get_db)) -> AutonomousCycleStatusResponse:
    """Read runtime diagnostics only; this endpoint cannot start a cycle."""
    snapshot = coordinator.snapshot(db=db)
    return AutonomousCycleStatusResponse(
        active_state=snapshot["active_state"],
        lock_held=snapshot["lock_held"],
        active_run=_run_response_from(snapshot["active_run"]),
        last_run=_run_response_from(snapshot["last_run"]),
    )
