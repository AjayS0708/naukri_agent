from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.config import PROJECT_ROOT, get_settings


class Base(DeclarativeBase):
    pass


def create_database_engine() -> Engine:
    database_url = get_settings().database_url
    prefix = "sqlite:///./"
    if database_url.startswith(prefix):
        (PROJECT_ROOT / database_url.removeprefix(prefix)).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url, connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {})


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
