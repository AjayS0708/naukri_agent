from fastapi import APIRouter, Depends
from sqlalchemy import text, inspect
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


def _check_schema_compatibility(db: Session) -> dict:
    """
    Phase 10: Check if database schema is compatible with current models.

    Returns: {"compatible": bool, "missing": List[str]}
    """
    try:
        engine = db.get_bind()
        inspector = inspect(engine)

        # Required columns for applications table (Phase 10)
        required_columns = [
            ("applications", "confirmation_evidence"),
            ("applications", "is_dry_run"),
        ]

        missing = []
        for table_name, column_name in required_columns:
            try:
                columns = inspector.get_columns(table_name)
                column_names = {col["name"] for col in columns}
                if column_name not in column_names:
                    missing.append(f"{table_name}.{column_name}")
            except Exception:
                # Table doesn't exist yet - will be created by create_all()
                pass

        return {
            "compatible": len(missing) == 0,
            "missing": missing
        }
    except Exception as e:
        return {
            "compatible": False,
            "missing": [f"schema_check_error: {str(e)}"]
        }


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

    # Phase 10: Check schema compatibility
    try:
        schema_check = _check_schema_compatibility(db)
        if schema_check["compatible"]:
            components["schema"] = "compatible"
        else:
            components["schema"] = f"incompatible: {', '.join(schema_check['missing'])}"
            overall_status = "not_ready"
    except Exception as e:
        components["schema"] = f"check_failed: {str(e)}"
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
