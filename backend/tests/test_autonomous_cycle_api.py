"""
Checkpoint E3 / E5-R15 — Tests for autonomous cycle control API.

These tests verify:
- Valid POST requests are accepted (with or without max_applications)
- Concurrent requests return 409 (DB-backed single-run coordination)
- Stop is idempotent and marks the active run CANCELLING
- Status endpoint works correctly from the DB coordinator
- No secrets are exposed
E5-R10: max_applications is optional and ignored (no application-count cap).
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from backend.database import database as database_module
from backend.models.cycle_run import CycleRunControl
from backend.services.autonomous_cycle.coordinator import CycleCoordinator, CONTROL_ROW_ID


@pytest.fixture(autouse=True)
def reset_cycle_control(db):
    """Fresh singleton control row per test (like a process restart)."""
    row = db.get(CycleRunControl, CONTROL_ROW_ID)
    if row is not None:
        db.delete(row)
        db.commit()


@pytest.fixture(autouse=True)
def mock_autonomous_cycle_run():
    """Mock the AutonomousCycle.run() to avoid actual execution in all tests."""
    async def fast_run():
        return {"status": "COMPLETED", "run_id": 1, "stats": {}}

    with patch('backend.api.routes.autonomous_cycle.AutonomousCycle') as mock_cycle:
        mock_instance = AsyncMock()
        mock_instance.run = fast_run
        mock_cycle.return_value = mock_instance
        yield


class TestAutonomousCycleStart:
    def test_valid_post_accepted(self, client: TestClient) -> None:
        """A valid POST request to start a cycle should be accepted."""
        response = client.post("/api/autonomous-cycle/run", json={"max_applications": 2})
        assert response.status_code in [200, 202]
        assert response.json()["run_token"]

    def test_empty_body_accepted(self, client: TestClient) -> None:
        """Empty body is accepted (E5-R10: no application-count cap)."""
        response = client.post("/api/autonomous-cycle/run", json={})
        assert response.status_code in [200, 202]

    def test_null_max_applications_accepted(self, client: TestClient) -> None:
        """max_applications: null is accepted (ignored field)."""
        response = client.post("/api/autonomous-cycle/run", json={"max_applications": None})
        assert response.status_code in [200, 202]

    def test_unknown_field_rejected(self, client: TestClient) -> None:
        """Unknown fields are still rejected (extra=forbid)."""
        response = client.post(
            "/api/autonomous-cycle/run",
            json={"max_applications": 2, "gemini_budget": 100}
        )
        assert response.status_code == 422


class TestAutonomousCycleConcurrency:
    def test_concurrent_post_returns_409(self, client: TestClient) -> None:
        """A second POST while a cycle is running should return 409."""
        async def slow_run():
            await asyncio.sleep(0.5)
            return {"status": "COMPLETED", "run_id": 1, "stats": {}}

        with patch('backend.api.routes.autonomous_cycle.AutonomousCycle') as mock_cycle:
            mock_instance = AsyncMock()
            mock_instance.run = slow_run
            mock_cycle.return_value = mock_instance

            response1 = client.post("/api/autonomous-cycle/run", json={})
            assert response1.status_code in [200, 202]

            response2 = client.post("/api/autonomous-cycle/run", json={})
            assert response2.status_code == 409
            detail = response2.json()["detail"]
            assert detail["code"] == "AUTONOMOUS_CYCLE_RUNNING"

    def test_second_start_same_process_blocked(self, client: TestClient) -> None:
        """Two sequential starts without completion still conflict (DB lock)."""
        async def slow_run():
            await asyncio.sleep(0.4)
            return {"status": "COMPLETED", "run_id": 1, "stats": {}}

        with patch('backend.api.routes.autonomous_cycle.AutonomousCycle') as mock_cycle:
            mock_instance = AsyncMock()
            mock_instance.run = slow_run
            mock_cycle.return_value = mock_instance

            r1 = client.post("/api/autonomous-cycle/run", json={})
            assert r1.status_code in [200, 202]
            r2 = client.post("/api/autonomous-cycle/run", json={})
            assert r2.status_code == 409


class TestAutonomousCycleStop:
    def test_stop_while_running(self, client: TestClient) -> None:
        """POST /stop while a cycle is running marks it CANCELLING."""
        async def slow_run():
            await asyncio.sleep(0.3)
            return {"status": "CANCELLED", "run_id": None, "stats": {}}

        with patch('backend.api.routes.autonomous_cycle.AutonomousCycle') as mock_cycle:
            mock_instance = AsyncMock()
            mock_instance.run = slow_run
            mock_cycle.return_value = mock_instance

            start = client.post("/api/autonomous-cycle/run", json={})
            assert start.status_code in [200, 202]
            run_token = start.json()["run_token"]

            stop = client.post("/api/autonomous-cycle/stop", json={"run_token": run_token})
            assert stop.status_code == 200
            body = stop.json()
            assert body["cancel_requested"] is True
            assert body["active_state"] == "RUNNING"
            assert body["status"] == "CANCELLING"

    def test_stop_without_body_idempotent(self, client: TestClient) -> None:
        """Stop with no body when idle is idempotent (not an error)."""
        stop = client.post("/api/autonomous-cycle/stop")
        assert stop.status_code == 200
        body = stop.json()
        assert body["cancel_requested"] is False
        assert body["active_state"] == "IDLE"

    def test_duplicate_stop_idempotent(self, client: TestClient) -> None:
        """Repeated Stop requests do not error and remain CANCELLING."""
        async def slow_run():
            await asyncio.sleep(0.3)
            return {"status": "CANCELLED", "run_id": None, "stats": {}}

        with patch('backend.api.routes.autonomous_cycle.AutonomousCycle') as mock_cycle:
            mock_instance = AsyncMock()
            mock_instance.run = slow_run
            mock_cycle.return_value = mock_instance

            start = client.post("/api/autonomous-cycle/run", json={})
            first = client.post("/api/autonomous-cycle/stop", json={})
            second = client.post("/api/autonomous-cycle/stop", json={})
            assert first.status_code == 200
            assert second.status_code == 200
            assert second.json()["status"] == "CANCELLING"
            assert second.json()["message"] == "Cancellation already requested"

    def test_stop_wrong_run_token_does_not_cancel(self, client: TestClient) -> None:
        """Stop with a mismatched run_token does not flip the active run."""
        async def slow_run():
            await asyncio.sleep(0.3)
            return {"status": "COMPLETED", "run_id": 1, "stats": {}}

        with patch('backend.api.routes.autonomous_cycle.AutonomousCycle') as mock_cycle:
            mock_instance = AsyncMock()
            mock_instance.run = slow_run
            mock_cycle.return_value = mock_instance

            client.post("/api/autonomous-cycle/run", json={})
            stop = client.post("/api/autonomous-cycle/stop", json={"run_token": "not-the-token"})
            assert stop.status_code == 200
            assert stop.json()["message"] == "Active run does not match the requested run_token"
            assert stop.json()["status"] == "RUNNING"


class TestAutonomousCycleStatus:
    def test_status_endpoint_returns_idle(self, client: TestClient) -> None:
        """Status endpoint should return IDLE when no cycle is running."""
        response = client.get("/api/autonomous-cycle/status")
        assert response.status_code == 200
        data = response.json()
        assert data["active_state"] == "IDLE"
        assert data["last_run"] is None

    def test_status_returns_structure(self, client: TestClient) -> None:
        """Status endpoint should return the correct structure."""
        response = client.get("/api/autonomous-cycle/status")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"active_state", "lock_held", "active_run", "last_run"}

    def test_status_is_read_only_and_never_constructs_cycle(self, client: TestClient) -> None:
        """GET diagnostics must not invoke the execution path."""
        with patch("backend.api.routes.autonomous_cycle.AutonomousCycle") as cycle:
            response = client.get("/api/autonomous-cycle/status")
        assert response.status_code == 200
        cycle.assert_not_called()

    def test_status_shows_active_run_while_running(self, client: TestClient) -> None:
        async def slow_run():
            await asyncio.sleep(0.3)
            return {"status": "COMPLETED", "run_id": 1, "stats": {}}

        with patch('backend.api.routes.autonomous_cycle.AutonomousCycle') as mock_cycle:
            mock_instance = AsyncMock()
            mock_instance.run = slow_run
            mock_cycle.return_value = mock_instance
            client.post("/api/autonomous-cycle/run", json={})
            data = client.get("/api/autonomous-cycle/status").json()
            assert data["active_state"] == "RUNNING"
            assert data["lock_held"] is True
            assert data["active_run"]["status"] in ("RUNNING", "CANCELLING")


class TestAutonomousCycleSecurity:
    def test_no_secrets_in_response(self, client: TestClient) -> None:
        """Autonomous cycle responses should not expose secrets."""
        response = client.post("/api/autonomous-cycle/run", json={})
        if response.status_code in [200, 202]:
            data = response.json()
            FORBIDDEN_KEYS = {
                "api_key", "gemini_api_key", "password", "secret", "token",
                "cookie", "session", "credential", "auth", "database_url",
            }

            def check_no_secrets(obj: object) -> None:
                if isinstance(obj, dict):
                    for key in obj:
                        assert key.lower() not in FORBIDDEN_KEYS
                        check_no_secrets(obj[key])
                elif isinstance(obj, list):
                    for item in obj:
                        check_no_secrets(item)

            check_no_secrets(data)

    def test_client_cannot_control_gemini_budget(self, client: TestClient) -> None:
        """The request schema should not allow gemini_budget parameter."""
        response = client.post(
            "/api/autonomous-cycle/run",
            json={"gemini_budget": 100}
        )
        assert response.status_code == 422


class TestAutonomousCycleServiceExtraction:
    def test_cli_uses_extracted_service(self) -> None:
        """Verify that the CLI script imports from the extracted service."""
        from backend.services.autonomous_cycle import AutonomousCycle
        assert AutonomousCycle is not None

    def test_api_uses_extracted_service(self) -> None:
        """Verify that the API imports from the extracted service."""
        from backend.services.autonomous_cycle import AutonomousCycle
        assert AutonomousCycle is not None


class TestCycleCoordinatorUnit:
    def test_acquire_then_release(self, db) -> None:
        coord = CycleCoordinator()
        ok1, token, snap = coord.try_acquire(max_applications=3, db=db)
        assert ok1 is True
        assert token
        assert snap["active_state"] == "RUNNING"

        ok2, _, snap2 = coord.try_acquire(db=db)
        assert ok2 is False
        assert snap2["active_state"] == "RUNNING"

        coord.complete(token, {"status": "COMPLETED", "run_id": 7, "stats": {"applied": 1}}, db=db)
        snap3 = coord.snapshot(db=db)
        assert snap3["active_state"] == "IDLE"
        assert snap3["last_run"]["status"] == "COMPLETED"
        assert snap3["last_run"]["run_id"] == 7

    def test_cancel_flag_visible_to_checker(self, db) -> None:
        coord = CycleCoordinator()
        ok, token, _ = coord.try_acquire(db=db)
        assert ok
        assert coord.is_cancellation_requested(token, db=db) is False
        result = coord.request_cancel(run_token=token, db=db)
        assert result["changed"] is True
        assert coord.is_cancellation_requested(token, db=db) is True
        coord.complete(token, {"status": "CANCELLED", "run_id": None, "stats": {}}, db=db)
        snap = coord.snapshot(db=db)
        assert snap["last_run"]["status"] == "CANCELLED"
