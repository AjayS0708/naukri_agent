from typing import Optional
from pydantic import BaseModel


class AutoStartStatusResponse(BaseModel):
    """Response for auto-start status endpoint."""
    enabled: bool
    platform: str
    task_name: str
    supported: bool


class AutoStartEnableRequest(BaseModel):
    """Request for enabling auto-start."""
    script_path: Optional[str] = None


class AutoStartActionResponse(BaseModel):
    """Response for auto-start action endpoints (enable, disable)."""
    success: bool
    message: Optional[str] = None
    reason: Optional[str] = None
    script_path: Optional[str] = None
