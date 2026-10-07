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
    is_employment_type_allowed,
    compute_profile_experience_years,
)

DEFAULT_IT_INDUSTRIES = (
    "IT Services & Consulting", "Software Product", "Internet",
    "Engineering - Software & QA", "IT & Information Security",
    "Data Science & Analytics", "Analytics & BI", "DevOps/Cloud",
)
DEFAULT_IT_KEYWORDS = (
    "software", "developer", "engineer", "data", "devops", "cloud",
    "qa", "test", "python", "sql", "backend", "frontend", "full stack",
    "machine learning", "analytics", "security",
)

# Allowed role families for deterministic title targeting
ALLOWED_ROLE_FAMILIES = {
    "data": ["data analyst", "data engineer", "data analytic"],
    "software": ["software engineer", "software developer", "developer", "software development engineer"],
    "devops": ["devops"],
    "python": ["python developer"],
}

# Explicitly rejected specializations (title-level exclusions)
UNWANTED_SPECIALIZATIONS = [
    "java", "php", ".net", "c#", "c++", "power platform",
    "platform engineer", "salesforce", "sap", "servicenow",
    "embedded", "firmware", "hardware", "electrical", "mechanical",
    "civil", "sales", "marketing", "hr", "operations",
]


def _contains_keyword(title: str, keywords: list[str]) -> bool:
    title_lower = (title or "").lower()
    return any(keyword.lower() in title_lower for keyword in keywords)


def title_matches_allowed_role(title: str) -> tuple[bool, str]:
    """
    Deterministic role/title targeting.

    Returns (allowed, reason) where:
    - allowed: True if title matches an allowed role family
    - reason: Explanation if rejected

    Rejects explicit unwanted specializations regardless of role family match.
    """
    title_lower = (title or "").lower()

    # First check for explicit unwanted specializations
    for unwanted in UNWANTED_SPECIALIZATIONS:
        if unwanted in title_lower:
            return False, f"Title contains unwanted specialization: {unwanted}"

    # Check if title matches allowed role families
    for family, keywords in ALLOWED_ROLE_FAMILIES.items():
        for keyword in keywords:
            if keyword in title_lower:
                return True, f"Title matches allowed role family: {family}"

    return False, "Title does not match any allowed role family"


def is_strict_it_job(job: Job, industries: list[str] | None = None,
                     keywords: list[str] | None = None) -> bool:
    allowed_industries = industries or list(DEFAULT_IT_INDUSTRIES)
    allowed_keywords = keywords or list(DEFAULT_IT_KEYWORDS)

    # Industry field is preferred but not mandatory if title contains IT keywords
    # If industry is present, it must match IT industries
    # If industry is missing, allow job if title contains IT keywords
    if job.industry:
        industry_lower = job.industry.strip().lower()
        if not any(value.lower() in industry_lower for value in allowed_industries):
            return False

    # Title must contain IT keyword (always required)
    return _contains_keyword(job.title, allowed_keywords)


def experience_passes_fresher_rule(job: Job, preference: JobPreference) -> tuple[bool, str]:
    text = job.experience
    title = (job.title or "").lower()
    title_exception = any(term in title for term in ("fresher", "trainee", "intern", "graduate"))
    exp_min, _ = extract_experience_years(text or "")
    if exp_min is None:
        if title_exception:
            return True, "Experience missing but title identifies an entry-level role"
        return False, "Experience is missing or unparseable"
    cap = preference.max_required_experience_years
    if exp_min > cap:
        return False, f"Experience required ({exp_min}y) exceeds cap ({cap}y)"
    return True, "Experience within fresher cap"


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

        # 4. Role/Title Targeting Check (deterministic before IT metadata)
        role_allowed, role_reason = title_matches_allowed_role(job.title)
        if not role_allowed:
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason=role_reason,
                skip_reason=SkipReason.OUTSIDE_SEARCH_SCOPE,
                failed_rules=["ROLE_TARGETING"],
            )
        matched_rules.append("ROLE_TARGETING_CHECK")

        # 5. Strict fresher experience and IT-only checks
        experience_ok, experience_reason = experience_passes_fresher_rule(job, preference)
        if not experience_ok:
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason=experience_reason,
                skip_reason=SkipReason.EXPERIENCE_TOO_HIGH,
                failed_rules=["EXPERIENCE"],
            )
        matched_rules.append("EXPERIENCE_CHECK")

        if not is_strict_it_job(job, preference.it_industry_allowlist, preference.it_keyword_list):
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason="Industry/department/role category is not an allowed IT value or title has no IT keyword.",
                skip_reason=SkipReason.OUTSIDE_SEARCH_SCOPE,
                failed_rules=["IT_SCOPE"],
            )
        matched_rules.append("IT_SCOPE_CHECK")

        # Salary Check: Treat salary_max == 0 (disclosed "Unpaid") as below minimum.
        # Salary metadata is available even when a job description is not.
        # salary NULL/None (undisclosed) is NOT rejected.
        if job.salary_max == 0:
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason="Salary is unpaid (disclosed 0 LPA).",
                skip_reason=SkipReason.SALARY_BELOW_MINIMUM,
                failed_rules=["SALARY"]
            )

        salary_lpa = extract_lowest_salary_lpa(job.salary)
        if salary_lpa is not None and preference.min_salary_lpa is not None:
            if salary_lpa < preference.min_salary_lpa:
                return MatchDecision(
                    decision=MatchDecisionEnum.SKIP,
                    reason=f"Salary ({salary_lpa} LPA) is below minimum {preference.min_salary_lpa} LPA.",
                    skip_reason=SkipReason.SALARY_BELOW_MINIMUM,
                    failed_rules=["SALARY"]
                )
        matched_rules.append("SALARY_CHECK")

        # Employment type is also structured metadata, independent of description text.
        if preference.employment_types and not is_employment_type_allowed(job.employment_type, preference.employment_types):
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
