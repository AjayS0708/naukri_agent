from fastapi.testclient import TestClient


def test_health_check_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "naukri-ai-agent"
    assert data["version"] == "0.1.0"
    assert "agent_state" in data


def test_readiness_check_returns_component_status(client: TestClient) -> None:
    """Test readiness endpoint returns detailed component status."""
    response = client.get("/api/readiness")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "service" in data
    assert "version" in data
    assert "components" in data
    assert "database" in data["components"]
    assert "configuration" in data["components"]
    assert "storage" in data["components"]
    assert "ai_provider" in data["components"]
    assert "runtime_environment" in data["components"]
