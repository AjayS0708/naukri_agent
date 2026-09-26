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
def health_check() -> HealthResponse:
    """Liveness check; deliberately independent of database and Gemini."""
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
    except Exception:
        components["database"] = "unhealthy"
        overall_status = "not_ready"

    # Check configuration
    try:
        errors = settings.production_configuration_errors
        if errors:
            components["configuration"] = ",".join(errors)
            overall_status = "not_ready"
        else:
            components["configuration"] = "valid"
    except Exception:
        components["configuration"] = "invalid"
        overall_status = "not_ready"

    # Check storage
    try:
        storage = get_storage_service()
        storage.get_data_storage_path()
        components["storage"] = "available"
    except Exception:
        components["storage"] = "unavailable"
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
