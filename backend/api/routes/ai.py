from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.ai import AIStatusResponse
from backend.services.ai_service import AIService

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AIStatusResponse)
def get_ai_status(db: Session = Depends(get_db)) -> AIStatusResponse:
    return AIService(db).get_status()
