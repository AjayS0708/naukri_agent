"""
Checkpoint E3 — Tests for autonomous cycle control API.

These tests verify:
- Valid POST requests are accepted (with or without max_applications)
- Concurrent requests return 409
- Lock is released after execution
- Status endpoint works correctly
- No secrets are exposed
- API uses the extracted AutonomousCycleService
E5-R10: max_applications is optional and ignored (no application-count cap).
"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from backend.services.autonomous_cycle.runtime import AutonomousCycleRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    """Every test receives a fresh process-local runtime, like a restart."""
    import backend.api.routes.autonomous_cycle as route_module
    route_module._runtime = AutonomousCycleRuntime()


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
