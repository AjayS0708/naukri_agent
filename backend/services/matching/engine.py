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
    # E5-R7: honor configured AI/ML, BI, and cloud families. Multi-word only
    # (no bare "ai"/"ml"/"bi") to avoid substring false positives such as
    # "ai" in "available" or "mis" in "permission".
    "artificial intelligence", "deep learning", "computer vision",
    "computational science", "nlp", "power bi", "business intelligence",
    "site reliability", "sre", "mis analyst",
)

# Built-in allowed role families (default fallback used when a caller does not
# supply the user's configured job_titles). Kept for backward compatibility; the
# runtime source of truth is preference.job_titles, which extends these
# families via build_allowed_role_patterns().
ALLOWED_ROLE_FAMILIES = {
    "data": ["data analyst", "data engineer", "data analytic", "data science", "power bi"],
    "software": ["software engineer", "software developer", "developer", "software development engineer", "software development"],
    "devops": ["devops"],
    "python": ["python developer"],
    "qa": ["qa", "quality assurance"],
    "sql": ["sql developer"],
}

# Curated fresher/entry-level expansions the user explicitly requested. These
# extend (never narrow) the built-in families so relevant configured titles
# (Graduate Engineer Trainee, Graduate Trainee, Apprentice, AI/ML, Cloud
# Engineering, BI, Data Science/Engineering) are not rejected by a stale
# hardcoded list. Matching stays phrase-based (no bare generic tokens) so
# unrelated titles are still rejected deterministically.
CURATED_ROLE_FAMILIES = {
    "graduate_trainee": [
        "graduate engineer trainee", "graduate trainee", "graduate engineer",
        "post graduate engineer", "campus hiring", "campus hire",
    ],
    "apprentice": ["apprentice", "apprenticeship"],
    "ai_ml": [
        "ai/ml", "ai engineer", "ai engineering", "machine learning",
        "deep learning", "artificial intelligence", "computational science",
        "computer vision", "nlp", "ml engineer", "ai and",
    ],
    "cloud": ["cloud engineer", "cloud", "site reliability", "sre"],
    "data_ext": [
        "elk", "mis analyst", "mis executive", "business analytics",
        "business intelligence", "bi analyst", "bi developer",
    ],
    "software_ext": [
        "solution engineer", "application developer", "full stack",
        "backend developer", "frontend developer",
    ],
}

# Explicitly rejected specializations (title-level exclusions)
UNWANTED_SPECIALIZATIONS = [
    "java", "php", ".net", "c#", "c++", "power platform",
    "platform engineer", "salesforce", "sap", "servicenow",
    "embedded", "firmware", "hardware", "electrical", "mechanical",
    "civil", "sales", "marketing", "hr", "operations",
    "production", "manufacturing", "automobile",
]

# Modifiers stripped from configured job_titles when deriving generic role
# cores (so "Data Analyst Fresher" also matches "Data Analyst").
_TITLE_MODIFIER_TOKENS = (
    "fresher", "junior", "senior", "associate", "trainee", "intern",
    "entry level", "entry-level",
)


def _normalize_title(title: str) -> str:
    return " ".join((title or "").lower().split())


def _job_title_cores(allowed_titles: Optional[list] = None) -> set[str]:
    """Exact normalized configured titles plus modifier-stripped cores."""
    cores: set[str] = set()
    for raw in allowed_titles or []:
        norm = _normalize_title(str(raw))
        if not norm:
            continue
        cores.add(norm)
        core = norm
        for modifier in _TITLE_MODIFIER_TOKENS:
            core = core.replace(modifier, " ")
        core = _normalize_title(core)
        if core:
            cores.add(core)
    return cores


def build_allowed_role_patterns(job_titles: Optional[list] = None) -> list[str]:
    """Merge built-in families, curated fresher expansions, and the user's
    configured job_titles into one de-duplicated, longest-first phrase list."""
    patterns: set[str] = set()
    for families in (ALLOWED_ROLE_FAMILIES, CURATED_ROLE_FAMILIES):
        for keywords in families.values():
            patterns.update(k for k in keywords if k)
    patterns.update(_job_title_cores(job_titles))
    return sorted(patterns, key=len, reverse=True)


def _contains_keyword(title: str, keywords: list[str]) -> bool:
    title_lower = (title or "").lower()
    return any(keyword.lower() in title_lower for keyword in keywords)


def title_matches_allowed_role(
    title: str, allowed_titles: Optional[list] = None
) -> tuple[bool, str]:
    """
    Deterministic role/title targeting.

    Returns (allowed, reason) where:
    - allowed: True if title matches an allowed role phrase
    - reason: Explanation if rejected

    Explicit unwanted specializations are rejected first regardless of family
    match. Otherwise the title must match one of the allowed role phrases from
    the built-in families, curated fresher expansions, and (when provided) the
    user's configured job_titles. The reason preserves the historical
    "Title matches allowed role family: <family>" format.
    """
    title_lower = _normalize_title(title)

    for unwanted in UNWANTED_SPECIALIZATIONS:
        if unwanted in title_lower:
            return False, f"Title contains unwanted specialization: {unwanted}"

    for families in (ALLOWED_ROLE_FAMILIES, CURATED_ROLE_FAMILIES):
        for family, keywords in families.items():
            for keyword in keywords:
                if keyword and keyword in title_lower:
                    return True, f"Title matches allowed role family: {family}"

    if allowed_titles:
        for core in _job_title_cores(allowed_titles):
            if core and core in title_lower:
                return True, "Title matches allowed role family: configured_title"

    return False, "Title does not match any allowed role family"


def is_strict_it_job(job: Job, industries: list[str] | None = None,
                     keywords: list[str] | None = None) -> bool:
    allowed_industries = industries or list(DEFAULT_IT_INDUSTRIES)
    allowed_keywords = keywords or list(DEFAULT_IT_KEYWORDS)

    # E5-R14: Explicitly reject non-IT role categories first.
    # This prevents manufacturing/production roles from passing just because
    # their title contains "Engineer", "Trainee", or "AI".
    # Handle role_category whether it's a clean string or list representation.
    non_it_role_categories = [
        "production", "manufacturing", "mechanical", "automobile",
        "civil", "electrical equipment", "industrial automation",
        "iron & steel", "auto components", "defence & aerospace",
        "electronic components / semiconductors", "engineering & construction"
    ]
    if job.role_category:
        role_cat_str = str(job.role_category).strip().lower()
        for non_it in non_it_role_categories:
            if non_it in role_cat_str:
                return False

    # E5-R13: Consider role_category and department in addition to industry.
    # IT roles exist in non-IT industries (e.g., Data Science in Pharma).
    # Allow job if ANY of industry, role_category, or department matches IT scope.
    # Use precise matching to avoid false positives (e.g., "Engineering" in "Manufacturing & Engineering").
    it_scope_match = False
    industry_match = False

    # Check industry - this is the strongest indicator
    if job.industry:
        industry_lower = job.industry.strip().lower()
        for industry in allowed_industries:
            # Require the full IT industry name to be present as a separate word/phrase
            # to avoid substring matches like "Engineering" matching "Manufacturing & Engineering"
            if f" {industry.lower()} " in f" {industry_lower} " or industry_lower.startswith(industry.lower()) or industry_lower.endswith(industry.lower()):
                it_scope_match = True
                industry_match = True
                break

    # Check role_category - only specific IT-related role categories
    # Allow "Data Science & Analytics", "DevOps/Cloud", "Software Product", etc.
    # Reject "Production, Manufacturing & Engineering", "Sales", etc.
    # Only check role_category if industry didn't match (to prevent false positives in non-IT industries)
    # E5-R14 continuation: Allow role_category match if industry is None/missing OR if title has IT keywords
    # This allows Data Science in Pharma (E5-R13) while preventing generic roles in non-IT industries
    if not it_scope_match and job.role_category:
        role_cat_str = str(job.role_category).strip().lower()
        # Specific IT role categories that are genuinely IT
        it_role_categories = [
            "data science & analytics", "analytics & bi", "devops/cloud",
            "it services & consulting", "software product", "engineering - software & qa",
            "it & information security", "quality assurance / testing"
        ]
        for it_cat in it_role_categories:
            if it_cat in role_cat_str:
                # If industry is None/missing, allow role_category match (Job 229 case)
                # If industry is non-IT, only allow if title has IT keywords (E5-R13 logic)
                if not job.industry:
                    it_scope_match = True
                    break
                elif _contains_keyword(job.title, allowed_keywords):
                    it_scope_match = True
                    break

    # Check department - only if industry didn't match
    # Only check department if industry didn't match (to prevent false positives in non-IT industries)
    # E5-R14 continuation: Only check department if industry is None/missing
    # Department check requires exact match with industry name (e.g., "Data Science & Analytics" in department)
    # Not substring match (e.g., "Analytics" should not match "Analytics & BI")
    if not it_scope_match and job.department and not job.industry:
        dept_lower = job.department.strip().lower()
        for industry in allowed_industries:
            # Require exact match, not substring match
            if dept_lower == industry.lower():
                it_scope_match = True
                break

    # If none of the structural fields match, require title to contain IT keywords
    # This handles jobs with missing or non-IT structural fields but IT-relevant titles
    if not it_scope_match:
        return _contains_keyword(job.title, allowed_keywords)

    # If structural field matched, require title to contain IT keywords
    # This prevents false positives from generic roles in IT companies
    # (e.g., "Manager" in an IT company when the role is actually HR or Sales)
    # E5-R14 continuation: Exception: if industry matched (strongest indicator),
    # we don't require title keywords. This allows roles like "Apprentice - Trainee"
    # in "Software Product" industry to pass.
    if industry_match:
        return True

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

    def _run_deterministic_checks(self, job: Job, profile: Profile, preference: JobPreference) -> MatchDecision:
        """
        Shared deterministic hard filter logic.
        Returns a MatchDecision with decision=APPLY if all checks pass,
        or SKIP/NEEDS_ATTENTION if any check fails.
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

        # 2. Duplicate Detection
        duplicate = self._check_duplicate(job)
        if duplicate:
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason="Job already processed or applied to.",
                skip_reason=SkipReason.DUPLICATE_JOB,
                failed_rules=["DUPLICATE_CHECK"]
            )
        matched_rules.append("DUPLICATE_CHECK")

        # 3. Role/Title Targeting Check
        role_allowed, role_reason = title_matches_allowed_role(
            job.title, getattr(preference, "job_titles", None)
        )
        if not role_allowed:
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason=role_reason,
                skip_reason=SkipReason.OUTSIDE_SEARCH_SCOPE,
                failed_rules=["ROLE_TARGETING"],
            )
        matched_rules.append("ROLE_TARGETING_CHECK")

        # 4. Strict fresher experience and IT-only checks
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

        # Salary Check
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

        # Employment type check
        if preference.employment_types and not is_employment_type_allowed(job.employment_type, preference.employment_types):
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason="Employment type not allowed.",
                skip_reason=SkipReason.EMPLOYMENT_TYPE_NOT_ALLOWED,
                failed_rules=["EMPLOYMENT_TYPE"]
            )
        matched_rules.append("EMPLOYMENT_TYPE_CHECK")

        # All deterministic checks passed
        return MatchDecision(
            decision=MatchDecisionEnum.APPLY,
            reason="All deterministic checks passed.",
            skip_reason=None,
            matched_rules=matched_rules,
            failed_rules=failed_rules,
            warnings=warnings,
            match_score=50  # Default score, will be refined by Gemini
        )

    def evaluate_job_deterministic(self, job: Job, profile: Profile, preference: JobPreference) -> MatchDecision:
        """
        Runs deterministic hard filters only. Does NOT call Gemini.
        Returns a MatchDecision with decision=APPLY if all deterministic checks pass,
        or SKIP/NEEDS_ATTENTION if any deterministic check fails.
        This is used for bounded candidate selection before invoking Gemini.
        """
        decision = self._run_deterministic_checks(job, profile, preference)
        if decision.decision == MatchDecisionEnum.APPLY:
            # Update reason to indicate readiness for Gemini evaluation
            decision.reason = "All deterministic checks passed. Ready for Gemini evaluation."
        return decision

    def evaluate_job(self, job: Job, profile: Profile, preference: JobPreference) -> MatchDecision:
        """
        Runs deterministic hard filters. If they pass, delegates to Gemini.
        Returns the final strict MatchDecision.
        """
        # Run shared deterministic checks
        decision = self._run_deterministic_checks(job, profile, preference)

        # If deterministic checks failed, return immediately
        if decision.decision != MatchDecisionEnum.APPLY:
            return decision

        # All deterministic checks passed - now call Gemini
        job_context = f"Title: {job.title}\nCompany: {job.company}\nDescription: {job.description or ''}"
        profile_context = json.dumps(profile.data, default=str)

        analysis: Optional[JobAnalysis] = self.ai.analyze_job(job_context, profile_context)
        if not analysis:
            return MatchDecision(
                decision=MatchDecisionEnum.NEEDS_ATTENTION,
                reason="Failed to analyze job via AI engine.",
                skip_reason=SkipReason.UNKNOWN,
                matched_rules=decision.matched_rules,
                failed_rules=decision.failed_rules,
                warnings=["AI_ANALYSIS_FAILED"]
            )

        # Apply final AI result to strict Pydantic Decision
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
            matched_rules=decision.matched_rules,
            failed_rules=decision.failed_rules,
            warnings=decision.warnings,
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
