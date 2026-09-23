from pydantic import BaseModel

from backend.schemas.agent import AgentState


class HealthResponse(BaseModel):
    """Liveness check - simple status check."""
    status: str
    service: str
    version: str
    agent_state: AgentState


class ReadinessResponse(BaseModel):
    """Readiness check - detailed component status."""
    status: str
    service: str
    version: str
    components: dict[str, str]
