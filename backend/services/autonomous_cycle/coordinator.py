"""DB-backed singleton control row for autonomous-cycle coordination.

E5-R15: Fixes simultaneous/intermingled runs. The previous process-local
``threading.Lock`` was lost on restart and unprotected across workers. This
row is claimed atomically via a single UPDATE so only one run can hold
``status='RUNNING'`` at a time (single SQLite writer + WHERE guard).
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.logging import get_logger
from backend.database import database as database_module
from backend.models.cycle_run import CycleRunControl

logger = get_logger(__name__)

CONTROL_ROW_ID = 1


def _pid_alive(pid: Optional[int]) -> bool:
    """Best-effort liveness check for a local process id (Windows + POSIX)."""
    if not pid or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class CycleCoordinator:
    """Atomic acquire / cancel / complete for the singleton autonomous cycle."""

    def ensure_row(self, db: Session) -> CycleRunControl:
        row = db.get(CycleRunControl, CONTROL_ROW_ID)
        if row is not None:
            return row
        row = CycleRunControl(id=CONTROL_ROW_ID, status="IDLE")
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = db.get(CycleRunControl, CONTROL_ROW_ID)
            if existing is None:
                raise
            return existing
        db.refresh(row)
        return row

    def try_acquire(
        self,
        max_applications: Optional[int] = None,
        *,
        db: Optional[Session] = None,
    ) -> tuple[bool, Optional[str], dict[str, Any]]:
        """Atomically claim the cycle. Returns (acquired, run_token, snapshot)."""
        owns_session = db is None
        if owns_session:
            db = database_module.SessionLocal()
        try:
            self.ensure_row(db)
            now = datetime.now(UTC)
            row = db.get(CycleRunControl, CONTROL_ROW_ID)
            if row is not None and row.status in ("RUNNING", "CANCELLING"):
                if _pid_alive(row.pid):
                    return False, None, self._snapshot_locked(db)
                logger.warning(
                    "autonomous_cycle_orphaned_lock_adopted",
                    extra={"previous_pid": row.pid, "previous_status": row.status},
                )
                # Dead owner: clear the orphan so the IDLE claim below succeeds.
                row.status = "IDLE"
                row.pid = None
                db.commit()

            run_token = f"cycle-{int(now.timestamp() * 1000)}-{os.getpid()}"
            claim = db.execute(
                update(CycleRunControl)
                .where(CycleRunControl.id == CONTROL_ROW_ID)
                .where(CycleRunControl.status == "IDLE")
                .values(
                    status="RUNNING",
                    run_token=run_token,
                    started_at=now,
                    completed_at=None,
                    cancellation_requested_at=None,
                    max_applications=max_applications,
                    discovery_run_id=None,
                    last_result=None,
                    last_error=None,
                    pid=os.getpid(),
                )
            )
            db.commit()
            if claim.rowcount != 1:
                return False, None, self._snapshot_locked(db)
            return True, run_token, self._snapshot_locked(db)
        finally:
            if owns_session:
                db.close()

    def request_cancel(
        self,
        run_token: Optional[str] = None,
        *,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        """Request cancellation of the active run. Idempotent.

        Returns a snapshot-like dict with ``cancel_requested`` and ``changed``.
        """
        owns_session = db is None
        if owns_session:
            db = database_module.SessionLocal()
        try:
            self.ensure_row(db)
            row = db.get(CycleRunControl, CONTROL_ROW_ID)
            if row is None or row.status == "IDLE":
                return {
                    "changed": False,
                    "active": False,
                    "message": "No autonomous cycle is running",
                    "snapshot": self._snapshot_locked(db),
                }
            if run_token and row.run_token and run_token != row.run_token:
                return {
                    "changed": False,
                    "active": True,
                    "message": "Active run does not match the requested run_token",
                    "snapshot": self._snapshot_locked(db),
                }
            if row.status == "CANCELLING":
                return {
                    "changed": False,
                    "active": True,
                    "message": "Cancellation already requested",
                    "snapshot": self._snapshot_locked(db),
                }
            row.status = "CANCELLING"
            row.cancellation_requested_at = datetime.now(UTC)
            db.commit()
            return {
                "changed": True,
                "active": True,
                "message": "Cancellation requested",
                "snapshot": self._snapshot_locked(db),
            }
        finally:
            if owns_session:
                db.close()

    def is_cancellation_requested(self, run_token: str, *, db: Optional[Session] = None) -> bool:
        owns_session = db is None
        if owns_session:
            db = database_module.SessionLocal()
        try:
            row = db.get(CycleRunControl, CONTROL_ROW_ID)
            if row is None or not run_token:
                return False
            if row.run_token != run_token:
                return False
            return row.status == "CANCELLING" or row.cancellation_requested_at is not None
        finally:
            if owns_session:
                db.close()

    def set_discovery_run_id(
        self,
        run_token: str,
        discovery_run_id: Optional[int],
        *,
        db: Optional[Session] = None,
    ) -> None:
        owns_session = db is None
        if owns_session:
            db = database_module.SessionLocal()
        try:
            row = db.get(CycleRunControl, CONTROL_ROW_ID)
            if row is None or row.run_token != run_token:
                return
            row.discovery_run_id = discovery_run_id
            db.commit()
        finally:
            if owns_session:
                db.close()

    def complete(
        self,
        run_token: str,
        result: dict[str, Any],
        *,
        db: Optional[Session] = None,
    ) -> dict[str, Any]:
        """Release the claim and store the terminal result (always IDLE)."""
        owns_session = db is None
        if owns_session:
            db = database_module.SessionLocal()
        try:
            self.ensure_row(db)
            row = db.get(CycleRunControl, CONTROL_ROW_ID)
            terminal_status = result.get("status", "FAILED")
            # LOGIN_REQUIRED (E5-R16) is a legitimate terminal state: the run
            # stopped because the Naukri session needs a manual sign-in.
            if terminal_status not in {"COMPLETED", "FAILED", "CANCELLED", "LOGIN_REQUIRED"}:
                terminal_status = "FAILED"
            payload = {
                "run_id": result.get("run_id"),
                "status": terminal_status,
                "max_applications": None,
                "started_at": None,
                "completed_at": datetime.now(UTC).isoformat(),
                "stats": result.get("stats", {}),
                "error": result.get("error"),
            }
            if row is None:
                return payload
            payload["max_applications"] = row.max_applications
            payload["started_at"] = row.started_at.isoformat() if row.started_at else None
            if not run_token or row.run_token == run_token:
                row.status = "IDLE"
                row.completed_at = datetime.now(UTC)
                row.last_result = payload
                row.last_error = result.get("error")
                row.pid = None
                # Keep run_token for last_run correlation until next acquire.
            db.commit()
            return payload
        finally:
            if owns_session:
                db.close()

    def fail(self, run_token: Optional[str], error: str, *, db: Optional[Session] = None) -> dict[str, Any]:
        return self.complete(
            run_token or "",
            {"status": "FAILED", "run_id": None, "stats": {}, "error": error},
            db=db,
        )

    def snapshot(self, *, db: Optional[Session] = None) -> dict[str, Any]:
        owns_session = db is None
        if owns_session:
            db = database_module.SessionLocal()
        try:
            self.ensure_row(db)
            return self._snapshot_locked(db)
        finally:
            if owns_session:
                db.close()

    def _snapshot_locked(self, db: Session) -> dict[str, Any]:
        row = db.get(CycleRunControl, CONTROL_ROW_ID)
        if row is None:
            return {
                "active_state": "IDLE",
                "lock_held": False,
                "active_run": None,
                "last_run": None,
            }
        active = None
        if row.status in ("RUNNING", "CANCELLING"):
            active = {
                "run_id": row.discovery_run_id,
                "run_token": row.run_token,
                "status": row.status,
                "max_applications": row.max_applications,
                "started_at": row.started_at,
                "completed_at": None,
                "stats": {},
                "error": None,
                "cancel_requested": row.status == "CANCELLING",
            }
        last_run = None
        if row.last_result:
            stored = dict(row.last_result)
            if isinstance(stored.get("stats"), str):
                try:
                    stored["stats"] = json.loads(stored["stats"])
                except json.JSONDecodeError:
                    stored["stats"] = {}
            if "cancel_requested" not in stored:
                stored["cancel_requested"] = stored.get("status") == "CANCELLED"
            last_run = stored
        return {
            "active_state": "RUNNING" if active else "IDLE",
            "lock_held": bool(active),
            "active_run": active,
            "last_run": last_run,
        }


coordinator = CycleCoordinator()
