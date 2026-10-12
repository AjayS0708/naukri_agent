"""Cross-process lock for the persistent Playwright user-data directory.

E5-R15 Goal C: prevent two agent processes from opening the same Chrome
profile simultaneously (which surfaces as a Playwright launch failure).
The lock file lives next to the profile directory and records the owning
PID. A live owner produces a clear conflict error; a dead owner is stolen.
We never kill other processes or delete the profile directory.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from backend.core.logging import get_logger

logger = get_logger(__name__)

LOCK_SUFFIX = ".lock"


def _pid_alive(pid: Optional[int]) -> bool:
    """Best-effort liveness check; works on Windows and POSIX."""
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


class BrowserSessionLockError(RuntimeError):
    """Raised when the browser profile is owned by another live process."""


class BrowserSessionLock:
    """File lock protecting a Playwright persistent-context profile."""

    def __init__(self, user_data_dir: str | Path):
        self.user_data_dir = Path(user_data_dir)
        self.lock_path = self.user_data_dir.parent / f"{self.user_data_dir.name}{LOCK_SUFFIX}"
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def _read_owner(self) -> dict[str, Any]:
        try:
            return json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def try_acquire(self) -> bool:
        """Atomically claim the profile. False if a live owner holds it."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"pid": os.getpid(), "acquired_at": time.time(), "user_data_dir": str(self.user_data_dir)}
        )
        # O_CREAT|O_EXCL: atomic create; fails if the file already exists.
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            owner = self._read_owner()
            owner_pid = owner.get("pid")
            if _pid_alive(owner_pid):
                logger.warning(
                    "browser_session_profile_locked",
                    extra={"lock_path": str(self.lock_path), "owner_pid": owner_pid},
                )
                return False
            # Dead owner: steal the stale lock.
            try:
                self.lock_path.unlink(missing_ok=True)
            except OSError:
                return False
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
        self._held = True
        return True

    def release(self) -> None:
        """Release only if we hold the lock. Never deletes a foreign lock."""
        if not self._held:
            return
        try:
            owner = self._read_owner()
            if owner.get("pid") == os.getpid():
                self.lock_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("browser_session_lock_release_failed", extra={"lock_path": str(self.lock_path)})
        finally:
            self._held = False

    def owner_pid(self) -> Optional[int]:
        return self._read_owner().get("pid")

    def conflict_message(self) -> str:
        pid = self.owner_pid()
        return (
            f"Browser session profile is in use by another process (pid={pid}). "
            f"Lock: {self.lock_path}. Stop that Naukri Agent run and retry."
        )
