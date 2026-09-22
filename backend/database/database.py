from collections.abc import Generator
from pathlib import Path
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.config import PROJECT_ROOT, get_settings


class Base(DeclarativeBase):
    pass


def create_database_engine() -> Engine:
    """
    Create database engine based on DATABASE_URL.
    
    Supports:
    - SQLite: sqlite:///./data/naukri_agent.db
    - PostgreSQL: postgresql://user:pass@host:port/dbname
    
    The database URL is fully configurable via NAUKRI_AGENT_DATABASE_URL environment variable.
    """
    database_url = get_settings().database_url
    
    # Handle SQLite directory creation
    if database_url.startswith("sqlite"):
        # Extract path from SQLite URL
        # Format: sqlite:///./data/naukri_agent.db or sqlite:///absolute/path/db.db
        if database_url.startswith("sqlite:///./"):
            # Relative path
            db_path = database_url.removeprefix("sqlite:///./")
            full_path = PROJECT_ROOT / db_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
        elif database_url.startswith("sqlite:///"):
            # Absolute path
            db_path = database_url.removeprefix("sqlite:///")
            full_path = Path(db_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
        
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False}
        )
    
    # PostgreSQL and other databases don't need special handling
    return create_engine(database_url)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """Alias for get_session for consistency with existing API routes."""
    return get_session()
