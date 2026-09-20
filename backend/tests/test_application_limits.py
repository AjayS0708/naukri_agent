import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from backend.services.applications.limits import ApplicationLimitService, LimitCheckResult
from backend.models.application import Application
from backend.models.matching import JobPreference
from backend.schemas.application import ApplicationStatus


class TestApplicationLimitService:
    """Tests for the ApplicationLimitService class."""

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

    def test_get_limits_creates_default(self, limit_service, db_session):
        """Test that get_limits creates default preference if none exists."""
        db_session.execute.return_value.scalars.return_value.first.return_value = None

        preference = limit_service.get_limits()

        assert preference is not None
        db_session.add.assert_called_once()
        db_session.commit.assert_called()

    def test_get_limits_returns_existing(self, limit_service, db_session):
        """Test that get_limits returns existing preference."""
        existing_pref = JobPreference(
            max_hourly_applications=5,
            max_daily_applications=25
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = existing_pref

        preference = limit_service.get_limits()

        assert preference == existing_pref
        db_session.add.assert_not_called()

    def test_update_limits_hourly(self, limit_service, db_session):
        """Test updating hourly limit."""
        existing_pref = JobPreference(
            max_hourly_applications=4,
            max_daily_applications=20
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = existing_pref

        updated = limit_service.update_limits(max_hourly=10)

        assert updated.max_hourly_applications == 10
        assert updated.max_daily_applications == 20
        db_session.commit.assert_called()

    def test_update_limits_daily(self, limit_service, db_session):
        """Test updating daily limit."""
        existing_pref = JobPreference(
            max_hourly_applications=4,
            max_daily_applications=20
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = existing_pref

        updated = limit_service.update_limits(max_daily=50)

        assert updated.max_hourly_applications == 4
        assert updated.max_daily_applications == 50
        db_session.commit.assert_called()

    def test_update_limits_both(self, limit_service, db_session):
        """Test updating both limits."""
        existing_pref = JobPreference(
            max_hourly_applications=4,
            max_daily_applications=20
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = existing_pref

        updated = limit_service.update_limits(max_hourly=8, max_daily=40)

        assert updated.max_hourly_applications == 8
        assert updated.max_daily_applications == 40
        db_session.commit.assert_called()

    def test_get_hourly_usage_empty(self, limit_service, db_session):
        """Test hourly usage when no applications exist."""
        db_session.execute.return_value.scalars.return_value.all.return_value = []

        count = limit_service.get_hourly_usage()

        assert count == 0

    def test_get_hourly_usage_with_applications(self, limit_service, db_session):
        """Test hourly usage with recent applications."""
        # Create mock applications
        apps = [
            MagicMock(applied_at=datetime.now(UTC) - timedelta(minutes=30)),
            MagicMock(applied_at=datetime.now(UTC) - timedelta(minutes=15)),
        ]
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        count = limit_service.get_hourly_usage()

        assert count == 2

    def test_get_hourly_usage_excludes_old_applications(self, limit_service, db_session):
        """Test that applications older than 1 hour are excluded."""
        # The SQL query filters by time, so we only return the recent app
        apps = [
            MagicMock(applied_at=datetime.now(UTC) - timedelta(minutes=30)),
        ]
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        count = limit_service.get_hourly_usage()

        assert count == 1

    def test_get_daily_usage_empty(self, limit_service, db_session):
        """Test daily usage when no applications exist."""
        db_session.execute.return_value.scalars.return_value.all.return_value = []

        count = limit_service.get_daily_usage()

        assert count == 0

    def test_get_daily_usage_with_applications(self, limit_service, db_session):
        """Test daily usage with recent applications."""
        apps = [
            MagicMock(applied_at=datetime.now(UTC) - timedelta(hours=12)),
            MagicMock(applied_at=datetime.now(UTC) - timedelta(hours=6)),
        ]
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        count = limit_service.get_daily_usage()

        assert count == 2

    def test_get_daily_usage_excludes_old_applications(self, limit_service, db_session):
        """Test that applications older than 24 hours are excluded."""
        # The SQL query filters by time, so we only return the recent app
        apps = [
            MagicMock(applied_at=datetime.now(UTC) - timedelta(hours=12)),
        ]
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        count = limit_service.get_daily_usage()

        assert count == 1

    def test_check_limits_allowed(self, limit_service, db_session):
        """Test limit check when under limits."""
        preference = JobPreference(
            max_hourly_applications=4,
            max_daily_applications=20
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = preference
        db_session.execute.return_value.scalars.return_value.all.return_value = []

        result = limit_service.check_limits()

        assert result.allowed is True
        assert result.reason == "Application limits not exceeded"
        assert result.hourly_used == 0
        assert result.daily_used == 0
        assert result.hourly_remaining == 4
        assert result.daily_remaining == 20

    def test_check_limits_hourly_reached(self, limit_service, db_session):
        """Test limit check when hourly limit is reached."""
        preference = JobPreference(
            max_hourly_applications=4,
            max_daily_applications=20
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = preference
        # Simulate 4 applications in the last hour
        apps = [MagicMock()] * 4
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        result = limit_service.check_limits()

        assert result.allowed is False
        assert "Hourly application limit reached" in result.reason
        assert result.hourly_used == 4
        assert result.hourly_remaining == 0

    def test_check_limits_daily_reached(self, limit_service, db_session):
        """Test limit check when daily limit is reached."""
        preference = JobPreference(
            max_hourly_applications=25,  # Higher than daily to avoid hourly check blocking first
            max_daily_applications=20
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = preference
        # Simulate 20 applications in the last day
        apps = [MagicMock()] * 20
        db_session.execute.return_value.scalars.return_value.all.return_value = apps

        result = limit_service.check_limits()

        assert result.allowed is False
        assert "Daily application limit reached" in result.reason
        assert result.daily_used == 20
        assert result.daily_remaining == 0

    def test_check_limits_partial_usage(self, limit_service, db_session):
        """Test limit check with partial usage."""
        preference = JobPreference(
            max_hourly_applications=4,
            max_daily_applications=20
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = preference
        # Simulate 2 applications in the last hour, 10 in the last day
        db_session.execute.return_value.scalars.return_value.all.return_value = [MagicMock()] * 2

        result = limit_service.check_limits()

        assert result.allowed is True
        assert result.hourly_used == 2
        assert result.daily_used == 2  # Same apps counted for both
        assert result.hourly_remaining == 2
        assert result.daily_remaining == 18

    def test_get_limit_status(self, limit_service, db_session):
        """Test getting limit status."""
        preference = JobPreference(
            max_hourly_applications=4,
            max_daily_applications=20
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = preference
        # Simulate 2 applications
        db_session.execute.return_value.scalars.return_value.all.return_value = [MagicMock()] * 2

        status = limit_service.get_limit_status()

        assert status["max_hourly_applications"] == 4
        assert status["max_daily_applications"] == 20
        assert status["hourly_used"] == 2
        assert status["daily_used"] == 2
        assert status["hourly_remaining"] == 2
        assert status["daily_remaining"] == 18
        assert status["hourly_percentage"] == 50.0
        assert status["daily_percentage"] == 10.0

    def test_get_limit_status_zero_limits(self, limit_service, db_session):
        """Test limit status when limits are zero (edge case)."""
        preference = JobPreference(
            max_hourly_applications=0,
            max_daily_applications=0
        )
        db_session.execute.return_value.scalars.return_value.first.return_value = preference
        db_session.execute.return_value.scalars.return_value.all.return_value = []

        status = limit_service.get_limit_status()

        assert status["hourly_percentage"] == 0
        assert status["daily_percentage"] == 0


class TestLimitCheckResult:
    """Tests for the LimitCheckResult class."""

    def test_limit_check_result_allowed(self):
        """Test creating an allowed result."""
        result = LimitCheckResult(
            allowed=True,
            reason="OK",
            hourly_used=2,
            daily_used=10,
            hourly_remaining=2,
            daily_remaining=10
        )

        assert result.allowed is True
        assert result.reason == "OK"
        assert result.hourly_used == 2
        assert result.daily_used == 10

    def test_limit_check_result_blocked(self):
        """Test creating a blocked result."""
        result = LimitCheckResult(
            allowed=False,
            reason="Hourly limit reached",
            hourly_used=4,
            daily_used=15,
            hourly_remaining=0,
            daily_remaining=5
        )

        assert result.allowed is False
        assert result.reason == "Hourly limit reached"
        assert result.hourly_remaining == 0
