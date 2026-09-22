import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from backend.models.job import Job
from backend.models.application import Application
from backend.models.ai import AIUsage, JobAnalysisModel
from backend.models.discovery import DiscoveryRun
from backend.models.feedback import DecisionQualityRecord, JobFeedback
from backend.schemas.decision import DecisionPriority, DecisionReasonCode
from backend.core.logging import get_logger

logger = get_logger(__name__)


class AnalyticsService:
    """
    Provides application analytics and aggregate metrics.
    Uses existing Job, Application, and decision data.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_analytics_summary(self, days: int = 30) -> dict:
        """
        Get comprehensive analytics summary for the specified time period.
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        
        # Job discovery metrics
        discovered_jobs = self.session.execute(
            select(func.count(Job.id)).where(Job.discovered_at >= cutoff_date)
        ).scalar() or 0
        
        # Application metrics
        total_applications = self.session.execute(
            select(func.count(Application.id)).where(Application.created_at >= cutoff_date)
        ).scalar() or 0
        
        successful_applications = self.session.execute(
            select(func.count(Application.id)).where(
                and_(
                    Application.created_at >= cutoff_date,
                    Application.status.in_(["APPLIED", "SUBMITTED"])
                )
            )
        ).scalar() or 0
        
        skipped_applications = self.session.execute(
            select(func.count(Application.id)).where(
                and_(
                    Application.created_at >= cutoff_date,
                    Application.status == "SKIPPED"
                )
            )
        ).scalar() or 0
        
        needs_attention = self.session.execute(
            select(func.count(Application.id)).where(
                and_(
                    Application.created_at >= cutoff_date,
                    Application.status == "NEEDS_ATTENTION"
                )
            )
        ).scalar() or 0
        
        external_applications = self.session.execute(
            select(func.count(Application.id)).where(
                and_(
                    Application.created_at >= cutoff_date,
                    Application.status == "EXTERNAL_APPLICATION"
                )
            )
        ).scalar() or 0
        
        # Success rate
        success_rate = (successful_applications / total_applications * 100) if total_applications > 0 else 0.0
        
        # AI usage metrics
        ai_requests = self.session.execute(
            select(func.count(AIUsage.id)).where(AIUsage.created_at >= cutoff_date)
        ).scalar() or 0
        
        ai_analyses = self.session.execute(
            select(func.count(JobAnalysisModel.id)).where(JobAnalysisModel.created_at >= cutoff_date)
        ).scalar() or 0
        
        # Discovery runs
        discovery_runs = self.session.execute(
            select(func.count(DiscoveryRun.id)).where(DiscoveryRun.started_at >= cutoff_date)
        ).scalar() or 0
        
        return {
            "period_days": days,
            "discovered_jobs": discovered_jobs,
            "total_applications": total_applications,
            "successful_applications": successful_applications,
            "skipped_applications": skipped_applications,
            "needs_attention": needs_attention,
            "external_applications": external_applications,
            "success_rate": round(success_rate, 2),
            "ai_requests": ai_requests,
            "ai_analyses": ai_analyses,
            "discovery_runs": discovery_runs
        }
    
    def get_skip_reasons(self, days: int = 30, limit: int = 10) -> list[dict]:
        """Get top skip reasons with counts."""
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        
        stmt = select(
            Application.skip_reason,
            func.count(Application.id).label('count')
        ).where(
            and_(
                Application.created_at >= cutoff_date,
                Application.status == "SKIPPED",
                Application.skip_reason.isnot(None)
            )
        ).group_by(
            Application.skip_reason
        ).order_by(
            func.count(Application.id).desc()
        ).limit(limit)
        
        results = self.session.execute(stmt).all()
        
        return [
            {"reason": row.skip_reason or "Unknown", "count": row.count}
            for row in results
        ]
    
    def get_decision_breakdown(self, days: int = 30) -> dict:
        """Get decision priority breakdown."""
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        
        stmt = select(
            DecisionQualityRecord.priority,
            func.count(DecisionQualityRecord.id).label('count')
        ).where(
            DecisionQualityRecord.created_at >= cutoff_date
        ).group_by(
            DecisionQualityRecord.priority
        )
        
        results = self.session.execute(stmt).all()
        
        breakdown = {
            "HIGH_PRIORITY": 0,
            "NORMAL_PRIORITY": 0,
            "LOW_PRIORITY": 0,
            "SKIP": 0,
            "HARD_REJECT": 0,
            "NEEDS_ATTENTION": 0
        }
        
        for row in results:
            breakdown[row.priority] = row.count
        
        total = sum(breakdown.values())
        
        return {
            "breakdown": breakdown,
            "total": total,
            "percentages": {
                key: (count / total * 100) if total > 0 else 0.0
                for key, count in breakdown.items()
            }
        }
    
    def get_applications_by_day(self, days: int = 30) -> list[dict]:
        """Get application counts by day."""
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        
        stmt = select(
            func.date(Application.created_at).label('date'),
            func.count(Application.id).label('count')
        ).where(
            Application.created_at >= cutoff_date
        ).group_by(
            func.date(Application.created_at)
        ).order_by(
            func.date(Application.created_at)
        )
        
        results = self.session.execute(stmt).all()
        
        return [
            {"date": str(row.date), "count": row.count}
            for row in results
        ]
    
    def get_applications_by_job_profile(self, days: int = 30) -> list[dict]:
        """Get application breakdown by job title/source."""
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        
        stmt = select(
            Job.title,
            func.count(Application.id).label('count')
        ).join(
            Application, Application.job_id == Job.id
        ).where(
            and_(
                Application.created_at >= cutoff_date,
                Application.status.in_(["APPLIED", "SUBMITTED"])
            )
        ).group_by(
            Job.title
        ).order_by(
            func.count(Application.id).desc()
        ).limit(20)
        
        results = self.session.execute(stmt).all()
        
        return [
            {"job_title": row.title or "Unknown", "count": row.count}
            for row in results
        ]
    
    def get_primary_reason_codes(self, days: int = 30, limit: int = 10) -> list[dict]:
        """Get top primary reason codes from decision records."""
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        
        stmt = select(
            DecisionQualityRecord.primary_reason_code,
            func.count(DecisionQualityRecord.id).label('count')
        ).where(
            DecisionQualityRecord.created_at >= cutoff_date
        ).group_by(
            DecisionQualityRecord.primary_reason_code
        ).order_by(
            func.count(DecisionQualityRecord.id).desc()
        ).limit(limit)
        
        results = self.session.execute(stmt).all()
        
        return [
            {"reason_code": row.primary_reason_code, "count": row.count}
            for row in results
        ]
    
    def get_feedback_summary(self, days: int = 30) -> dict:
        """Get feedback summary metrics."""
        cutoff_date = datetime.now(UTC) - timedelta(days=days)
        
        total_feedback = self.session.execute(
            select(func.count(JobFeedback.id)).where(JobFeedback.created_at >= cutoff_date)
        ).scalar() or 0
        
        if total_feedback == 0:
            return {
                "total_feedback": 0,
                "relevant_count": 0,
                "not_relevant_count": 0,
                "applied_count": 0,
                "skipped_count": 0,
                "incorrect_match_count": 0,
                "good_match_count": 0,
                "relevance_rate": 0.0
            }
        
        relevant_count = self.session.execute(
            select(func.count(JobFeedback.id)).where(
                and_(
                    JobFeedback.created_at >= cutoff_date,
                    JobFeedback.feedback_type == "RELEVANT"
                )
            )
        ).scalar() or 0
        
        not_relevant_count = self.session.execute(
            select(func.count(JobFeedback.id)).where(
                and_(
                    JobFeedback.created_at >= cutoff_date,
                    JobFeedback.feedback_type == "NOT_RELEVANT"
                )
            )
        ).scalar() or 0
        
        applied_count = self.session.execute(
            select(func.count(JobFeedback.id)).where(
                and_(
                    JobFeedback.created_at >= cutoff_date,
                    JobFeedback.feedback_type == "APPLIED"
                )
            )
        ).scalar() or 0
        
        skipped_count = self.session.execute(
            select(func.count(JobFeedback.id)).where(
                and_(
                    JobFeedback.created_at >= cutoff_date,
                    JobFeedback.feedback_type == "SKIPPED"
                )
            )
        ).scalar() or 0
        
        incorrect_match_count = self.session.execute(
            select(func.count(JobFeedback.id)).where(
                and_(
                    JobFeedback.created_at >= cutoff_date,
                    JobFeedback.feedback_type == "INCORRECT_MATCH"
                )
            )
        ).scalar() or 0
        
        good_match_count = self.session.execute(
            select(func.count(JobFeedback.id)).where(
                and_(
                    JobFeedback.created_at >= cutoff_date,
                    JobFeedback.feedback_type == "GOOD_MATCH"
                )
            )
        ).scalar() or 0
        
        relevance_rate = relevant_count / total_feedback if total_feedback > 0 else 0.0
        
        return {
            "total_feedback": total_feedback,
            "relevant_count": relevant_count,
            "not_relevant_count": not_relevant_count,
            "applied_count": applied_count,
            "skipped_count": skipped_count,
            "incorrect_match_count": incorrect_match_count,
            "good_match_count": good_match_count,
            "relevance_rate": round(relevance_rate, 2)
        }
    
    def get_recent_decision_activity(self, limit: int = 20) -> list[dict]:
        """Get recent decision quality records."""
        stmt = select(DecisionQualityRecord).order_by(
            DecisionQualityRecord.created_at.desc()
        ).limit(limit)
        
        records = self.session.execute(stmt).scalars().all()
        
        return [
            {
                "job_id": record.job_id,
                "priority": record.priority,
                "decision_score": record.decision_score,
                "primary_reason_code": record.primary_reason_code,
                "explanation": record.explanation,
                "created_at": record.created_at.isoformat()
            }
            for record in records
        ]
