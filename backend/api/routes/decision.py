import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.models.ai import JobAnalysisModel
from backend.schemas.decision import (
    DecisionQuality, DecisionHistoryRequest, DecisionHistoryResponse,
    JobPriorityRequest, BulkPriorityResponse
)
from backend.services.decision.quality import DecisionQualityService
from backend.services.decision.prioritization import JobPrioritizationService
from backend.core.logging import get_logger

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/decision", tags=["decision"])


def get_current_profile(db: Session) -> Profile:
    """Get current confirmed profile."""
    profile = db.query(Profile).filter(Profile.confirmed == True).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Confirmed profile not found")
    return profile


def get_current_preference(db: Session) -> JobPreference:
    """Get current job preferences."""
    pref = db.query(JobPreference).first()
    if not pref:
        pref = JobPreference()
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


@router.post("/evaluate/{job_id}", response_model=DecisionQuality)
def evaluate_job_decision(
    job_id: int,
    db: Session = Depends(get_db)
):
    """
    Evaluate decision quality for a specific job.
    Returns comprehensive decision assessment with explainable reasoning.
    """
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    profile = get_current_profile(db)
    preference = get_current_preference(db)
    
    # Get AI analysis if available
    job_analysis = db.query(JobAnalysisModel).filter(
        JobAnalysisModel.job_id == job_id
    ).first()
    
    decision_service = DecisionQualityService(db)
    decision = decision_service.evaluate_job_decision(
        job, profile, preference, job_analysis
    )
    
    # Save decision record for analytics
    decision_service.save_decision_record(decision, job_id)
    
    return decision


@router.post("/prioritize", response_model=BulkPriorityResponse)
def prioritize_jobs(
    request: JobPriorityRequest,
    db: Session = Depends(get_db)
):
    """
    Prioritize a list of jobs for application processing.
    Returns jobs sorted by priority (highest first).
    """
    profile = get_current_profile(db)
    preference = get_current_preference(db)
    
    prioritization_service = JobPrioritizationService(db)
    result = prioritization_service.prioritize_jobs(
        request.job_ids, profile, preference
    )
    
    return result


@router.get("/history/{job_id}", response_model=DecisionHistoryResponse)
def get_decision_history(
    job_id: int,
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get decision history for a specific job.
    """
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # For now, return current decision only
    # History can be extended later if we store multiple evaluations
    profile = get_current_profile(db)
    preference = get_current_preference(db)
    
    job_analysis = db.query(JobAnalysisModel).filter(
        JobAnalysisModel.job_id == job_id
    ).first()
    
    decision_service = DecisionQualityService(db)
    decision = decision_service.evaluate_job_decision(
        job, profile, preference, job_analysis
    )
    
    return DecisionHistoryResponse(
        job_id=job_id,
        decisions=[decision]
    )
