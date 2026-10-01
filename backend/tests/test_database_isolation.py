from pathlib import Path
import sqlite3

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from backend.core.config import PROJECT_ROOT, get_settings


def _production_database_path() -> Path:
    database_url = get_settings().database_url
    assert database_url.startswith("sqlite:///./")
    return (PROJECT_ROOT / database_url.removeprefix("sqlite:///./")).resolve()


def _production_row_counts() -> dict[str, int]:
    path = _production_database_path()
    connection = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        counts: dict[str, int] = {}
        for table in ("profiles", "resumes", "jobs", "job_analyses", "job_preferences", "applications"):
            if table in tables:
                counts[table] = connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
        return counts
    finally:
        connection.close()


def test_test_engine_is_not_production_database(isolated_database: Engine) -> None:
    production_path = _production_database_path()
    test_path = Path(isolated_database.url.database).resolve()

    assert test_path != production_path
    assert test_path.exists()
    assert inspect(isolated_database).has_table("profiles")


def test_api_database_dependency_uses_test_engine(isolated_database: Engine) -> None:
    from backend.api.dependencies import get_db

    session = next(get_db())
    try:
        assert session.get_bind() is isolated_database
    finally:
        session.close()


def test_test_database_reset_does_not_modify_production_database(isolated_database: Engine) -> None:
    before = _production_row_counts()

    from backend.database.database import Base

    Base.metadata.drop_all(bind=isolated_database)
    assert not inspect(isolated_database).has_table("profiles")
    Base.metadata.create_all(bind=isolated_database)

    assert _production_row_counts() == before
    assert inspect(isolated_database).has_table("profiles")
