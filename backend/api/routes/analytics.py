import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.services.analytics.service import AnalyticsService
from backend.core.logging import get_logger

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary")
def get_analytics_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive analytics summary for the specified time period.
    Includes job discovery, application metrics, AI usage, and discovery runs.
    """
    analytics_service = AnalyticsService(db)
    return analytics_service.get_analytics_summary(days)


@router.get("/skip-reasons")
def get_skip_reasons(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get top skip reasons with counts."""
    analytics_service = AnalyticsService(db)
    return analytics_service.get_skip_reasons(days, limit)


@router.get("/decision-breakdown")
def get_decision_breakdown(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """Get decision priority breakdown with counts and percentages."""
    analytics_service = AnalyticsService(db)
    return analytics_service.get_decision_breakdown(days)


@router.get("/applications-by-day")
def get_applications_by_day(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """Get application counts by day."""
    analytics_service = AnalyticsService(db)
    return analytics_service.get_applications_by_day(days)


@router.get("/applications-by-profile")
def get_applications_by_job_profile(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """Get application breakdown by job title/source."""
    analytics_service = AnalyticsService(db)
    return analytics_service.get_applications_by_job_profile(days)


@router.get("/primary-reasons")
def get_primary_reason_codes(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db)
):
    """Get top primary reason codes from decision records."""
    analytics_service = AnalyticsService(db)
    return analytics_service.get_primary_reason_codes(days, limit)


@router.get("/feedback-summary")
def get_feedback_summary(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """Get feedback summary metrics."""
    analytics_service = AnalyticsService(db)
    return analytics_service.get_feedback_summary(days)


@router.get("/recent-decisions")
def get_recent_decision_activity(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get recent decision quality records."""
    analytics_service = AnalyticsService(db)
    return analytics_service.get_recent_decision_activity(limit)
