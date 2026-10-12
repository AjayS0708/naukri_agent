"""E5-R15: cancellation boundaries in AutonomousCycle (unit, no live browser)."""
import pytest

from backend.services.autonomous_cycle.service import AutonomousCycle


def test_terminal_outcome_cancelled_is_not_completed() -> None:
    cycle = AutonomousCycle(enable_cli_output=False)
    cycle.stop_reason = "Cancellation requested at start of cycle"
    cycle.stop_is_normal = True
    code, status = cycle._terminal_outcome()
    assert code == 0
    assert status == "CANCELLED"
    assert status != "COMPLETED"


def test_terminal_outcome_auth_is_login_required_not_completed() -> None:
    """E5-R16: a logged-out session is LOGIN_REQUIRED, never COMPLETED/FAILED."""
    cycle = AutonomousCycle(enable_cli_output=False)
    cycle.stop_reason = "Authentication required"
    cycle.stop_is_normal = False
    code, status = cycle._terminal_outcome()
    assert code == 2
    assert status == "LOGIN_REQUIRED"
    assert status != "COMPLETED"


def test_check_cancellation_no_token_never_stops() -> None:
    cycle = AutonomousCycle(enable_cli_output=False)
    assert cycle._check_cancellation("start of cycle") is False
    assert cycle.stop_reason is None


def test_check_cancellation_with_coordinator(db, monkeypatch) -> None:
    from backend.services.autonomous_cycle.coordinator import CycleCoordinator

    coord = CycleCoordinator()
    ok, token, _ = coord.try_acquire(db=db)
    assert ok
    cycle = AutonomousCycle(enable_cli_output=False, run_token=coord.snapshot(db=db)["active_run"]["run_token"])
    assert cycle._check_cancellation("start of cycle") is False

    coord.request_cancel(run_token=token, db=db)
    # Patch coordinator lookup to use the same test session
    monkeypatch.setattr(
        "backend.services.autonomous_cycle.coordinator.coordinator.is_cancellation_requested",
        lambda run_token, db=None: coord.is_cancellation_requested(run_token, db=db),
    )
    assert cycle._check_cancellation("before job 1") is True
    assert "Cancellation requested" in cycle.stop_reason
    assert cycle.stop_is_normal is True


def test_native_only_filter_preserved_in_service_sql() -> None:
    """Goal D: recovery application path remains NAUKRI_NATIVE-only."""
    import inspect
    from backend.services.autonomous_cycle import service as service_module

    source = inspect.getsource(service_module)
    assert "Job.application_mode == 'NAUKRI_NATIVE'" in source
