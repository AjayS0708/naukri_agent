import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.models.feedback import JobFeedback
from backend.schemas.feedback import FeedbackCreate, FeedbackResponse, FeedbackSummary
from backend.core.logging import get_logger

logger = get_logger(__name__)


class FeedbackService:
    """
    Manages user feedback on jobs for learning and prioritization.
    Feedback influences ranking but never overrides hard filters.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def submit_feedback(self, feedback: FeedbackCreate) -> FeedbackResponse:
        """Submit user feedback for a job."""
        job_feedback = JobFeedback(
            job_id=feedback.job_id,
            feedback_type=feedback.feedback_type.value,
            comments=feedback.comments
        )
        self.session.add(job_feedback)
        self.session.commit()
        self.session.refresh(job_feedback)
        
        logger.info(f"Feedback submitted for job {feedback.job_id}: {feedback.feedback_type.value}")
        
        return FeedbackResponse(
            id=job_feedback.id,
            job_id=job_feedback.job_id,
            feedback_type=feedback.feedback_type,
            comments=job_feedback.comments,
            created_at=job_feedback.created_at
        )
    
    def get_feedback_for_job(self, job_id: int) -> list[FeedbackResponse]:
        """Get all feedback for a specific job."""
        stmt = select(JobFeedback).where(JobFeedback.job_id == job_id)
        feedbacks = self.session.execute(stmt).scalars().all()
        
        return [
            FeedbackResponse(
                id=f.id,
                job_id=f.job_id,
                feedback_type=f.feedback_type,
                comments=f.comments,
                created_at=f.created_at
            )
            for f in feedbacks
        ]
    
    def get_feedback_summary(self, job_id: Optional[int] = None) -> FeedbackSummary:
        """Get feedback summary, optionally filtered by job."""
        stmt = select(JobFeedback)
        if job_id is not None:
            stmt = stmt.where(JobFeedback.job_id == job_id)
        
        feedbacks = self.session.execute(stmt).scalars().all()
        
        total = len(feedbacks)
        if total == 0:
            return FeedbackSummary(
                total_feedback=0,
                relevant_count=0,
                not_relevant_count=0,
                applied_count=0,
                skipped_count=0,
                incorrect_match_count=0,
                good_match_count=0,
                relevance_rate=0.0
            )
        
        relevant_count = sum(1 for f in feedbacks if f.feedback_type == "RELEVANT")
        not_relevant_count = sum(1 for f in feedbacks if f.feedback_type == "NOT_RELEVANT")
        applied_count = sum(1 for f in feedbacks if f.feedback_type == "APPLIED")
        skipped_count = sum(1 for f in feedbacks if f.feedback_type == "SKIPPED")
        incorrect_match_count = sum(1 for f in feedbacks if f.feedback_type == "INCORRECT_MATCH")
        good_match_count = sum(1 for f in feedbacks if f.feedback_type == "GOOD_MATCH")
        
        relevance_rate = relevant_count / total if total > 0 else 0.0
        
        return FeedbackSummary(
            total_feedback=total,
            relevant_count=relevant_count,
            not_relevant_count=not_relevant_count,
            applied_count=applied_count,
            skipped_count=skipped_count,
            incorrect_match_count=incorrect_match_count,
            good_match_count=good_match_count,
            relevance_rate=relevance_rate
        )
    
    def delete_feedback(self, feedback_id: int) -> bool:
        """Delete a feedback record."""
        feedback = self.session.get(JobFeedback, feedback_id)
        if not feedback:
            return False
        
        self.session.delete(feedback)
        self.session.commit()
        logger.info(f"Feedback {feedback_id} deleted")
        return True
