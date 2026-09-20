from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.matching import JobPreference
from backend.schemas.application import ApplicationStatus
from backend.core.logging import get_logger

logger = get_logger(__name__)


class LimitCheckResult:
    """Result of an application limit check."""
    def __init__(
        self,
        allowed: bool,
        reason: Optional[str] = None,
        hourly_used: int = 0,
        daily_used: int = 0,
        hourly_remaining: int = 0,
        daily_remaining: int = 0
    ):
        self.allowed = allowed
        self.reason = reason
        self.hourly_used = hourly_used
        self.daily_used = daily_used
        self.hourly_remaining = hourly_remaining
        self.daily_remaining = daily_remaining


class ApplicationLimitService:
    """
    Service for enforcing hourly and daily application volume limits.
    
    Uses deterministic Python logic only - Gemini never decides limits.
    Counts only successful applications (APPLIED or SUBMITTED status).
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_limits(self) -> JobPreference:
        """Get current application limits from JobPreference."""
        preference = self.session.execute(select(JobPreference)).scalars().first()
        if not preference:
            # Create default preference if none exists
            preference = JobPreference()
            self.session.add(preference)
            self.session.commit()
            self.session.refresh(preference)
        return preference
    
    def update_limits(
        self,
        max_hourly: Optional[int] = None,
        max_daily: Optional[int] = None
    ) -> JobPreference:
        """Update application limits."""
        preference = self.get_limits()
        
        if max_hourly is not None and max_hourly >= 0:
            preference.max_hourly_applications = max_hourly
        if max_daily is not None and max_daily >= 0:
            preference.max_daily_applications = max_daily
        
        self.session.commit()
        self.session.refresh(preference)
        logger.info(f"Application limits updated: hourly={preference.max_hourly_applications}, daily={preference.max_daily_applications}")
        return preference
    
    def get_hourly_usage(self) -> int:
        """
        Count successful applications in the last hour.
        Only counts APPLIED or SUBMITTED status applications.
        """
        one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
        
        stmt = select(Application).where(
            and_(
                Application.status.in_([ApplicationStatus.APPLIED.value, ApplicationStatus.SUBMITTED.value]),
                Application.applied_at >= one_hour_ago
            )
        )
        count = len(self.session.execute(stmt).scalars().all())
        return count
    
    def get_daily_usage(self) -> int:
        """
        Count successful applications in the last 24 hours.
        Only counts APPLIED or SUBMITTED status applications.
        """
        one_day_ago = datetime.now(UTC) - timedelta(days=1)
        
        stmt = select(Application).where(
            and_(
                Application.status.in_([ApplicationStatus.APPLIED.value, ApplicationStatus.SUBMITTED.value]),
                Application.applied_at >= one_day_ago
            )
        )
        count = len(self.session.execute(stmt).scalars().all())
        return count
    
    def check_limits(self) -> LimitCheckResult:
        """
        Check if another application is allowed based on current limits.
        
        Returns LimitCheckResult with detailed information.
        """
        preference = self.get_limits()
        hourly_used = self.get_hourly_usage()
        daily_used = self.get_daily_usage()
        
        hourly_remaining = max(0, preference.max_hourly_applications - hourly_used)
        daily_remaining = max(0, preference.max_daily_applications - daily_used)
        
        # Check hourly limit
        if hourly_used >= preference.max_hourly_applications:
            return LimitCheckResult(
                allowed=False,
                reason=f"Hourly application limit reached ({hourly_used}/{preference.max_hourly_applications})",
                hourly_used=hourly_used,
                daily_used=daily_used,
                hourly_remaining=0,
                daily_remaining=daily_remaining
            )
        
        # Check daily limit
        if daily_used >= preference.max_daily_applications:
            return LimitCheckResult(
                allowed=False,
                reason=f"Daily application limit reached ({daily_used}/{preference.max_daily_applications})",
                hourly_used=hourly_used,
                daily_used=daily_used,
                hourly_remaining=hourly_remaining,
                daily_remaining=0
            )
        
        # Both limits allow another application
        return LimitCheckResult(
            allowed=True,
            reason="Application limits not exceeded",
            hourly_used=hourly_used,
            daily_used=daily_used,
            hourly_remaining=hourly_remaining,
            daily_remaining=daily_remaining
        )
    
    def get_limit_status(self) -> dict:
        """
        Get current limit status including usage and remaining capacity.
        """
        preference = self.get_limits()
        hourly_used = self.get_hourly_usage()
        daily_used = self.get_daily_usage()
        
        return {
            "max_hourly_applications": preference.max_hourly_applications,
            "max_daily_applications": preference.max_daily_applications,
            "hourly_used": hourly_used,
            "daily_used": daily_used,
            "hourly_remaining": max(0, preference.max_hourly_applications - hourly_used),
            "daily_remaining": max(0, preference.max_daily_applications - daily_used),
            "hourly_percentage": round((hourly_used / preference.max_hourly_applications) * 100, 1) if preference.max_hourly_applications > 0 else 0,
            "daily_percentage": round((daily_used / preference.max_daily_applications) * 100, 1) if preference.max_daily_applications > 0 else 0
        }
