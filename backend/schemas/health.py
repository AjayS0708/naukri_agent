from pydantic import BaseModel

from backend.schemas.agent import AgentState


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    agent_state: AgentState
