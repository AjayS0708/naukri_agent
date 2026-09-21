import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session

from backend.main import app
from backend.database.database import SessionLocal, initialize_database
from backend.services.agent_state import AgentStateManager
from backend.schemas.agent import AgentState


@pytest.fixture
def client() -> TestClient:
    # Create the data directory if it doesn't exist to avoid database errors
    import os
    from pathlib import Path
    backend_dir = Path(__file__).parent.parent
    data_dir = backend_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Session:
    """Create a database session for testing."""
    # Initialize database
    initialize_database()
    
    # Create session
    session = SessionLocal()
    
    yield session
    
    # Cleanup - rollback and close
    session.rollback()
    session.close()


@pytest.fixture
def state_manager() -> AgentStateManager:
    """Create an agent state manager for testing."""
    return AgentStateManager(initial_state=AgentState.IDLE)
