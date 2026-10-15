"""E5-R29: manual apply queue — apply to already-discovered jobs on demand."""
from backend.services.manual_apply.service import (
    ManualApplyService,
    get_last_manual_run,
)

__all__ = ["ManualApplyService", "get_last_manual_run"]
