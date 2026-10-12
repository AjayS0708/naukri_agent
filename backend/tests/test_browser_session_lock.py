"""E5-R15: browser persistent-profile lock (single process owns the profile)."""
from pathlib import Path

import pytest

from backend.services.browser_session_lock import BrowserSessionLock, LOCK_SUFFIX


@pytest.fixture
def profile_dir(tmp_path: Path):
    user_data = tmp_path / "browser_session"
    user_data.mkdir()
    return user_data


def test_acquire_release_roundtrip(profile_dir: Path) -> None:
    lock = BrowserSessionLock(profile_dir)
    assert lock.try_acquire() is True
    assert lock.held is True
    assert lock.lock_path == profile_dir.parent / f"{profile_dir.name}{LOCK_SUFFIX}"
    assert lock.lock_path.exists()
    lock.release()
    assert lock.held is False
    assert not lock.lock_path.exists()


def test_second_acquire_conflicts_while_owner_alive(profile_dir: Path) -> None:
    first = BrowserSessionLock(profile_dir)
    second = BrowserSessionLock(profile_dir)
    assert first.try_acquire() is True
    assert second.try_acquire() is False
    msg = second.conflict_message()
    assert "in use" in msg
    assert str(second.lock_path) in msg
    # First owner still holds; release frees for next claim.
    first.release()
    assert second.try_acquire() is True
    second.release()


def test_stale_lock_from_dead_pid_is_stolen(profile_dir: Path) -> None:
    import json
    lock_path = profile_dir.parent / f"{profile_dir.name}{LOCK_SUFFIX}"
    # PID 1 is typically alive on Windows; use a high unlikely PID that is dead.
    # On Windows os.kill for a non-existent process raises; _pid_alive returns False.
    lock_path.write_text(json.dumps({"pid": 999999, "acquired_at": 0.0}), encoding="utf-8")
    lock = BrowserSessionLock(profile_dir)
    assert lock.try_acquire() is True
    lock.release()


def test_release_does_not_delete_foreign_lock(profile_dir: Path) -> None:
    import json
    lock_path = profile_dir.parent / f"{profile_dir.name}{LOCK_SUFFIX}"
    lock_path.write_text(json.dumps({"pid": os_getpid_plus_one(), "acquired_at": 0.0}), encoding="utf-8")
    foreign = BrowserSessionLock(profile_dir)
    # Not held by us — release must be a no-op for the file.
    foreign.release()
    assert lock_path.exists()


def os_getpid_plus_one() -> int:
    import os
    return os.getpid() + 100000
