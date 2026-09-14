from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.core.config import get_settings
from backend.schemas.health import HealthResponse
from backend.services.agent_state import AgentStateManager

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.service_slug, version=settings.app_version, agent_state=AgentStateManager().current_state)
