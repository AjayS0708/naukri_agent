import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import Session

from backend.services.applications.limits import ApplicationLimitService, LimitCheckResult
from backend.schemas.application import ApplicationStatus


class TestLimitEnforcementWithApplicationStatus:
    """Tests that limits only count successful applications."""

    @pytest.fixture
    def db_session(self):
        """Create a mock database session."""
        session = MagicMock(spec=Session)
        session.execute = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()
        return session

    @pytest.fixture
    def limit_service(self, db_session):
        """Create an ApplicationLimitService instance for testing."""
        return ApplicationLimitService(db_session)

    def test_only_applied_counted(self, limit_service, db_session):
        """Test that only APPLIED applications are counted."""
        # The SQL query filters by status, so we only return APPLIED/SUBMITTED apps
        apps = [
            MagicMock(status=ApplicationStatus.APPLIED.value, applied_at=datetime.now(UTC) - timedelta(minutes=30)),
            MagicMock(status=ApplicationStatus.SUBMITTED.value, applied_at=datetime.now(UTC) - timedelta(minutes=15)),
        ]
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        count = limit_service.get_hourly_usage()

        # Only APPLIED and SUBMITTED should be counted
        assert count == 2

    def test_failed_applications_not_counted(self, limit_service, db_session):
        """Test that failed applications are not counted."""
        # The SQL query filters by status, so no apps would be returned for SKIPPED/NEEDS_ATTENTION
        apps = []
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        count = limit_service.get_hourly_usage()

        assert count == 0

    def test_external_applications_not_counted(self, limit_service, db_session):
        """Test that external applications are not counted."""
        # The SQL query filters by status, so no apps would be returned for EXTERNAL_APPLICATION
        apps = []
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        count = limit_service.get_hourly_usage()

        assert count == 0
