from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.worker import (
    WorkerRegisterRequest,
    WorkerStatusResponse,
    WorkerListResponse,
)
from backend.services.worker import WorkerService

router = APIRouter(prefix="/worker", tags=["worker"])


@router.get("/status", response_model=WorkerListResponse)
def get_worker_status(db: Session = Depends(get_db)) -> WorkerListResponse:
    """List all registered workers."""
    return WorkerService(db).list_workers()


@router.post("/register", response_model=WorkerStatusResponse)
def register_worker(
    request: WorkerRegisterRequest,
    db: Session = Depends(get_db),
) -> WorkerStatusResponse:
    """Register a new worker or return existing registration."""
    return WorkerService(db).register_worker(request)


@router.get("/{worker_id}", response_model=WorkerStatusResponse)
def get_worker_by_id(
    worker_id: str,
    db: Session = Depends(get_db),
) -> WorkerStatusResponse:
    """Get worker status by ID."""
    response = WorkerService(db).get_worker(worker_id)
    if not response:
        raise HTTPException(status_code=404, detail="Worker not found")
    return response
