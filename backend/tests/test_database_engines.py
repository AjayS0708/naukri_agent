import pytest
from unittest.mock import patch
from sqlalchemy.engine import Engine
from backend.core.config import Settings
import backend.database.database as db_module

def test_sqlite_engine_creation():
    """Verify SQLite connection is created according to config."""
    with patch("backend.database.database.get_settings") as mock_settings:
        mock_settings.return_value = Settings(database_url="sqlite:///:memory:")
        engine = db_module.create_database_engine()
        assert isinstance(engine, Engine)
        assert engine.url.drivername == "sqlite"


def test_postgresql_engine_creation():
    """Verify PostgreSQL uses psycopg and proper configurations."""
    with patch("backend.database.database.get_settings") as mock_settings:
        mock_settings.return_value = Settings(database_url="postgresql://user:pass@localhost:5432/naukridb")
        engine = db_module.create_database_engine()
        assert isinstance(engine, Engine)
        # Should be rewritten to use psycopg adapter
        assert engine.url.drivername == "postgresql+psycopg"
        # Dialect info check
        assert engine.pool.size() == 20
        assert engine.name == "postgresql"

