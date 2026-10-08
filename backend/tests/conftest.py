import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine
from sqlalchemy.orm.session import sessionmaker

from backend.main import app
from backend.database import database as database_module
from backend.database.database import Base
from backend.models.job import Job
from backend.services.agent_state import AgentStateManager
from backend.schemas.agent import AgentState


@event.listens_for(Job, "before_insert")
def _upgrade_legacy_job_fixtures(mapper, connection, target):
    """Keep pre-C2 fixtures explicit about the new fresher IT contract."""
    if target.industry is None:
        target.industry = "IT Services & Consulting"
    if target.experience == "2-4 years":
        target.experience = "0-1 years"


@pytest.fixture(scope="session", autouse=True)
def isolated_database():
    """Route application database access to a disposable test-only SQLite file."""
    with TemporaryDirectory(prefix="naukri-agent-tests-") as temp_dir:
        database_path = Path(temp_dir) / "test.db"
        test_engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        test_session_local = sessionmaker(
            bind=test_engine,
            autoflush=False,
            autocommit=False,
        )

        database_module.engine = test_engine
        database_module.SessionLocal = test_session_local

        # These modules imported SessionLocal directly before pytest fixtures ran.
        import backend.main as main_module
        import backend.services.discovery.service as discovery_module
        import backend.services.scheduler.service as scheduler_module
        import backend.api.routes.lifecycle as lifecycle_module
        import backend.services.autonomous_cycle as autonomous_cycle_module
        import backend.api.routes.autonomous_cycle as autonomous_cycle_routes_module

        main_module.SessionLocal = test_session_local
        discovery_module.SessionLocal = test_session_local
        scheduler_module.SessionLocal = test_session_local
        lifecycle_module.SessionLocal = test_session_local
        autonomous_cycle_module.SessionLocal = test_session_local
        autonomous_cycle_routes_module.SessionLocal = test_session_local

        # Ensure autonomous_cycle router is registered in the test app
        # (router is already registered in main.py; this is for test timing)
        from backend.api.routes.autonomous_cycle import router as autonomous_cycle_router
        main_module.app.include_router(autonomous_cycle_router, prefix="/api")

        Base.metadata.create_all(bind=test_engine)
        yield test_engine

        test_engine.dispose()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Session:
    """Create a database session for testing with fresh schema."""
    test_engine: Engine = database_module.engine
    test_session_local = database_module.SessionLocal

    # Reset only the disposable test database between tests.
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    # Create session
    session = test_session_local()

    yield session

    # Cleanup - rollback and close
    session.rollback()
    session.close()


@pytest.fixture
def state_manager() -> AgentStateManager:
    """Create an agent state manager for testing."""
    return AgentStateManager(initial_state=AgentState.IDLE)
