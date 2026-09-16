import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.dependencies import get_db
from backend.models.matching import JobPreference
from backend.schemas.matching import (
    JobPreferenceUpdate, JobPreferenceResponse, 
    EvaluateJobRequest, MatchDecision
)
from backend.models.profile import Profile
from backend.models.job import Job
from backend.schemas.profile import ProfileStatus
from backend.services.matching.engine import MatchEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/matching", tags=["matching"])



def get_current_preference(db: Session) -> JobPreference:
    pref = db.query(JobPreference).first()
    if not pref:
        pref = JobPreference()
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


@router.get("/preferences", response_model=JobPreferenceResponse)
def get_preferences(db: Session = Depends(get_db)):
    pref = get_current_preference(db)
    return pref


@router.put("/preferences", response_model=JobPreferenceResponse)
def update_preferences(req: JobPreferenceUpdate, db: Session = Depends(get_db)):
    pref = get_current_preference(db)
    pref.locations = req.locations
    pref.job_titles = req.job_titles
    pref.employment_types = req.employment_types
    pref.min_salary_lpa = req.min_salary_lpa
    pref.aggressiveness = req.aggressiveness.value
    pref.max_daily_applications = req.max_daily_applications
    pref.max_hourly_applications = req.max_hourly_applications
    
    db.commit()
    db.refresh(pref)
    return pref


@router.post("/evaluate", response_model=MatchDecision)
def evaluate_job(req: EvaluateJobRequest, db: Session = Depends(get_db)):
    pref = get_current_preference(db)
    profile = db.query(Profile).filter(Profile.confirmed == True).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Confirmed profile not found.")
        
    engine = MatchEngine(db)
    job = Job(title=req.title, company=req.company, description=req.description, url=req.url, platform="naukri")
    decision = engine.evaluate_job(job, profile, pref)
    return decision
