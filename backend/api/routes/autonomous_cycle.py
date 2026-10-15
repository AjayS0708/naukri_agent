"""Autonomous-cycle control and strictly read-only runtime diagnostics."""
import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.core.logging import get_logger
from backend.models.screening import PendingQuestion, ScreeningAnswer
from backend.schemas.autonomous_cycle import (
    AutonomousCycleRunResponse,
    AutonomousCycleStartRequest,
    AutonomousCycleStartResponse,
    AutonomousCycleStatusResponse,
    AutonomousCycleStopRequest,
    AutonomousCycleStopResponse,
)
from backend.schemas.screening import (
    AnswerQuestionRequest,
    AnswerQuestionResponse,
    PendingQuestionResponse,
    ScreeningAnswerResponse,
    ScreeningAnswerUpdateRequest,
)
from backend.services.applications.answer_memory import (
    ScreeningAnswerService,
    is_sensitive_question,
    normalize_option,
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
    last_run = _run_response_from(snapshot["last_run"])
    # E5-R29: the shared control row also stores manual-apply and scheduled
    # runs; the autonomous-cycle panel only reports actual autonomous cycles.
    if last_run is not None:
        run_kind = (last_run.stats or {}).get("run_kind", "AUTONOMOUS")
        if run_kind != "AUTONOMOUS":
            last_run = None
    return AutonomousCycleStatusResponse(
        active_state=snapshot["active_state"],
        lock_held=snapshot["lock_held"],
        active_run=_run_response_from(snapshot["active_run"]),
        last_run=last_run,
    )


# E5-R21: human-in-the-loop screening answers --------------------------------


def _screening_answer_response(row: ScreeningAnswer) -> ScreeningAnswerResponse:
    return ScreeningAnswerResponse(
        id=row.id,
        question_text=row.question_text,
        answer=row.answer,
        answer_type=row.answer_type,
        scope=row.scope,
        employer=row.employer,
        job_id=row.job_id,
        source=row.source,
        verification_status=row.verification_status,
        context_sensitive=bool(row.context_sensitive),
        reuse_count=row.reuse_count or 0,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/pending-question", response_model=PendingQuestionResponse)
async def get_pending_question(db: Session = Depends(get_db)) -> PendingQuestionResponse:
    """Return the screening question the active run is waiting on, if any."""
    snapshot = coordinator.snapshot(db=db)
    active = snapshot.get("active_run") or {}
    pending_id = active.get("waiting_for_question_id")
    if not active.get("waiting_for_user") or not pending_id:
        return PendingQuestionResponse(found=False)
    row = db.get(PendingQuestion, pending_id)
    if row is None or row.status != "WAITING":
        return PendingQuestionResponse(found=False)
    return PendingQuestionResponse(
        found=True,
        pending_question_id=row.id,
        run_token=row.run_token,
        question_text=row.question_text,
        question_type=row.question_type,
        options=row.options,
        employer=row.employer,
        job_title=row.job_title,
        job_id=row.job_id,
        application_id=row.application_id,
        status=row.status,
        created_at=row.created_at,
    )


@router.post("/answer-question", response_model=AnswerQuestionResponse)
async def answer_pending_question(
    request: AnswerQuestionRequest, db: Session = Depends(get_db)
) -> AnswerQuestionResponse:
    """Answer or skip the active run's pending screening question.

    Validations: 404 unknown id, 409 stale/already-handled/foreign-run, 400
    missing answer, invalid option, sensitive (credential) question, or a
    context-sensitive answer requested for GLOBAL reuse without explicit
    authorisation. On success the run resumes on its next poll.
    """
    row = db.get(PendingQuestion, request.pending_question_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "PENDING_QUESTION_NOT_FOUND", "message": "Unknown question id"},
        )
    if row.status != "WAITING":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PENDING_QUESTION_NOT_WAITING",
                "message": "Question was already handled",
                "status": row.status,
            },
        )

    snapshot = coordinator.snapshot(db=db)
    active = snapshot.get("active_run") or {}
    if request.run_token and active.get("run_token") != request.run_token:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PENDING_QUESTION_STALE",
                "message": "Question does not belong to the given run",
            },
        )
    if active.get("waiting_for_question_id") != row.id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PENDING_QUESTION_STALE",
                "message": "Question is no longer the active run's pending question",
            },
        )

    if request.skip:
        row.status = "SKIPPED"
        row.answered_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        db.commit()
        if row.run_token:
            coordinator.clear_waiting(row.run_token, db=db)
        return AnswerQuestionResponse(
            status="SKIPPED",
            pending_question_id=row.id,
            message="Job will be skipped; the run continues with the next candidate",
        )

    answer = (request.answer or "").strip()
    if not answer:
        raise HTTPException(
            status_code=400,
            detail={"code": "ANSWER_REQUIRED", "message": "An answer is required"},
        )

    # E5-R21: credentials/OTPs/tokens are never stored anywhere.
    if is_sensitive_question(row.question_text):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "SENSITIVE_QUESTION",
                "message": (
                    "This question cannot be answered through the agent. "
                    "Complete it manually or skip the job."
                ),
            },
        )

    # Choice questions: the answer must be one of the offered options.
    if row.options:
        normalized_options = {normalize_option(option) for option in row.options}
        if normalize_option(answer) not in normalized_options:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_OPTION",
                    "message": "Answer must be one of the offered options",
                    "options": row.options,
                },
            )

    scope = (request.scope or "JOB").upper()
    if scope not in ("JOB", "EMPLOYER", "GLOBAL"):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_SCOPE", "message": f"Unknown scope: {scope}"},
        )

    saved = False
    if request.remember:
        try:
            ScreeningAnswerService(db).save_user_answer(
                row.question_text,
                answer,
                scope=scope,
                employer=row.employer,
                job_id=row.job_id,
                options=row.options,
                source="USER",
                answer_type=row.question_type or "TEXT",
                origin_pending_question_id=row.id,
                allow_global_reuse=request.allow_global_reuse,
            )
            saved = True
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "MEMORY_SAVE_REFUSED", "message": str(exc)},
            )

    row.status = "ANSWERED"
    row.answer = answer
    row.answer_scope = scope
    row.answered_via = "USER"
    row.answered_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    db.commit()
    if row.run_token:
        coordinator.clear_waiting(row.run_token, db=db)

    return AnswerQuestionResponse(
        status="ANSWERED",
        pending_question_id=row.id,
        saved_to_memory=saved,
        answer_scope=scope if saved else None,
        message="Answer recorded; the run will resume",
    )


# E5-R21: screening-answer memory management ---------------------------------


@router.get("/screening-answers", response_model=list[ScreeningAnswerResponse])
async def list_screening_answers(db: Session = Depends(get_db)) -> list[ScreeningAnswerResponse]:
    """Inspect every saved reusable screening answer."""
    rows = ScreeningAnswerService(db).list_answers()
    return [_screening_answer_response(row) for row in rows]


@router.put("/screening-answers/{answer_id}", response_model=ScreeningAnswerResponse)
async def update_screening_answer(
    answer_id: int,
    request: ScreeningAnswerUpdateRequest,
    db: Session = Depends(get_db),
) -> ScreeningAnswerResponse:
    """Edit an existing saved answer; widening to GLOBAL needs authorisation."""
    try:
        row = ScreeningAnswerService(db).update_answer(
            answer_id,
            answer=request.answer,
            scope=request.scope,
            allow_global_reuse=request.allow_global_reuse,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "MEMORY_SAVE_REFUSED", "message": str(exc)},
        )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SCREENING_ANSWER_NOT_FOUND", "message": "Unknown answer id"},
        )
    return _screening_answer_response(row)


@router.delete("/screening-answers/{answer_id}")
async def delete_screening_answer(
    answer_id: int, db: Session = Depends(get_db)
) -> dict:
    """Delete a saved answer (it will be asked again when encountered)."""
    removed = ScreeningAnswerService(db).delete_answer(answer_id)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail={"code": "SCREENING_ANSWER_NOT_FOUND", "message": "Unknown answer id"},
        )
    return {"deleted": True, "id": answer_id}
