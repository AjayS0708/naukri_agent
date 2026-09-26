from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.worker import Worker
from backend.schemas.worker import (
    WorkerRegisterRequest,
    WorkerStatusResponse,
    WorkerStatus,
    WorkerListResponse,
)


class WorkerService:
    """
    Manages persistent worker identity and lifecycle.
    
    Provides registration, status tracking, and retrieval without
    modifying the existing scheduler or Naukri execution architecture.
    """
    
    def __init__(self, session: Session) -> None:
        self.session = session
    
    def register_worker(self, request: WorkerRegisterRequest) -> WorkerStatusResponse:
        """
        Register a new worker or return existing registration.
        
        Registration is safely repeatable: if a worker with the same
        type and environment already exists, return its status.
        """
        # Check for existing worker with same type and environment
        existing = self.session.scalar(
            select(Worker).where(
                (Worker.worker_type == request.worker_type)
                & (Worker.runtime_environment == request.runtime_environment)
            )
        )
        
        if existing:
            return self._worker_to_response(existing)
        
        # Create new worker
        worker_id = str(uuid4())
        worker = Worker(
            worker_id=worker_id,
            worker_type=request.worker_type,
            status=WorkerStatus.IDLE,
            runtime_environment=request.runtime_environment,
            started_at=None,
            stopped_at=None,
        )
        
        self.session.add(worker)
        self.session.commit()
        self.session.refresh(worker)
        
        return self._worker_to_response(worker)
    
    def get_worker(self, worker_id: str) -> WorkerStatusResponse | None:
        """Retrieve a worker by ID."""
        worker = self.session.scalar(
            select(Worker).where(Worker.worker_id == worker_id)
        )
        
        if not worker:
            return None
        
        return self._worker_to_response(worker)
    
    def list_workers(self) -> WorkerListResponse:
        """List all registered workers."""
        workers = self.session.scalars(select(Worker)).all()
        
        active_count = len([
            w for w in workers
            if w.status not in (WorkerStatus.STOPPED, WorkerStatus.ERROR)
        ])
        
        responses = [self._worker_to_response(w) for w in workers]
        
        return WorkerListResponse(
            workers=responses,
            total_count=len(workers),
            active_count=active_count,
        )
    
    def update_worker_status(
        self, worker_id: str, status: WorkerStatus
    ) -> WorkerStatusResponse:
        """Update worker status."""
        worker = self.session.scalar(
            select(Worker).where(Worker.worker_id == worker_id)
        )
        
        if not worker:
            raise ValueError(f"Worker {worker_id} not found")
        
        worker.status = status
        
        # Track lifecycle transitions
        if status == WorkerStatus.RUNNING and not worker.started_at:
            worker.started_at = datetime.now(UTC)
        elif status in (WorkerStatus.STOPPED, WorkerStatus.ERROR) and not worker.stopped_at:
            worker.stopped_at = datetime.now(UTC)
        
        self.session.commit()
        self.session.refresh(worker)
        
        return self._worker_to_response(worker)
    
    def _worker_to_response(self, worker: Worker) -> WorkerStatusResponse:
        """Convert Worker model to response schema."""
        return WorkerStatusResponse(
            worker_id=worker.worker_id,
            worker_type=worker.worker_type,
            status=worker.status,
            runtime_environment=worker.runtime_environment,
            started_at=worker.started_at,
            stopped_at=worker.stopped_at,
            created_at=worker.created_at,
            updated_at=worker.updated_at,
        )
