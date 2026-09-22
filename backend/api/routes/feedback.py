import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.schemas.feedback import FeedbackCreate, FeedbackResponse, FeedbackSummary
from backend.services.learning.service import FeedbackService
from backend.core.logging import get_logger

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("/submit", response_model=FeedbackResponse)
def submit_feedback(
    feedback: FeedbackCreate,
    db: Session = Depends(get_db)
):
    """
    Submit user feedback for a job.
    Feedback influences ranking but never overrides hard filters.
    """
    feedback_service = FeedbackService(db)
    return feedback_service.submit_feedback(feedback)


@router.get("/job/{job_id}", response_model=list[FeedbackResponse])
def get_job_feedback(
    job_id: int,
    db: Session = Depends(get_db)
):
    """Get all feedback for a specific job."""
    feedback_service = FeedbackService(db)
    return feedback_service.get_feedback_for_job(job_id)


@router.get("/summary", response_model=FeedbackSummary)
def get_feedback_summary(
    job_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db)
):
    """
    Get feedback summary.
    Optionally filter by specific job ID.
    """
    feedback_service = FeedbackService(db)
    return feedback_service.get_feedback_summary(job_id)


@router.delete("/{feedback_id}")
def delete_feedback(
    feedback_id: int,
    db: Session = Depends(get_db)
):
    """Delete a feedback record."""
    feedback_service = FeedbackService(db)
    success = feedback_service.delete_feedback(feedback_id)
    if not success:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return {"message": "Feedback deleted successfully"}
