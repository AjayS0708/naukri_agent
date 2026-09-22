import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.schemas.decision import (
    DecisionQuality, DecisionPriority, JobPriorityResponse, BulkPriorityResponse
)
from backend.services.decision.quality import DecisionQualityService
from backend.core.logging import get_logger

logger = get_logger(__name__)


class JobPrioritizationService:
    """
    Prioritizes jobs for application processing.
    Uses deterministic scoring based on decision quality signals.
    """
    
    def __init__(self, session: Session):
        self.session = session
        self.decision_service = DecisionQualityService(session)
    
    def prioritize_jobs(
        self,
        job_ids: list[int],
        profile: Profile,
        preference: JobPreference
    ) -> BulkPriorityResponse:
        """
        Prioritize a list of jobs for application processing.
        Returns jobs sorted by priority (highest first).
        """
        prioritized = []
        
        for job_id in job_ids:
            job = self.session.get(Job, job_id)
            if not job:
                logger.warning(f"Job {job_id} not found for prioritization")
                continue
            
            # Get AI analysis if available
            job_analysis = self.session.execute(
                select(JobAnalysisModel).where(JobAnalysisModel.job_id == job_id)
            ).scalars().first()
            
            # Evaluate decision quality
            decision = self.decision_service.evaluate_job_decision(
                job, profile, preference, job_analysis
            )
            
            prioritized.append(JobPriorityResponse(
                job_id=job_id,
                priority=decision.priority,
                decision_score=decision.decision_score,
                explanation=decision.explanation,
                primary_reason_code=decision.primary_reason_code
            ))
        
        # Sort by priority (descending: HIGH > NORMAL > LOW > SKIP > HARD_REJECT)
        priority_order = {
            DecisionPriority.HIGH_PRIORITY: 5,
            DecisionPriority.NORMAL_PRIORITY: 4,
            DecisionPriority.LOW_PRIORITY: 3,
            DecisionPriority.SKIP: 2,
            DecisionPriority.HARD_REJECT: 1,
            DecisionPriority.NEEDS_ATTENTION: 0  # Process needs attention last
        }
        
        prioritized.sort(
            key=lambda x: (
                priority_order.get(x.priority, 0),
                -x.decision_score  # Higher score first within same priority
            )
        )
        
        # Count priorities
        counts = {
            "high_priority_count": 0,
            "normal_priority_count": 0,
            "low_priority_count": 0,
            "skip_count": 0,
            "hard_reject_count": 0,
            "needs_attention_count": 0
        }
        
        for item in prioritized:
            if item.priority == DecisionPriority.HIGH_PRIORITY:
                counts["high_priority_count"] += 1
            elif item.priority == DecisionPriority.NORMAL_PRIORITY:
                counts["normal_priority_count"] += 1
            elif item.priority == DecisionPriority.LOW_PRIORITY:
                counts["low_priority_count"] += 1
            elif item.priority == DecisionPriority.SKIP:
                counts["skip_count"] += 1
            elif item.priority == DecisionPriority.HARD_REJECT:
                counts["hard_reject_count"] += 1
            elif item.priority == DecisionPriority.NEEDS_ATTENTION:
                counts["needs_attention_count"] += 1
        
        return BulkPriorityResponse(
            prioritized_jobs=prioritized,
            total_jobs=len(prioritized),
            **counts
        )
    
    def get_eligible_jobs_for_application(
        self,
        job_ids: list[int],
        profile: Profile,
        preference: JobPreference
    ) -> list[int]:
        """
        Get list of job IDs that are eligible for application.
        Filters out HARD_REJECT and SKIP priorities.
        Returns job IDs sorted by priority (highest first).
        """
        bulk_response = self.prioritize_jobs(job_ids, profile, preference)
        
        # Filter to only eligible priorities
        eligible_priorities = {
            DecisionPriority.HIGH_PRIORITY,
            DecisionPriority.NORMAL_PRIORITY,
            DecisionPriority.LOW_PRIORITY
        }
        
        eligible_jobs = [
            item.job_id for item in bulk_response.prioritized_jobs
            if item.priority in eligible_priorities
        ]
        
        return eligible_jobs
    
    def get_prioritized_eligible_jobs(
        self,
        job_ids: list[int],
        profile: Profile,
        preference: JobPreference,
        limit: Optional[int] = None
    ) -> list[JobPriorityResponse]:
        """
        Get prioritized eligible jobs for application.
        Returns job priority responses sorted by priority (highest first).
        """
        bulk_response = self.prioritize_jobs(job_ids, profile, preference)
        
        # Filter to only eligible priorities
        eligible_priorities = {
            DecisionPriority.HIGH_PRIORITY,
            DecisionPriority.NORMAL_PRIORITY,
            DecisionPriority.LOW_PRIORITY
        }
        
        eligible_jobs = [
            item for item in bulk_response.prioritized_jobs
            if item.priority in eligible_priorities
        ]
        
        # Apply limit if specified
        if limit and limit > 0:
            eligible_jobs = eligible_jobs[:limit]
        
        return eligible_jobs
