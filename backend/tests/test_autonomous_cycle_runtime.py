"""Unit tests for process-local autonomous-cycle runtime recovery semantics."""
from backend.services.autonomous_cycle.runtime import AutonomousCycleRuntime


def test_fresh_runtime_is_idle() -> None:
    runtime = AutonomousCycleRuntime()
    snapshot = runtime.snapshot()
    assert snapshot["active_state"] == "IDLE"
    assert snapshot["last_run"] is None
    assert snapshot["lock_held"] is False


def test_success_returns_to_idle_and_retains_history() -> None:
    runtime = AutonomousCycleRuntime()
    runtime.start(2)
    assert runtime.snapshot()["active_state"] == "RUNNING"

    runtime.complete({"status": "COMPLETED", "run_id": 44, "stats": {"applied": 0}})
    snapshot = runtime.snapshot()
    assert snapshot["active_state"] == "IDLE"
    assert snapshot["lock_held"] is False
    assert snapshot["last_run"]["run_id"] == 44
    assert snapshot["last_run"]["status"] == "COMPLETED"


def test_failure_returns_to_idle_releases_lock_and_retains_error() -> None:
    runtime = AutonomousCycleRuntime()
    runtime.start(1)
    runtime.fail("Browser startup failed.")
    snapshot = runtime.snapshot()
    assert snapshot["active_state"] == "IDLE"
    assert snapshot["lock_held"] is False
    assert snapshot["last_run"]["status"] == "FAILED"
    assert snapshot["last_run"]["error"] == "Browser startup failed."


def test_second_run_is_rejected_only_while_active_then_allowed() -> None:
    runtime = AutonomousCycleRuntime()
    assert runtime.start(1) is not None
    assert runtime.start(1) is None
    runtime.complete({"status": "FAILED", "stats": {}})
    assert runtime.start(1) is not None
