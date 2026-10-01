from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.database import get_session
from backend.schemas.notification import NotificationHistoryResponse
from backend.services.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationHistoryResponse)
def get_notifications(
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_session),
) -> NotificationHistoryResponse:
    return NotificationService(db).history(limit)
