from collections.abc import Generator
from pathlib import Path
import os

from sqlalchemy import create_engine, inspect, text
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
    # Convert postgresql:// to postgresql+psycopg:// to use the new driver
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    engine_kwargs = {}
    if database_url.startswith("postgresql"):
        # Connection pooling settings for production PostgreSQL
        engine_kwargs = {
            "pool_size": 20,
            "max_overflow": 10,
            "pool_pre_ping": True,
            "pool_recycle": 3600
        }

    return create_engine(database_url, **engine_kwargs)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def initialize_database() -> None:
    """
    Initialize database schema and apply additive migrations.

    Phase 10: Ensures all required columns exist on applications table,
    including confirmation_evidence for applied state detection.
    """
    Base.metadata.create_all(bind=engine)

    # Migration 1: is_dry_run column (Phase 9B-4)
    if "is_dry_run" not in {
        column["name"] for column in inspect(engine).get_columns("applications")
    }:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE applications "
                    "ADD COLUMN is_dry_run BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )

    # Migration 2: confirmation_evidence column (Phase 10)
    # Stores explicit applied state evidence for post-click detection
    if "confirmation_evidence" not in {
        column["name"] for column in inspect(engine).get_columns("applications")
    }:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE applications "
                    "ADD COLUMN confirmation_evidence TEXT NULL"
                )
            )

    job_columns = {column["name"] for column in inspect(engine).get_columns("jobs")}
    preference_columns = {column["name"] for column in inspect(engine).get_columns("job_preferences")}
    with engine.begin() as connection:
        if "industry" not in job_columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN industry VARCHAR(255)"))
        if "department" not in job_columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN department VARCHAR(255)"))
        if "role_category" not in job_columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN role_category VARCHAR(255)"))
        if "max_required_experience_years" not in preference_columns:
            connection.execute(text("ALTER TABLE job_preferences ADD COLUMN max_required_experience_years INTEGER NOT NULL DEFAULT 0"))
        if "it_industry_allowlist" not in preference_columns:
            connection.execute(text("ALTER TABLE job_preferences ADD COLUMN it_industry_allowlist JSON"))
        if "it_keyword_list" not in preference_columns:
            connection.execute(text("ALTER TABLE job_preferences ADD COLUMN it_keyword_list JSON"))


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """Alias for get_session for consistency with existing API routes."""
    return get_session()


# Standalone migration command support
if __name__ == "__main__":
    """
    Standalone database migration runner.

    Usage: python -m backend.database.database

    Runs schema initialization and migrations on the configured database.
    Uses current DATABASE_URL from environment/config.
    """
    print("Phase 10 Database Schema Migration")
    print("===================================\n")

    try:
        print(f"Database: {engine.url}")
        print("Running migrations...\n")

        initialize_database()

        from sqlalchemy import inspect
        inspector = inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("applications")}

        print("Migration Results:")
        print(f"  - confirmation_evidence: {'OK' if 'confirmation_evidence' in columns else 'MISSING'}")
        print(f"  - is_dry_run: {'OK' if 'is_dry_run' in columns else 'MISSING'}")

        if "confirmation_evidence" in columns and "is_dry_run" in columns:
            print("\nStatus: SUCCESS")
            exit(0)
        else:
            print("\nStatus: FAILED")
            exit(1)
    except Exception as e:
        print(f"\nStatus: ERROR")
        print(f"Message: {str(e)}")
        exit(1)
