import pytest
from uuid import uuid4
from sqlalchemy.orm import Session

from backend.models.worker import Worker
from backend.schemas.worker import (
    WorkerType,
    WorkerStatus,
    WorkerRegisterRequest,
    WorkerStatusResponse,
)
from backend.services.worker import WorkerService


class TestWorkerTypeValidation:
    def test_worker_type_local_windows_is_valid(self) -> None:
        assert WorkerType.LOCAL_WINDOWS.value == "LOCAL_WINDOWS"
    
    def test_worker_type_cloud_browser_is_valid(self) -> None:
        assert WorkerType.CLOUD_BROWSER.value == "CLOUD_BROWSER"


class TestWorkerStatusValidation:
    def test_worker_status_starting_is_valid(self) -> None:
        assert WorkerStatus.STARTING.value == "STARTING"
    
    def test_worker_status_idle_is_valid(self) -> None:
        assert WorkerStatus.IDLE.value == "IDLE"
    
    def test_worker_status_running_is_valid(self) -> None:
        assert WorkerStatus.RUNNING.value == "RUNNING"


class TestWorkerRegistration:
    def test_register_local_windows_worker(self, db: Session) -> None:
        unique_env = f"test_local_{uuid4().hex[:8]}"
        request = WorkerRegisterRequest(
            worker_type=WorkerType.LOCAL_WINDOWS,
            runtime_environment=unique_env,
        )
        
        service = WorkerService(db)
        response = service.register_worker(request)
        
        assert response.worker_id is not None
        assert response.worker_type == WorkerType.LOCAL_WINDOWS
        assert response.status == WorkerStatus.IDLE
        assert response.runtime_environment == unique_env
        assert response.created_at is not None
        assert response.updated_at is not None


class TestRepeatRegistration:
    def test_repeat_registration_returns_same_worker(self, db: Session) -> None:
        unique_env = f"test_repeat_{uuid4().hex[:8]}"
        request = WorkerRegisterRequest(
            worker_type=WorkerType.LOCAL_WINDOWS,
            runtime_environment=unique_env,
        )
        
        service = WorkerService(db)
        response1 = service.register_worker(request)
        response2 = service.register_worker(request)
        
        assert response1.worker_id == response2.worker_id


class TestWorkerRetrieval:
    def test_get_worker_by_id(self, db: Session) -> None:
        unique_env = f"test_retrieve_{uuid4().hex[:8]}"
        request = WorkerRegisterRequest(
            worker_type=WorkerType.LOCAL_WINDOWS,
            runtime_environment=unique_env,
        )
        
        service = WorkerService(db)
        registered = service.register_worker(request)
        retrieved = service.get_worker(registered.worker_id)
        
        assert retrieved is not None
        assert retrieved.worker_id == registered.worker_id
        assert retrieved.worker_type == registered.worker_type


class TestWorkerStatusUpdate:
    def test_update_worker_status_to_running(self, db: Session) -> None:
        unique_env = f"test_update_{uuid4().hex[:8]}"
        request = WorkerRegisterRequest(
            worker_type=WorkerType.LOCAL_WINDOWS,
            runtime_environment=unique_env,
        )
        
        service = WorkerService(db)
        registered = service.register_worker(request)
        updated = service.update_worker_status(registered.worker_id, WorkerStatus.RUNNING)
        
        assert updated.status == WorkerStatus.RUNNING
        assert updated.started_at is not None


class TestWorkerListing:
    def test_list_multiple_workers(self, db: Session) -> None:
        service = WorkerService(db)
        
        unique_env1 = f"test_list1_{uuid4().hex[:8]}"
        request1 = WorkerRegisterRequest(
            worker_type=WorkerType.LOCAL_WINDOWS,
            runtime_environment=unique_env1,
        )
        response1 = service.register_worker(request1)
        
        unique_env2 = f"test_list2_{uuid4().hex[:8]}"
        request2 = WorkerRegisterRequest(
            worker_type=WorkerType.CLOUD_BROWSER,
            runtime_environment=unique_env2,
        )
        response2 = service.register_worker(request2)
        
        listing = service.list_workers()
        
        assert listing.total_count >= 2
        assert len(listing.workers) >= 2
        worker_ids = [w.worker_id for w in listing.workers]
        assert response1.worker_id in worker_ids
        assert response2.worker_id in worker_ids


class TestAPIEndpoints:
    def test_register_worker_endpoint(self, client) -> None:
        unique_env = f"test_api_{uuid4().hex[:8]}"
        response = client.post(
            "/api/worker/register",
            json={
                "worker_type": "LOCAL_WINDOWS",
                "runtime_environment": unique_env,
            },
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "worker_id" in data
        assert data["worker_type"] == "LOCAL_WINDOWS"
        assert data["status"] == "IDLE"
    
    def test_get_worker_status_endpoint(self, client) -> None:
        unique_env = f"test_list_api_{uuid4().hex[:8]}"
        register_response = client.post(
            "/api/worker/register",
            json={
                "worker_type": "LOCAL_WINDOWS",
                "runtime_environment": unique_env,
            },
        )
        assert register_response.status_code == 200
        
        list_response = client.get("/api/worker/status")
        assert list_response.status_code == 200
        data = list_response.json()
        assert "workers" in data
        assert data["total_count"] >= 1
