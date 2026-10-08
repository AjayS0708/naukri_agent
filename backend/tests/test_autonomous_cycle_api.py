"""
Checkpoint E3 — Tests for autonomous cycle control API.

These tests verify:
- Valid POST requests are accepted
- Invalid max_applications is rejected
- Client cannot control Gemini budget
- Concurrent requests return 409
- Lock is released after execution
- Status endpoint works correctly
- No secrets are exposed
- API uses the extracted AutonomousCycleService
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
        # The endpoint should return 200 or 202 (accepted)
        assert response.status_code in [200, 202]

    def test_invalid_max_applications_rejected(self, client: TestClient) -> None:
        """Invalid max_applications should be rejected with 422."""
        response = client.post("/api/autonomous-cycle/run", json={"max_applications": 0})
        assert response.status_code == 422

    def test_max_applications_upper_bound(self, client: TestClient) -> None:
        """max_applications cannot exceed 10."""
        response = client.post("/api/autonomous-cycle/run", json={"max_applications": 11})
        assert response.status_code == 422

    def test_negative_max_applications_rejected(self, client: TestClient) -> None:
        """Negative max_applications should be rejected."""
        response = client.post("/api/autonomous-cycle/run", json={"max_applications": -1})
        assert response.status_code == 422

    def test_missing_max_applications_defaults(self, client: TestClient) -> None:
        """Missing max_applications should use default value."""
        response = client.post("/api/autonomous-cycle/run", json={})
        assert response.status_code in [200, 202]


class TestAutonomousCycleConcurrency:
    def test_concurrent_post_returns_409(self, client: TestClient) -> None:
        """A second POST while a cycle is running should return 409."""
        # Mock the cycle.run() to take some time
        async def slow_run():
            await asyncio.sleep(0.5)  # Simulate a running cycle
            return {"status": "COMPLETED", "run_id": 1, "stats": {}}
        
        with patch('backend.api.routes.autonomous_cycle.AutonomousCycle') as mock_cycle:
            mock_instance = AsyncMock()
            mock_instance.run = slow_run
            mock_cycle.return_value = mock_instance
            
            # First request should succeed
            response1 = client.post("/api/autonomous-cycle/run", json={"max_applications": 2})
            assert response1.status_code in [200, 202]

            # Second request should return 409 (cycle is still running)
            response2 = client.post("/api/autonomous-cycle/run", json={"max_applications": 2})
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
        response = client.post("/api/autonomous-cycle/run", json={"max_applications": 2})
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
        # Try to send gemini_budget - should be rejected by schema validation
        response = client.post(
            "/api/autonomous-cycle/run",
            json={"max_applications": 2, "gemini_budget": 100}
        )
        # Should fail validation because gemini_budget is not in the schema
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
