import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.job import Job
from backend.models.profile import Profile
from backend.models.matching import JobPreference
from backend.schemas.ai import JobAnalysis
from backend.schemas.matching import (
    MatchDecision, MatchDecisionEnum, SkipReason
)
from backend.services.ai_provider import AIProvider
from backend.services.gemini.provider import GeminiProvider
from backend.services.matching.normalizer import (
    has_overlapping_location,
    extract_lowest_salary_lpa,
    extract_experience_years,
    is_employment_type_allowed
)


class MatchEngine:
    def __init__(self, session: Session, ai_provider: Optional[AIProvider] = None):
        self.session = session
        self.ai = ai_provider or GeminiProvider()
        
    def evaluate_job(self, job: Job, profile: Profile, preference: JobPreference) -> MatchDecision:
        """
        Runs deterministic hard filters. If they pass, delegates to Gemini.
        Returns the final strict MatchDecision.
        """
        matched_rules = []
        failed_rules = []
        warnings = []
        
        # 1. Profile Status
        if not profile.confirmed:
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason="Profile is not confirmed by the user.",
                skip_reason=SkipReason.PROFILE_NOT_CONFIRMED,
                failed_rules=["PROFILE_CONFIRMATION"]
            )
            
        # 2. Location Hard Filter
        # Note: If no location provided in job.description or nowhere in job object, we ideally look for meta.
        # But Phase 1-3 doesn't have a separated "job_locations" field, we'd need to extract it or assume it's valid if undefined.
        # Let's assume description has location somewhere or metadata (in Phase 5). 
        # For this test, we will create a dummy logic that safely assumes true if no strict explicit field, 
        # but typically you parse it. We'll use a mocked location field if it existed, otherwise skip for now.
        # If job doesn't provide location directly in a field, we will skip hard filter natively and let AI catch it,
        # OR we wait till we update `Job` model to store location. Let's assume we do deterministic text search in description for now.
        if job.description:
            # Very basic placeholder logic for deterministic text since job lacks structured fields for Location/Salary yet.
            pass

        # 3. Duplicate Detection
        duplicate = self._check_duplicate(job)
        if duplicate:
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason="Job already processed or applied to.",
                skip_reason=SkipReason.DUPLICATE_JOB,
                failed_rules=["DUPLICATE_CHECK"]
            )
        matched_rules.append("DUPLICATE_CHECK")

        # 4. Try string extraction for deterministic checks
        if job.description:
            # Experience Check (Heuristic: 1 yr per job listed if not explicitly stored)
            exp_min, exp_max = extract_experience_years(job.description)
            if exp_min is not None:
                user_exp_years = len(profile.data.get("experience", [])) if isinstance(profile.data, dict) else len(getattr(profile.data, "experience", []))
                if exp_min > user_exp_years + 2: # Adding 2 years grace period since we approximate
                    return MatchDecision(
                        decision=MatchDecisionEnum.SKIP, 
                        reason=f"Experience required ({exp_min}y) is greater than user profile approx ({user_exp_years}y).", 
                        skip_reason=SkipReason.EXPERIENCE_TOO_HIGH,
                        failed_rules=["EXPERIENCE"]
                    )
            matched_rules.append("EXPERIENCE_CHECK")
            
            # Salary Check
            salary_lpa = extract_lowest_salary_lpa(job.description)
            if salary_lpa is not None and preference.min_salary_lpa is not None:
                if salary_lpa < preference.min_salary_lpa:
                    return MatchDecision(
                        decision=MatchDecisionEnum.SKIP,
                        reason=f"Salary ({salary_lpa} LPA) is below minimum {preference.min_salary_lpa} LPA.",
                        skip_reason=SkipReason.SALARY_BELOW_MINIMUM,
                        failed_rules=["SALARY"]
                    )
            matched_rules.append("SALARY_CHECK")
            
            # Employment Check
            if preference.employment_types and not is_employment_type_allowed(job.description, preference.employment_types):
                return MatchDecision(
                    decision=MatchDecisionEnum.SKIP,
                    reason="Employment type not allowed.",
                    skip_reason=SkipReason.EMPLOYMENT_TYPE_NOT_ALLOWED,
                    failed_rules=["EMPLOYMENT_TYPE"]
                )
            matched_rules.append("EMPLOYMENT_TYPE_CHECK")
        
        # 5. Gemini Semantic Check (Only runs because hard checks haven't failed)
        job_context = f"Title: {job.title}\nCompany: {job.company}\nDescription: {job.description or ''}"
        profile_context = json.dumps(profile.data, default=str)
        
        analysis: Optional[JobAnalysis] = self.ai.analyze_job(job_context, profile_context)
        if not analysis:
            return MatchDecision(
                decision=MatchDecisionEnum.NEEDS_ATTENTION,
                reason="Failed to analyze job via AI engine.",
                skip_reason=SkipReason.UNKNOWN,
                warnings=["AI_ANALYSIS_FAILED"]
            )
            
        # 6. Apply final AI result to strict Pydantic Decision
        decision_val = MatchDecisionEnum.APPLY
        skip_r = None
        
        if analysis.recommendation == "SKIP":
            decision_val = MatchDecisionEnum.SKIP
            skip_r = SkipReason.INSUFFICIENT_RELEVANCE
        elif analysis.recommendation == "NEEDS_ATTENTION":
            decision_val = MatchDecisionEnum.NEEDS_ATTENTION
            
        return MatchDecision(
            decision=decision_val,
            reason=analysis.short_reason,
            skip_reason=skip_r,
            matched_rules=matched_rules,
            failed_rules=failed_rules,
            warnings=warnings,
            match_score=analysis.match_score
        )

    def _check_duplicate(self, job: Job) -> bool:
        if not job.url:
            return False
        stmt = select(Job).where(Job.url == job.url)
        if job.id is not None:
            stmt = stmt.where(Job.id != job.id)
        res = self.session.execute(stmt).first()
        return res is not None
