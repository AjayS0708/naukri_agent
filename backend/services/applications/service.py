from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.application import Application, ApplicationAnswer as ApplicationAnswerModel
from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference, MatchResult
from backend.models.ai import JobAnalysisModel
from backend.schemas.application import (
    ApplicationStatus, ApplicationMethod, ApplicationSchema,
    ApplicationCreate, ApplicationUpdate
)
from backend.schemas.ai import JobAnalysis, AIRecommendation
from backend.services.matching.normalizer import (
    has_overlapping_location,
    extract_lowest_salary_lpa,
    extract_experience_years,
    is_employment_type_allowed
)
from backend.core.logging import get_logger

logger = get_logger(__name__)


class SafetyGateError(Exception):
    """Raised when the safety gate blocks an application."""
    pass


class ApplicationService:
    """
    Coordinates the application flow with final safety gate.
    Gemini provides advisory analysis; Python rules are authoritative.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def create_application(self, create: ApplicationCreate) -> ApplicationSchema:
        """Create a new application record."""
        application = Application(
            job_id=create.job_id,
            status=create.status.value,
            application_method=create.application_method.value if create.application_method else None
        )
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)
    
    def get_application(self, application_id: int) -> Optional[ApplicationSchema]:
        """Get an application by ID."""
        application = self.session.get(Application, application_id)
        if not application:
            return None
        return self._to_schema(application)
    
    def update_application(self, application_id: int, update: ApplicationUpdate) -> Optional[ApplicationSchema]:
        """Update an application."""
        application = self.session.get(Application, application_id)
        if not application:
            return None
        
        if update.status is not None:
            application.status = update.status.value
        if update.application_method is not None:
            application.application_method = update.application_method.value
        if update.started_at is not None:
            application.started_at = update.started_at
        if update.applied_at is not None:
            application.applied_at = update.applied_at
        if update.failure_reason is not None:
            application.failure_reason = update.failure_reason
        if update.skip_reason is not None:
            application.skip_reason = update.skip_reason
        if update.external_url is not None:
            application.external_url = update.external_url
        if update.needs_attention is not None:
            application.needs_attention = update.needs_attention
        
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)
    
    def get_application_by_job(self, job_id: int) -> Optional[ApplicationSchema]:
        """Get the most recent application for a job."""
        stmt = select(Application).where(Application.job_id == job_id).order_by(Application.created_at.desc())
        application = self.session.execute(stmt).scalars().first()
        if not application:
            return None
        return self._to_schema(application)
    
    def run_final_safety_gate(
        self,
        job: Job,
        profile: Profile,
        preference: JobPreference,
        job_analysis: Optional[JobAnalysis] = None
    ) -> tuple[bool, str]:
        """
        Final deterministic Python safety gate before application submission.
        Gemini output is advisory; this gate is authoritative.
        
        Returns:
            (allowed: bool, reason: str)
        """
        # 1. Job exists
        if not job or not job.id:
            return False, "Job does not exist"
        
        # 2. Profile is confirmed
        if not profile or not profile.confirmed:
            return False, "Profile is not confirmed by user"
        
        # 3. Check if already applied (duplicate protection)
        existing_application = self.get_application_by_job(job.id)
        if existing_application and existing_application.status in [ApplicationStatus.APPLIED, ApplicationStatus.SUBMITTED]:
            return False, "Job already applied to"
        
        # 4. Location hard filter
        if job.location and preference.locations:
            if not has_overlapping_location(job.location, preference.locations):
                return False, f"Location mismatch: job location '{job.location}' not in allowed locations"
        
        # 5. Experience hard filter
        if job.experience:
            exp_min, exp_max = extract_experience_years(job.experience)
            if exp_min is not None:
                user_exp_years = len(profile.data.get("experience", [])) if isinstance(profile.data, dict) else 0
                if exp_min > user_exp_years + 2:  # 2 year grace period
                    return False, f"Experience required ({exp_min}y) exceeds user profile ({user_exp_years}y)"
        
        # 6. Salary minimum rule
        if job.salary and preference.min_salary_lpa is not None:
            salary_lpa = extract_lowest_salary_lpa(job.salary)
            if salary_lpa is not None and salary_lpa < preference.min_salary_lpa:
                return False, f"Salary ({salary_lpa} LPA) below minimum ({preference.min_salary_lpa} LPA)"
        
        # 7. Employment type
        if job.employment_type and preference.employment_types:
            if not is_employment_type_allowed(job.employment_type, preference.employment_types):
                return False, f"Employment type '{job.employment_type}' not allowed"
        
        # 8. Job title/search scope
        if preference.job_titles and job.title:
            title_match = any(
                title.lower() in job.title.lower() 
                for title in preference.job_titles
            )
            if not title_match:
                return False, f"Job title '{job.title}' not in configured search scope"
        
        # 9. Gemini suspicious flag (if analysis available)
        if job_analysis and job_analysis.suspicious:
            return False, "Job flagged as suspicious by AI analysis"
        
        # 10. Gemini recommendation validation (if analysis available)
        if job_analysis:
            if job_analysis.recommendation == AIRecommendation.NEEDS_ATTENTION:
                return False, f"AI recommends attention: {job_analysis.short_reason}"
        
        return True, "All safety checks passed"
    
    def check_duplicate_application(self, job: Job) -> bool:
        """
        Check if this job has already been applied to.
        Returns True if duplicate, False otherwise.
        """
        existing = self.get_application_by_job(job.id)
        if existing and existing.status in [ApplicationStatus.APPLIED, ApplicationStatus.SUBMITTED]:
            return True
        return False
    
    def record_external_application(
        self,
        job: Job,
        external_url: str,
        reason: str = "External application redirect"
    ) -> ApplicationSchema:
        """
        Record an external application redirect.
        Does NOT submit the external application.
        """
        application = Application(
            job_id=job.id,
            status=ApplicationStatus.EXTERNAL_APPLICATION.value,
            application_method=ApplicationMethod.EXTERNAL.value,
            external_url=external_url,
            skip_reason=reason,
            needs_attention=True,
            started_at=datetime.now(UTC)
        )
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)
    
    def record_application_failure(
        self,
        job: Job,
        failure_reason: str,
        needs_attention: bool = True
    ) -> ApplicationSchema:
        """Record an application failure."""
        application = Application(
            job_id=job.id,
            status=ApplicationStatus.NEEDS_ATTENTION.value if needs_attention else ApplicationStatus.SKIPPED.value,
            failure_reason=failure_reason,
            needs_attention=needs_attention,
            started_at=datetime.now(UTC)
        )
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)
    
    def record_application_skip(
        self,
        job: Job,
        skip_reason: str
    ) -> ApplicationSchema:
        """Record a skipped application."""
        application = Application(
            job_id=job.id,
            status=ApplicationStatus.SKIPPED.value,
            skip_reason=skip_reason,
            started_at=datetime.now(UTC)
        )
        self.session.add(application)
        self.session.commit()
        self.session.refresh(application)
        return self._to_schema(application)
    
    def get_application_history(self, limit: int = 100) -> list[ApplicationSchema]:
        """Get application history."""
        stmt = select(Application).order_by(Application.created_at.desc()).limit(limit)
        applications = self.session.execute(stmt).scalars().all()
        return [self._to_schema(app) for app in applications]
    
    def _to_schema(self, application: Application) -> ApplicationSchema:
        """Convert model to schema."""
        return ApplicationSchema(
            id=application.id,
            job_id=application.job_id,
            status=ApplicationStatus(application.status),
            application_method=ApplicationMethod(application.application_method) if application.application_method else None,
            started_at=application.started_at,
            applied_at=application.applied_at,
            failure_reason=application.failure_reason,
            skip_reason=application.skip_reason,
            external_url=application.external_url,
            needs_attention=application.needs_attention,
            created_at=application.created_at,
            updated_at=application.updated_at
        )
