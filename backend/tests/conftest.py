import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from backend.main import app


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
