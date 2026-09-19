from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DiscoveryRunStats(BaseModel):
    searches_attempted: int
    jobs_discovered: int
    new_jobs: int
    duplicate_jobs: int
    errors: int
    pages_processed: int


class DiscoveryRunResponse(BaseModel):
    id: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    stats: DiscoveryRunStats
    error_message: Optional[str]

    model_config = {"from_attributes": True}


class DiscoveryStatusResponse(BaseModel):
    is_running: bool
    agent_state: str
    current_search: Optional[str] = None
    active_run: Optional[DiscoveryRunResponse] = None
