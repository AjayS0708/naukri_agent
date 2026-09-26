import pytest
import os
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.main import app
from backend.database.database import SessionLocal, initialize_database, engine, Base
from backend.services.agent_state import AgentStateManager
from backend.schemas.agent import AgentState


@pytest.fixture
def client() -> TestClient:
    # Create the data directory if it doesn't exist to avoid database errors
    backend_dir = Path(__file__).parent.parent
    data_dir = backend_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Session:
    """Create a database session for testing with fresh schema."""
    # Clean and reinitialize database
    # Drop all tables and recreate them to ensure new columns are present
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

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
