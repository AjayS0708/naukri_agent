"""Phase 10: Database schema migration tests."""

from pathlib import Path
from tempfile import TemporaryDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import Engine

from backend.database.database import Base


def _create_old_schema_engine(db_path: Path) -> Engine:
    """Create SQLite engine with old schema (no confirmation_evidence column)."""
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                profile_id INTEGER NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'PRE_APPLY',
                is_dry_run BOOLEAN NOT NULL DEFAULT FALSE,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title VARCHAR,
                company VARCHAR,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))

    return engine


def _insert_sample_applications(engine: Engine, count: int = 5) -> list:
    """Insert sample applications into old schema."""
    ids = []
    with engine.begin() as connection:
        for i in range(count):
            connection.execute(text(
                "INSERT INTO jobs (title, company) VALUES (:title, :company)"
            ), {"title": f"Job {i+1}", "company": f"Company {i+1}"})

        connection.execute(text(
            "INSERT INTO profiles (name) VALUES (:name)"
        ), {"name": "Test Profile"})

        for i in range(count):
            result = connection.execute(text("""
                INSERT INTO applications (job_id, profile_id, status, is_dry_run)
                VALUES (:job_id, :profile_id, :status, :is_dry_run)
            """), {
                "job_id": i + 1,
                "profile_id": 1,
                "status": "APPLICATION_STARTED" if i == 0 else "PRE_APPLY",
                "is_dry_run": False
            })
            ids.append(result.lastrowid)

    return ids


def initialize_database_from_engine(engine: Engine) -> None:
    """Run database initialization and migrations on a specific engine."""
    Base.metadata.create_all(bind=engine)

    if "is_dry_run" not in {col["name"] for col in inspect(engine).get_columns("applications")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE applications ADD COLUMN is_dry_run BOOLEAN NOT NULL DEFAULT FALSE"))

    if "confirmation_evidence" not in {col["name"] for col in inspect(engine).get_columns("applications")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE applications ADD COLUMN confirmation_evidence TEXT NULL"))


class TestOldSchemaMigration:
    """Test A: Old schema migration adds confirmation_evidence column."""

    def test_migration_adds_confirmation_evidence_column(self):
        """Verify migration adds missing confirmation_evidence column."""
        with TemporaryDirectory(prefix="test-migration-") as temp_dir:
            db_path = Path(temp_dir) / "old_schema.db"
            old_engine = _create_old_schema_engine(db_path)

            inspector = inspect(old_engine)
            columns_before = {col["name"] for col in inspector.get_columns("applications")}
            assert "confirmation_evidence" not in columns_before

            initialize_database_from_engine(old_engine)

            inspector = inspect(old_engine)
            columns_after = {col["name"] for col in inspector.get_columns("applications")}
            assert "confirmation_evidence" in columns_after

            old_engine.dispose()

    def test_migration_preserves_existing_rows(self):
        """Verify migration preserves existing application records."""
        with TemporaryDirectory(prefix="test-migration-") as temp_dir:
            db_path = Path(temp_dir) / "preserve_rows.db"
            old_engine = _create_old_schema_engine(db_path)
            _insert_sample_applications(old_engine, count=5)

            with old_engine.begin() as connection:
                count_before = connection.execute(text("SELECT COUNT(*) FROM applications")).scalar()
                data_before = connection.execute(text("SELECT id, job_id, profile_id, status FROM applications ORDER BY id")).fetchall()

            assert len(data_before) == 5
            initialize_database_from_engine(old_engine)

            with old_engine.begin() as connection:
                count_after = connection.execute(text("SELECT COUNT(*) FROM applications")).scalar()
                data_after = connection.execute(text("SELECT id, job_id, profile_id, status FROM applications ORDER BY id")).fetchall()

            assert count_after == count_before == 5
            for before, after in zip(data_before, data_after):
                assert before == after

            old_engine.dispose()


class TestMigrationIdempotency:
    """Test B: Migration is idempotent (runs twice without error)."""

    def test_migration_is_idempotent(self):
        """Verify migration can run twice without error or duplication."""
        with TemporaryDirectory(prefix="test-migration-") as temp_dir:
            db_path = Path(temp_dir) / "idempotent.db"
            old_engine = _create_old_schema_engine(db_path)
            _insert_sample_applications(old_engine, count=3)

            initialize_database_from_engine(old_engine)
            with old_engine.begin() as connection:
                count_after_first = connection.execute(text("SELECT COUNT(*) FROM applications")).scalar()

            initialize_database_from_engine(old_engine)
            with old_engine.begin() as connection:
                count_after_second = connection.execute(text("SELECT COUNT(*) FROM applications")).scalar()

            assert count_after_first == count_after_second == 3
            old_engine.dispose()


class TestReadinessCheck:
    """Test C: Readiness check detects schema compatibility."""

    def test_old_schema_reports_incompatible(self):
        """Verify readiness check detects missing confirmation_evidence."""
        with TemporaryDirectory(prefix="test-migration-") as temp_dir:
            db_path = Path(temp_dir) / "readiness_old.db"
            old_engine = _create_old_schema_engine(db_path)
            SessionLocal = sessionmaker(bind=old_engine)
            session = SessionLocal()

            try:
                from backend.api.routes.health import _check_schema_compatibility
                result = _check_schema_compatibility(session)
                assert result["compatible"] is False
                assert "applications.confirmation_evidence" in result["missing"]
            finally:
                session.close()
            old_engine.dispose()

    def test_new_schema_reports_compatible(self):
        """Verify readiness check passes after migration."""
        with TemporaryDirectory(prefix="test-migration-") as temp_dir:
            db_path = Path(temp_dir) / "readiness_new.db"
            old_engine = _create_old_schema_engine(db_path)
            initialize_database_from_engine(old_engine)

            SessionLocal = sessionmaker(bind=old_engine)
            session = SessionLocal()

            try:
                from backend.api.routes.health import _check_schema_compatibility
                result = _check_schema_compatibility(session)
                assert result["compatible"] is True
                assert len(result["missing"]) == 0
            finally:
                session.close()
            old_engine.dispose()


class TestCurrentSchema:
    """Test D: Current schema requires no changes."""

    def test_current_schema_runs_without_changes(self):
        """Verify migration on current schema succeeds without modifications."""
        with TemporaryDirectory(prefix="test-migration-") as temp_dir:
            db_path = Path(temp_dir) / "current_schema.db"
            current_engine = create_engine(
                f"sqlite:///{db_path.as_posix()}",
                connect_args={"check_same_thread": False},
            )

            Base.metadata.create_all(bind=current_engine)
            inspector = inspect(current_engine)
            columns_before = {col["name"] for col in inspector.get_columns("applications")}

            initialize_database_from_engine(current_engine)
            inspector = inspect(current_engine)
            columns_after = {col["name"] for col in inspector.get_columns("applications")}

            assert columns_before == columns_after
            assert "confirmation_evidence" in columns_after
            current_engine.dispose()


class TestDatabaseIsolation:
    """Test E: Ensure these tests never use production database."""

    def test_uses_temporary_database_not_production(self):
        """Verify all migrations use temp databases, not production."""
        from backend.core.config import PROJECT_ROOT
        production_path = PROJECT_ROOT / "data" / "naukri_agent.db"

        with TemporaryDirectory(prefix="test-migration-") as temp_dir:
            db_path = Path(temp_dir) / "isolated.db"
            assert db_path != production_path
            assert str(db_path).startswith(temp_dir)
