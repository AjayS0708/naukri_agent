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
    extract_experience_years,
    is_employment_type_allowed,
    compute_profile_experience_years,
    evaluate_salary_gate,
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
    # E5-R24: a bare "Business Analyst" posting (jobs #392, #527) carries no
    # structural IT signal, so the title-keyword fallback had to reject it
    # even though the role is an explicit P1 target. Paired with
    # CURATED_ROLE_FAMILIES so the scope gate and the title gate agree.
    "business analyst",
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
    # E5-R22: the "apprentice" / "apprenticeship" family was removed — the
    # operator is already an apprentice and does not want another one; those
    # titles are now rejected via UNWANTED_SPECIALIZATIONS instead.
    "ai_ml": [
        "ai/ml", "ai engineer", "ai engineering", "machine learning",
        "deep learning", "artificial intelligence", "computational science",
        "computer vision", "nlp", "ml engineer", "ai and",
        # E5-R24: "data scientist" / "mlops" are named P2 targets of
        # interest_priority_rank but were missing here, so real postings
        # titled "Data Scientist" (job #231) and "MLOps Engineer" (job #336)
        # were rejected by the title gate before any other check ran.
        # "data science" alone does not substring-match "data scientist".
        "data scientist", "mlops",
    ],
    "cloud": ["cloud engineer", "cloud", "site reliability", "sre"],
    "data_ext": [
        "elk", "mis analyst", "mis executive", "business analytics",
        "business intelligence", "bi analyst", "bi developer",
        # E5-R24: named P1 target of interest_priority_rank. Reached only via
        # the unwanted-specialization scan before this (jobs #389-#393, #527).
        "business analyst",
    ],
    "software_ext": [
        "solution engineer", "application developer", "full stack",
        "backend developer", "frontend developer",
    ],
}

# Explicitly rejected specializations (title-level exclusions).
# E5-R22: added BPO / voice-call / customer-support / telemarketing /
# apprenticeship exclusions from the first controlled live run — those roles
# entered the candidate list because the title filter did not reject them.
UNWANTED_SPECIALIZATIONS = [
    "java", "php", ".net", "c#", "c++", "power platform",
    "platform engineer", "salesforce", "sap", "servicenow",
    "embedded", "firmware", "hardware", "electrical", "mechanical",
    "civil", "sales", "marketing", "hr", "operations",
    "production", "manufacturing", "automobile",
    # E5-R22: support / process roles and apprenticeship (Ajay is already
    # an apprentice and does not want another apprenticeship).
    "bpo", "voice process", "international voice", "voice call",
    "telecalling", "tele calling", "telemarketing",
    "customer support", "customer service",
    "call center", "call centre",
    "apprentice", "apprenticeship",
    # E5-R23: exclusions taken from the third controlled live run (run #82)
    # and the persisted irrelevant-job backlog. Bare "voice" catches the
    # variants E5-R22 missed ("International Voice", "Semi Voice Process",
    # "Non-Voice"). "fea"/"piping" caught the mechanical "Walk-in || Graduate
    # Trainee FEA and Piping Analysis" leak (job #535) at title level;
    # "fea" itself is deliberately NOT listed because it substring-matches
    # "feature"/"feasible" — that job is caught by "piping" and by the JD
    # responsibility phrases below. "tax" is likewise omitted ("tax" is a
    # substring of "syntax"); "taxation" and "accounts & finance" phrases
    # cover the actual postings.
    "voice",
    "non voice", "non-voice", "semi voice", "semi-voice",
    "voice process", "voice process executive",
    "customer care", "customer success", "customer executive",
    "customer officer", "customer relation", "customer relations",
    "customer handling",
    "piping", "ansys", "harness",
    "data entry", "back office",
    "operation executive", "operations executive",
    "accounts", "accounting", "finance", "payroll", "taxation",
    "recruiter", "recruitment",
    "graphic designer", "ui/ux", "ux designer",
    "field executive", "field sales", "field marketing",
    "jewels", "retail store",
    "procurement", "purchase executive",
    "front office", "receptionist",
    "technical support", "tech support", "helpdesk", "help desk",
]

# Modifiers stripped from configured job_titles when deriving generic role
# cores (so "Data Analyst Fresher" also matches "Data Analyst").
_TITLE_MODIFIER_TOKENS = (
    "fresher", "junior", "senior", "associate", "trainee", "intern",
    "entry level", "entry-level",
)

# ── E5-R17: irrelevant-role rejection (shared, deterministic) ──────────────
#
# Title matching alone cannot tell what a job actually is: a voice-process /
# L1 support opening titled "Associate Software Engineer" satisfies every
# title rule and used to reach the AI and application queue. These phrases
# are matched against the JD's responsibilities, and role_category /
# department are matched as role *scope*, so a Sales or Manufacturing posting
# is rejected even when its title sounds technical.

EXCLUDED_ROLE_SCOPE_PHRASES = (
    "sales", "business development", "marketing", "human resource",
    "production", "manufacturing", "customer success",
    "customer support", "customer service", "customer care",
    "customer relations",
    "service & operations", "service and operations", "bpo", "voice",
    # E5-R23: mechanical / civil / electrical engineering departments and
    # research scopes that leaked through as "Research & Development" on
    # the FEA / piping walk-in posting (job #535). "research & development"
    # itself is NOT excluded (software / data R&D roles are in scope).
    "mechanical", "civil", "electrical",
)

# Responsibility phrases identifying the described work as an excluded role.
# A job is rejected on these only when at least
# MIN_EXCLUDED_RESPONSIBILITY_HITS distinct phrases match, so an IT JD that
# merely mentions "lead generation" (a data pipeline) or "ticketing" (an ITSM
# tool) is not swept away by a single loose phrase.
EXCLUDED_RESPONSIBILITY_PHRASES = (
    # sales / business development
    "cold calling", "telecalling", "tele calling", "telesales",
    "field sales", "inside sales", "door to door", "door-to-door",
    "walk-in", "walk in customer", "sales target", "monthly target",
    "achieving target", "closing deal", "sales pitch", "channel sales",
    "pre-sales", "presales", "business target", "revenue target",
    "canvassing", "lead generation",
    # voice / BPO / customer support
    "voice process", "inbound call", "outbound call", "call centre",
    "call center", "helpdesk", "help desk", "l1 support",
    "l1 technical support", "customer handling", "bpo",
    "international voice", "voice call", "telemarketing",
    "customer support", "customer service", "tech support",
    # manufacturing / production
    "assembly line", "shop floor", "production line", "production floor",
    "manufacturing plant", "automotive component",
    # E5-R23: mechanical / civil / piping / FEA engineering domains (job #535
    # "Walk-in || Graduate Trainee FEA and Piping Analysis"). These appear
    # only in true mechanical/civil JDs, never in the user's data / software
    # / BI target roles, so they count toward the two-hit threshold (a lone
    # "manufacturing data" mention in a data JD stays safe).
    "mechanical engineering", "civil engineering", "electrical engineering",
    "piping analysis", "ansys", "caesar ii", "fea and piping",
    "harness design", "cad design", "autocad", "solidworks",
    # E5-R23: finance / accounts / payroll / recruitment processing work.
    "accounts payable", "accounts receivable", "journal entry",
    "gst filing", "income tax", "payroll processing",
    "sourcing candidates", "resume screening", "campus recruitment",
    # E5-R23: data-entry / back-office / merchandising process work.
    "data entry", "back office", "merchandising", "stock replenishment",
    "billing process", "invoice processing",
)
MIN_EXCLUDED_RESPONSIBILITY_HITS = 2

# E5-R22: phrases that unambiguously identify an excluded process / support
# role — a single hit in the JD is enough to reject regardless of the
# MIN_EXCLUDED_RESPONSIBILITY_HITS threshold, because these never appear in
# genuine engineering or analytics work. Added after the first controlled
# live run leaked short-JD BPO / voice / customer-support postings through
# the two-hit threshold.
STRONG_EXCLUDED_RESPONSIBILITY_PHRASES = (
    "voice process", "international voice", "bpo",
    "telemarketing", "telecalling", "tele calling",
    "call centre", "call center",
    "customer support", "customer service",
    # E5-R23: unambiguous process phrases from run #82 and the persisted
    # backlog (non-voice / semi-voice call-centre variants, customer-care
    # desks, domain tools of the FEA/piping leak). Walk-in drives are NOT
    # blanket-rejected here — only when the actual position is an excluded
    # role, which the title-level phrases above already catch (e.g.
    # "Walk-in || Customer Service Officer" → "customer service").
    "non voice process", "non-voice process", "semi voice process",
    "semi-voice process", "voice support", "customer care",
    "ansys", "caesar ii", "piping analysis",
    "data entry", "back office", "invoice processing",
    "payroll processing", "gst filing", "resume screening",
)

# Technical work signals used only to rescue a job whose structural scope
# looks non-technical (e.g. a Data Analyst posting filed under
# "Sales & Business Development"): if the JD describes genuine engineering or
# analytics work, the role scope alone must not reject it.
TECHNICAL_RESPONSIBILITY_SIGNALS = (
    "python", "sql", "java", "javascript", "typescript", "react", "angular",
    "django", "flask", "aws", "azure", "gcp", "docker", "kubernetes",
    "etl", "data pipeline", "power bi", "tableau", "pandas", "numpy",
    "machine learning", "rest api", "git", "ci/cd", "analytics",
    "dashboard", "reporting", "software development", "programming",
    "html", "css", "c#", ".net", "scala", "spark", "airflow", "snowflake",
    "dbt", "linux", " api", "data analysis", "data quality", "data cleaning",
    "excel", "google sheets", "pivot table", "vlook", "tally",
    "spreadsheet", "vba",
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


def _unwanted_title_reason(title: str) -> Optional[str]:
    """First explicitly rejected specialization found in the title, else None."""
    title_lower = _normalize_title(title)
    for unwanted in UNWANTED_SPECIALIZATIONS:
        if unwanted in title_lower:
            return f"Title contains unwanted specialization: {unwanted}"
    return None


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

    unwanted_reason = _unwanted_title_reason(title)
    if unwanted_reason:
        return False, unwanted_reason

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


def _excluded_responsibility_hits(text: Optional[str]) -> list[str]:
    text_lower = (text or "").lower()
    return [phrase for phrase in EXCLUDED_RESPONSIBILITY_PHRASES if phrase in text_lower]


def _strong_excluded_responsibility_hits(text: Optional[str]) -> list[str]:
    """E5-R22: single-hit unambiguous exclusions (voice/BPO/support/process)."""
    text_lower = (text or "").lower()
    return [
        phrase
        for phrase in STRONG_EXCLUDED_RESPONSIBILITY_PHRASES
        if phrase in text_lower
    ]


def has_technical_responsibilities(text: Optional[str]) -> bool:
    """True when the JD text shows genuine engineering/analytics work."""
    text_lower = (text or "").lower()
    return any(signal in text_lower for signal in TECHNICAL_RESPONSIBILITY_SIGNALS)


def _excluded_scope_reason(
    role_category: Optional[str], department: Optional[str]
) -> Optional[str]:
    for value, label in ((role_category, "Role category"), (department, "Department")):
        if not value:
            continue
        value_lower = str(value).strip().lower()
        for phrase in EXCLUDED_ROLE_SCOPE_PHRASES:
            if phrase in value_lower:
                return (
                    f"{label} '{value}' is outside the preferred technical "
                    f"scope (matched excluded scope: {phrase})"
                )
    return None


def irrelevant_role_reason(
    title: Optional[str] = None,
    role_category: Optional[str] = None,
    department: Optional[str] = None,
    description: Optional[str] = None,
    allowed_titles: Optional[list] = None,
) -> Optional[str]:
    """
    E5-R17 shared irrelevant-role rejection.

    Returns None when the job is not known to be irrelevant, otherwise a
    human-readable reason. Checks, in order:
      1. title unwanted specializations (sales, hr, production, ...),
      2. responsibilities in the JD describing an excluded role (requires
         >= MIN_EXCLUDED_RESPONSIBILITY_HITS distinct phrases so one loose
         mention in an otherwise technical JD does not reject),
      3. structural role scope (role_category / department): rejected as soon
         as the JD shows even one excluded responsibility, and otherwise
         rejected unless the JD shows genuine technical work *and* the title
         itself targets an allowed role family (keeps a Data Analyst post
         filed under a non-technical department, drops everything else).

    Never rejects purely on a missing field: absent metadata simply carries
    no signal here.
    """
    unwanted_reason = _unwanted_title_reason(title)
    if unwanted_reason:
        return unwanted_reason

    # E5-R22: unambiguous process/support phrases reject on a single hit
    # (short BPO / voice / customer-support JDs used to slip past the
    # two-hit threshold and enter the candidate list).
    strong_hits = sorted(set(_strong_excluded_responsibility_hits(description)))
    if strong_hits:
        return (
            "Job responsibilities describe an excluded role rather than a "
            f"preferred technical role (matched: {', '.join(strong_hits)})"
        )

    hits = sorted(set(_excluded_responsibility_hits(description)))
    if len(hits) >= MIN_EXCLUDED_RESPONSIBILITY_HITS:
        return (
            "Job responsibilities describe an excluded role rather than a "
            f"preferred technical role (matched: {', '.join(hits)})"
        )

    scope_reason = _excluded_scope_reason(role_category, department)
    if scope_reason:
        if hits:
            return scope_reason
        if (
            description
            and has_technical_responsibilities(description)
            and title_matches_allowed_role(title, allowed_titles)[0]
        ):
            return None
        return scope_reason

    return None


def job_relevance_check(
    title: Optional[str],
    allowed_titles: Optional[list] = None,
    role_category: Optional[str] = None,
    department: Optional[str] = None,
    description: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Canonical relevance gate: shared irrelevant-role rejection first, then
    the configured title/role-family targeting. Used by MatchEngine's
    deterministic checks, the final application safety gate, and discovery.
    """
    reason = irrelevant_role_reason(
        title,
        role_category=role_category,
        department=department,
        description=description,
        allowed_titles=allowed_titles,
    )
    if reason:
        return False, reason
    return title_matches_allowed_role(title, allowed_titles)


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

        # 3. Role relevance: title targeting plus actual role scope and
        # responsibilities (E5-R17). A technical-sounding title over an
        # excluded JD is rejected here before any AI evaluation.
        role_allowed, role_reason = job_relevance_check(
            job.title,
            getattr(preference, "job_titles", None),
            role_category=job.role_category,
            department=job.department,
            description=job.description,
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

        # Salary Check (E5-R25: shared gate — unpaid and disclosed-below-min
        # reject; missing/undisclosed/ambiguous salary never rejects).
        salary_ok, salary_reason = evaluate_salary_gate(
            job.salary, job.salary_max, preference.min_salary_lpa
        )
        if not salary_ok:
            return MatchDecision(
                decision=MatchDecisionEnum.SKIP,
                reason=salary_reason or "Salary does not meet the minimum preference.",
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

        # Location check (E5-R17 parity with the final safety gate): the job
        # must sit in one of the configured locations (Bengaluru / Remote).
        allowed_locations = getattr(preference, "locations", None)
        if job.location and allowed_locations:
            if not has_overlapping_location(job.location, allowed_locations):
                return MatchDecision(
                    decision=MatchDecisionEnum.SKIP,
                    reason=f"Location '{job.location}' is not in the allowed locations.",
                    skip_reason=SkipReason.LOCATION_NOT_ALLOWED,
                    failed_rules=["LOCATION"],
                )
        matched_rules.append("LOCATION_CHECK")

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
