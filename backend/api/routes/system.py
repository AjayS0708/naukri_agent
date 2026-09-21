from fastapi import APIRouter, Depends

from backend.services.windows import WindowsAutoStartService
from backend.schemas.autostart import (
    AutoStartStatusResponse,
    AutoStartEnableRequest,
    AutoStartActionResponse
)
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Global auto-start service instance
_autostart_service: WindowsAutoStartService = None


def set_autostart_service_instance(service: WindowsAutoStartService):
    """Set the global auto-start service instance."""
    global _autostart_service
    _autostart_service = service


def get_autostart_service() -> WindowsAutoStartService:
    """Get the auto-start service instance."""
    if _autostart_service is None:
        raise RuntimeError("Auto-start service not initialized")
    return _autostart_service


@router.get("/system/autostart", response_model=AutoStartStatusResponse)
async def get_autostart_status(
    autostart_service: WindowsAutoStartService = Depends(get_autostart_service)
):
    """Get auto-start status."""
    try:
        status = autostart_service.get_status()
        return AutoStartStatusResponse(**status)
    except Exception as e:
        logger.error(f"Failed to get auto-start status: {e}", exc_info=True)
        raise


@router.post("/system/autostart/enable", response_model=AutoStartActionResponse)
async def enable_autostart(
    request: AutoStartEnableRequest,
    autostart_service: WindowsAutoStartService = Depends(get_autostart_service)
):
    """Enable Windows auto-start."""
    try:
        result = autostart_service.enable(request.script_path)
        return AutoStartActionResponse(**result)
    except Exception as e:
        logger.error(f"Failed to enable auto-start: {e}", exc_info=True)
        raise


@router.post("/system/autostart/disable", response_model=AutoStartActionResponse)
async def disable_autostart(
    autostart_service: WindowsAutoStartService = Depends(get_autostart_service)
):
    """Disable Windows auto-start."""
    try:
        result = autostart_service.disable()
        return AutoStartActionResponse(**result)
    except Exception as e:
        logger.error(f"Failed to disable auto-start: {e}", exc_info=True)
        raise
