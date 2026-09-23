from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.core.config import get_settings
from backend.core.storage import get_storage_service
from backend.schemas.health import HealthResponse, ReadinessResponse
from backend.services.agent_state import AgentStateManager

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Liveness check - simple API process status."""
    db.execute(text("SELECT 1"))
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.service_slug, version=settings.app_version, agent_state=AgentStateManager().current_state)


@router.get("/readiness", response_model=ReadinessResponse)
def readiness_check(db: Session = Depends(get_db)) -> ReadinessResponse:
    """Readiness check - detailed component status for production deployment."""
    settings = get_settings()
    components = {}
    overall_status = "ready"

    # Check database
    try:
        db.execute(text("SELECT 1"))
        components["database"] = "healthy"
    except Exception as e:
        components["database"] = f"unhealthy: {str(e)}"
        overall_status = "not_ready"

    # Check configuration
    try:
        # Validate required configuration
        if settings.is_production and not settings.gemini_api_key:
            components["configuration"] = "missing_required_api_key"
            overall_status = "not_ready"
        else:
            components["configuration"] = "valid"
    except Exception as e:
        components["configuration"] = f"invalid: {str(e)}"
        overall_status = "not_ready"

    # Check storage
    try:
        storage = get_storage_service()
        storage.get_data_storage_path()
        components["storage"] = "available"
    except Exception as e:
        components["storage"] = f"unavailable: {str(e)}"
        overall_status = "not_ready"

    # Check AI provider (optional - can run without AI)
    if settings.gemini_api_key:
        components["ai_provider"] = "configured"
    else:
        components["ai_provider"] = "not_configured"

    # Check runtime environment
    components["runtime_environment"] = settings.runtime_environment

    return ReadinessResponse(
        status=overall_status,
        service=settings.service_slug,
        version=settings.app_version,
        components=components
    )
