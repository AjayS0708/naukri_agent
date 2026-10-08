"""Process-local runtime state for autonomous-cycle execution."""
from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Any, Optional


class AutonomousCycleRuntime:
    """Owns the execution lock, active run, and last completed result."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active_run: Optional[dict[str, Any]] = None
        self._last_run: Optional[dict[str, Any]] = None

    @property
    def lock_held(self) -> bool:
        return self._lock.locked()

    def start(self, max_applications: int) -> Optional[dict[str, Any]]:
        """Atomically begin a run, returning None when another run is active."""
        if not self._lock.acquire(blocking=False):
            return None
        self._active_run = {"run_id": None, "status": "RUNNING", "max_applications": max_applications, "started_at": datetime.now(UTC)}
        return self._active_run.copy()

    def complete(self, result: dict[str, Any]) -> dict[str, Any]:
        """Finish the active run and always return the runtime to IDLE."""
        active = self._active_run or {}
        terminal_status = result.get("status", "FAILED")
        if terminal_status not in {"COMPLETED", "FAILED"}:
            terminal_status = "FAILED"
        self._last_run = {
            "run_id": result.get("run_id", active.get("run_id")), "status": terminal_status,
            "max_applications": active.get("max_applications"), "started_at": active.get("started_at"),
            "completed_at": datetime.now(UTC), "stats": result.get("stats", {}), "error": result.get("error"),
        }
        self._active_run = None
        if self._lock.locked():
            self._lock.release()
        return self._last_run.copy()

    def fail(self, error: str, *, run_id: Optional[int] = None) -> dict[str, Any]:
        """Record a failure and release the lock even during startup errors."""
        return self.complete({"status": "FAILED", "run_id": run_id, "stats": {}, "error": error})

    def snapshot(self) -> dict[str, Any]:
        """Return diagnostics only; this method never starts execution."""
        return {"active_state": "RUNNING" if self._active_run else "IDLE", "active_run": self._active_run.copy() if self._active_run else None, "last_run": self._last_run.copy() if self._last_run else None, "lock_held": self.lock_held}
