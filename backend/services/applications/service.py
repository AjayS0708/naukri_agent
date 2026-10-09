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
from backend.schemas.ai import JobAnalysis
from backend.services.matching.normalizer import (
    has_overlapping_location,
    extract_lowest_salary_lpa,
    extract_experience_years,
    is_employment_type_allowed,
    compute_profile_experience_years,
)
from backend.services.matching.engine import experience_passes_fresher_rule, is_strict_it_job
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
            application_method=create.application_method.value if create.application_method else None,
            is_dry_run=create.is_dry_run
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
        if update.confirmation_evidence is not None:
            application.confirmation_evidence = update.confirmation_evidence
        if update.external_url is not None:
            application.external_url = update.external_url
        if update.needs_attention is not None:
            application.needs_attention = update.needs_attention
        if update.is_dry_run is not None:
            application.is_dry_run = update.is_dry_run
        
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
        
        # 5. Strict fresher experience and IT-only scope
        experience_ok, experience_reason = experience_passes_fresher_rule(job, preference)
        if not experience_ok:
            return False, experience_reason
        if not is_strict_it_job(job, preference.it_industry_allowlist, preference.it_keyword_list):
            return False, "Industry/department/role category is not an allowed IT value or title has no IT keyword"
        
        # 6. Salary minimum rule: treat salary_max == 0 (disclosed "Unpaid") as below minimum
        # salary NULL/None (undisclosed) is NOT rejected
        if job.salary_max == 0:
            # Disclosed zero pay (unpaid) - always reject
            return False, "Salary is unpaid (disclosed 0 LPA)"

        if job.salary and preference.min_salary_lpa is not None:
            salary_lpa = extract_lowest_salary_lpa(job.salary)
            if salary_lpa is not None and salary_lpa < preference.min_salary_lpa:
                return False, f"Salary ({salary_lpa} LPA) below minimum ({preference.min_salary_lpa} LPA)"
        
        # 7. Employment type
        if job.employment_type and preference.employment_types:
            if not is_employment_type_allowed(job.employment_type, preference.employment_types):
                return False, f"Employment type '{job.employment_type}' not allowed"
        
        # 8. Job title/search scope — use the deterministic role-targeting
        # function (already applied by MatchEngine) as the canonical scope gate.
        # This avoids false rejections from strict substring mismatches between
        # configured search titles (e.g. "Python Developer Fresher") and actual
        # Naukri job titles (e.g. "Python Developer").  Unwanted specializations
        # are already caught by title_matches_allowed_role.
        if job.title:
            from backend.services.matching.engine import title_matches_allowed_role
            role_allowed, role_reason = title_matches_allowed_role(job.title)
            if not role_allowed:
                return False, f"Job title '{job.title}' not in configured search scope: {role_reason}"
        
        # 9. Gemini suspicious/fraud flag (only if analysis available).
        #
        # Gemini is advisory. Its subjective recommendation is never treated as
        # proof of fraud: a job that matches the user's saved preferences and
        # passes every deterministic hard rule above must not be rejected solely
        # because Gemini returned NEEDS_ATTENTION (weak fit / vague description).
        # Only the explicit `suspicious` fraud flag blocks here, and the
        # deterministic rules above remain authoritative.
        if job_analysis and job_analysis.suspicious:
            return False, "Job flagged as suspicious by AI analysis"

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
        reason: str = "External application redirect",
        is_dry_run: bool = False
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
            is_dry_run=is_dry_run,
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
            confirmation_evidence=application.confirmation_evidence,
            external_url=application.external_url,
            needs_attention=application.needs_attention,
            is_dry_run=application.is_dry_run,
            created_at=application.created_at,
            updated_at=application.updated_at
        )
