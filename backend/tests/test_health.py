from fastapi.testclient import TestClient


def test_health_check_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "naukri-ai-agent", "version": "0.1.0", "agent_state": "IDLE"}
