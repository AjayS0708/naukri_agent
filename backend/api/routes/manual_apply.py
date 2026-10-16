"""Manual apply queue: apply to previously discovered jobs on demand (E5-R29).

Unlike the autonomous cycle, this flow never runs discovery. The operator
selects jobs that are already in the local database; every safety gate is the
same code path the autonomous cycle uses (protection, relevance, hard filters,
external boundary, evidence verification, HITL screening answers).

The run shares the singleton cycle lock with the autonomous cycle and the
scheduler's apply phase, so only one apply process can hold the browser
session at a time.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.core.logging import get_logger
from backend.schemas.manual_apply import (
    ManualApplyEligibleResponse,
    ManualApplyRunSummary,
    ManualApplyStartRequest,
    ManualApplyStartResponse,
    ManualApplyStatusResponse,
    ManualApplyStopRequest,
    ManualApplyStopResponse,
)
from backend.services.autonomous_cycle.coordinator import coordinator
from backend.services.manual_apply.service import ManualApplyService, get_last_manual_run

logger = get_logger(__name__)
router = APIRouter(prefix="/manual-apply", tags=["manual-apply"])


def _active_summary(snapshot: dict) -> ManualApplyRunSummary | None:
    """Map the coordinator's active run (manual or not) to a summary."""
    active = snapshot.get("active_run")
    if not active:
        return None
    progress = active.get("progress") or {}
    return ManualApplyRunSummary(
        run_token=active.get("run_token"),
        status=active.get("status") or "RUNNING",
        started_at=active.get("started_at"),
        completed_at=None,
        stats={},
        error=None,
        progress=progress,
        waiting_for_user=bool(active.get("waiting_for_user")),
        waiting_for_question_id=active.get("waiting_for_question_id"),
        cancel_requested=bool(active.get("cancel_requested")),
    )


@router.get("/eligible", response_model=ManualApplyEligibleResponse)
async def list_manual_apply_eligible(
    limit: int = 200,
    offset: int = 0,
    only_eligible: bool = False,
    q: str = "",
    db: Session = Depends(get_db),
) -> ManualApplyEligibleResponse:
    """Previously discovered jobs with a per-job eligibility verdict.

    Read-only. Never starts a run and never touches discovery.
    Pagination (limit/offset) and the optional case-insensitive title/company
    search (q) are applied server-side over a stable ordering; counts always
    describe the whole search-matched set.
    """
    service = ManualApplyService(db)
    payload = service.list_eligible(
        limit=limit, offset=offset, only_eligible=only_eligible, q=q
    )
    return ManualApplyEligibleResponse(**payload)


@router.post("/start", response_model=ManualApplyStartResponse)
async def start_manual_apply(
    request: ManualApplyStartRequest, db: Session = Depends(get_db)
) -> ManualApplyStartResponse:
    """Start a manual apply run over explicitly selected job ids.

    409 when any other apply process (autonomous cycle, manual apply, or the
    scheduler's apply phase) holds the singleton lock. Selected ids are
    re-validated at start; ineligible ones are dropped and reported, never
    silently attempted.
    """
    acquired, run_token, snap = coordinator.try_acquire(max_applications=None, db=db)
    if not acquired:
        active = snap.get("active_run") or {}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "APPLY_PROCESS_ALREADY_RUNNING",
                "message": (
                    "Another apply process is already running "
                    "(autonomous cycle, manual apply, or scheduler)"
                ),
                "run_id": active.get("run_id"),
                "run_token": active.get("run_token"),
            },
        )

    service = ManualApplyService(db)
    accepted, dropped = service.validate_job_ids(request.job_ids)
    if not accepted:
        # Nothing to do — release the lock immediately with an honest result.
        coordinator.complete(
            run_token,
            {
                "run_id": None,
                "status": "COMPLETED",
                "stats": {
                    "run_kind": "MANUAL_APPLY",
                    "requested": len(request.job_ids),
                    "processed": 0,
                    "applied": 0,
                    "dropped": len(dropped),
                },
                "error": None,
            },
            db=db,
        )
        return ManualApplyStartResponse(
            status="NO_ELIGIBLE_JOBS",
            run_token=None,
            accepted_job_ids=[],
            dropped_job_ids=dropped,
            message="No selected job passed the eligibility checks",
        )

    try:
        asyncio.create_task(
            service.run(accepted, run_token, dry_run=request.dry_run)
        )
    except Exception:
        coordinator.fail(run_token, "Unable to initialize the manual apply run.", db=db)
        logger.exception("manual_apply_start_failed")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to start the manual apply run",
            },
        )

    logger.info(
        "manual_apply_started",
        extra={
            "accepted": len(accepted),
            "accepted_ids": list(accepted),
            "dropped": len(dropped),
            "dropped_ids": list(dropped),
            "dry_run": request.dry_run,
        },
    )
    return ManualApplyStartResponse(
        status="RUNNING",
        run_token=run_token,
        accepted_job_ids=accepted,
        dropped_job_ids=dropped,
        message=f"Manual apply started for {len(accepted)} job(s)",
    )


@router.get("/status", response_model=ManualApplyStatusResponse)
async def get_manual_apply_status(db: Session = Depends(get_db)) -> ManualApplyStatusResponse:
    """Live status of the manual apply queue (read-only).

    Shares the singleton control row with the autonomous cycle: when an
    autonomous run (or the scheduler) holds the lock, the active run is still
    reported so the UI can explain why a manual start was refused.
    """
    snapshot = coordinator.snapshot(db=db)
    active_run = None
    if snapshot.get("active_run"):
        active_run = _active_summary(snapshot)

    last_raw = get_last_manual_run()
    last_manual_run = None
    if last_raw:
        last_manual_run = ManualApplyRunSummary(
            run_token=last_raw.get("run_token"),
            status=last_raw.get("status", "COMPLETED"),
            started_at=last_raw.get("started_at"),
            completed_at=last_raw.get("completed_at"),
            stats=last_raw.get("stats") or {},
            error=last_raw.get("error"),
            progress=None,
            waiting_for_user=False,
            waiting_for_question_id=None,
            cancel_requested=False,
        )
    else:
        # E5-R30: the in-process summary is lost on restart. Fall back to the
        # durable cycle_run_control.last_result when it was a manual apply
        # run, so the dashboard does not pretend the last run never happened.
        try:
            from backend.models.cycle_run import CycleRunControl
            from backend.services.autonomous_cycle.coordinator import CONTROL_ROW_ID

            row = db.get(CycleRunControl, CONTROL_ROW_ID)
            stored = dict(row.last_result) if row is not None and row.last_result else {}
            stored_stats = stored.get("stats") or {}
            if stored and stored_stats.get("run_kind") == "MANUAL_APPLY":
                last_manual_run = ManualApplyRunSummary(
                    run_token=row.run_token,
                    status=stored.get("status") or "COMPLETED",
                    started_at=stored.get("started_at"),
                    completed_at=stored.get("completed_at"),
                    stats=stored_stats,
                    error=stored.get("error"),
                    progress=None,
                    waiting_for_user=False,
                    waiting_for_question_id=None,
                    cancel_requested=False,
                )
        except Exception:
            logger.debug("persisted last manual run lookup failed", exc_info=True)

    return ManualApplyStatusResponse(
        active_state=snapshot["active_state"],
        lock_held=snapshot["lock_held"],
        active_run=active_run,
        last_manual_run=last_manual_run,
        pending_question_available=bool(
            active_run and active_run.waiting_for_question_id
        ),
    )


@router.post("/stop", response_model=ManualApplyStopResponse)
async def stop_manual_apply(
    request: ManualApplyStopRequest | None = None,
    db: Session = Depends(get_db),
) -> ManualApplyStopResponse:
    """Request cancellation of the active apply run (idempotent).

    The runner checks the flag at safe boundaries (between jobs / before
    starting an application) and never begins a new application after Stop.
    """
    result = coordinator.request_cancel(
        run_token=(request.run_token if request else None), db=db
    )
    snap = result.get("snapshot") or {}
    active = snap.get("active_run") or {}
    cancelling = (
        active.get("status") == "CANCELLING" or active.get("cancel_requested") is True
    )
    return ManualApplyStopResponse(
        cancel_requested=bool(result.get("changed") or cancelling),
        active_state=snap.get("active_state", "IDLE"),
        message=result.get("message", "Stop requested"),
    )
