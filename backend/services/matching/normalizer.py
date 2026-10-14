import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


def normalize_naukri_url_for_comparison(url: Optional[str]) -> Optional[str]:
    """
    Safe normalization of equivalent URL forms for reconciliation matching.

    E5-R23: relocated here (from backend/services/applications/service.py,
    which re-exports it for backward compatibility) so the discovery
    deduplicator can use the same canonical form without importing the
    heavy applications package.

    Trims whitespace, lowercases the host, treats http/https as equivalent,
    drops the fragment and default ports, and strips a trailing slash from
    the path. Returns None when the URL is missing or unparseable so callers
    treat the row as ambiguous rather than matching it.
    """
    if not url or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        if not host:
            return None
        port = parts.port
        netloc = f"{host}:{port}" if port is not None and port not in (80, 443) else host
        path = parts.path.rstrip("/")
        return urlunsplit(("https", netloc, path, parts.query, ""))
    except ValueError:
        return None


def normalize_location(location: str) -> str:
    """
    Normalizes common variations of cities. 
    Bengaluru -> Bengaluru
    Bangalore -> Bengaluru
    Bengaluru, Karnataka -> Bengaluru
    """
    if not location:
        return ""
    
    loc = location.lower()
    
    # Bengaluru normalization
    if "bangalore" in loc or "bengaluru" in loc:
        return "bengaluru"
    
    if "remote" in loc:
        return "remote"
    
    # Simple cleanup, grab main part before comma
    loc = loc.split(",")[0].strip()
    return loc


def has_overlapping_location(job_locations_str: str, preferred_locations: list[str]) -> bool:
    """
    Checks if there's any intersection between job locations and user preferences.
    Example: 
      job_locations_str: "Bengaluru / Hyderabad / Pune"
      preferred_locations: ["Bengaluru", "Remote"]
      -> True
    """
    if not preferred_locations: # If no preferences, allow all
        return True
    if not job_locations_str: # If no location specified, do not automatically reject
        return True
    
    job_locs = [normalize_location(loc) for loc in re.split(r'[/,]', job_locations_str)]
    pref_locs = [normalize_location(loc) for loc in preferred_locations]
    
    # Check intersection
    return any(jl in pref_locs for jl in job_locs if jl)


# E5-R25: unit markers for the unit-aware salary parser. Detection runs on the
# lowercased original text (before comma stripping) so comma-formatted rupee
# amounts stay distinguishable from lacs-scale plain numbers. The abbreviated
# forms use a trailing (?!\w) instead of \b so trailing-dot spellings like
# "p.m." / "p.a." still match at end of string.
_SALARY_MONTHLY_MARKER = re.compile(r"(?:/|\bper\s*)\s*month\b|\bp\.?\s?m\.?(?!\w)", re.I)
_SALARY_ANNUAL_MARKER = re.compile(r"\bp\.?\s?a\.?(?!\w)|\bper\s*annum\b|\bpa\b|\byearly\b|\bannually\b", re.I)
_SALARY_LACS_MARKER = re.compile(r"\b(?:lacs?|lakhs?|lpa)\b", re.I)
# Numeric tokens: digits with optional Indian-style comma grouping and decimals.
_SALARY_NUMBER_TOKEN = re.compile(r"(\d[\d,]*(?:\.\d+)?)")


def _annualize_monthly(value: float) -> float:
    """Monthly rupees -> LPA (value * 12 / 100,000)."""
    return (value * 12) / 100000.0


def _rupees_to_lpa(value: float) -> float:
    """Annual rupees -> LPA (value / 100,000)."""
    return value / 100000.0


def _parse_salary_endpoint(
    raw_token: str,
    *,
    range_has_lacs: bool,
    range_has_monthly: bool,
    range_has_annual: bool,
) -> Optional[float]:
    """Convert one numeric salary endpoint to LPA, or None when ambiguous.

    Decision rules (E5-R25), auditable and order-stable:

    1. A token directly followed by lacs/lakh/lpa in the original text is an
       LPA value as written ("3 Lacs" -> 3.0).
    2. A comma-grouped or >=100000 token is a rupee amount:
       annual marker -> /1e5 ("50,000 PA" -> 0.5), monthly marker ->
       *12/1e5 ("50,000 per month" -> 6.0), no marker but >=100000 ->
       annual rupees (legacy "400000 to 600000" -> 4.0). A rupee-scale
       token inside a lacs-marked range still uses the range unit marker
       when present ("50,000-3 Lacs PA" -> left endpoint 0.5).
    3. A small comma-less token inherits the range unit: lacs marker ->
       LPA as written ("2-3 Lacs PA" -> 2.0), monthly marker -> annualized
       ("300/month" -> 0.036). With an annual marker only, a bare small
       number ("5 PA") is genuinely ambiguous and stays unknown.
    4. Anything else (bare small numbers with no unit context) is unknown;
       callers must treat unknown as "salary not disclosed", never as a
       confirmed below-minimum value.
    """
    has_comma = "," in raw_token
    try:
        value = float(raw_token.replace(",", ""))
    except ValueError:
        return None

    # Rule 1: rupee-scale or comma-grouped tokens are rupee amounts.
    if has_comma or value >= 100000:
        if range_has_monthly:
            return _annualize_monthly(value)
        if range_has_annual:
            return _rupees_to_lpa(value)
        if value >= 100000:
            return _rupees_to_lpa(value)
        return None

    # Rule 2: small comma-less tokens inherit the range unit.
    if range_has_lacs:
        return value
    if range_has_monthly:
        return _annualize_monthly(value)
    return None


def parse_salary_to_range(salary_str: str) -> tuple[Optional[float], Optional[float]]:
    """
    Parses salary string to (salary_min, salary_max) in LPA.
    Handles: "Unpaid", "Not disclosed", "3-5 Lacs PA", "50,000/month", etc.
    Returns (min_lpa, max_lpa) or (None, None) for undisclosed/ambiguous.

    Special case: "Unpaid" (any case, with/without "P.M"/"per month") -> (0.0, 0.0)
    "Not disclosed"/"Undisclosed"/empty -> (None, None)

    E5-R25: unit-aware endpoint parsing. Monthly amounts are annualized
    (50,000/month -> 6.0 LPA); annual rupee amounts are scaled to LPA
    (60,000-80,000 PA -> 0.6-0.8 LPA); mixed lacs/rupee ranges normalize each
    endpoint by its own unit ("50,000-3 Lacs PA" -> 0.5-3.0 LPA). Genuinely
    ambiguous strings (bare uncomma'd numbers with no unit, e.g. "50,000-80,000")
    return (None, None) so the salary gate continues consideration instead of
    inventing a confirmed value.
    """
    if not salary_str or not isinstance(salary_str, str):
        return None, None

    s = salary_str.strip().lower()

    # Check for undisclosed or empty
    if not s or "not disclos" in s or "undisclosed" in s:
        return None, None

    # Check for unpaid (including "Unpaid P.M", "Unpaid per month", etc.)
    if "unpaid" in s:
        return 0.0, 0.0

    # Unit markers are evaluated against the comma-preserving text so
    # "50,000" stays identifiable as a rupee amount.
    has_monthly = bool(_SALARY_MONTHLY_MARKER.search(s))
    has_annual = bool(_SALARY_ANNUAL_MARKER.search(s))
    has_lacs = bool(_SALARY_LACS_MARKER.search(s))

    tokens = _SALARY_NUMBER_TOKEN.findall(s)
    if not tokens:
        return None, None

    values: list[float] = []
    for token in tokens:
        # Direct lacs/lakh/lpa suffix on THIS token -> LPA as written.
        suffix_match = re.search(
            re.escape(token) + r"\s*(lacs?|lakhs?|lpa)\b", s
        )
        if suffix_match:
            try:
                values.append(float(token.replace(",", "")))
                continue
            except ValueError:
                pass
        endpoint = _parse_salary_endpoint(
            token,
            range_has_lacs=has_lacs,
            range_has_monthly=has_monthly,
            range_has_annual=has_annual,
        )
        if endpoint is None:
            # One unparseable endpoint in a multi-endpoint range makes the
            # range incomparable; a lone unknown token is undisclosed. The
            # single-known-endpoint case is handled after the loop only when
            # every token parsed, so an ambiguous partner never fabricates a
            # bound.
            return None, None
        values.append(endpoint)

    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    low = min(values)
    high = max(values)
    return low, high


def extract_lowest_salary_lpa(salary_str: str) -> Optional[float]:
    """
    Extracts the minimum salary in LPA from a string.
    Example:
    "3-5 Lakhs" -> 3.0
    "₹ 400000 - 600000" -> 4.0
    "4 LPA" -> 4.0
    If salary is undisclosed or ambiguous, returns None.
    """
    min_lpa, _ = parse_salary_to_range(salary_str)
    return min_lpa


def evaluate_salary_gate(
    salary_text: Optional[str],
    salary_max: Optional[float],
    min_salary_lpa: Optional[float],
) -> tuple[bool, Optional[str]]:
    """
    E5-R25: single source of truth for the disclosed-salary preference gate.

    Shared by the MatchEngine deterministic filter, the final application
    safety gate, decision-quality scoring, and the existing-job recovery stage
    so no two pipeline stages can disagree about the same job.

    Behavior:
    - Unpaid / disclosed 0 LPA -> rejected ("Salary is unpaid...").
    - Disclosed salary strictly below ``min_salary_lpa`` -> rejected.
    - Disclosed salary at/above the minimum -> allowed.
    - Missing, "Not disclosed", or genuinely ambiguous/malformed salary ->
      allowed (never treated as a confirmed below-minimum value).

    Returns ``(passed, reason)``; ``reason`` is None when passed.
    """
    # Unpaid safeguard: the normalized salary_max column is 0 for "Unpaid",
    # and a parsed 0.0 LPA floor is the same disclosure.
    parsed_low = extract_lowest_salary_lpa(salary_text) if salary_text else None
    if salary_max == 0 or parsed_low == 0.0:
        return False, "Salary is unpaid (disclosed 0 LPA)."

    if parsed_low is not None and min_salary_lpa is not None:
        if parsed_low < min_salary_lpa:
            return False, (
                f"Salary ({parsed_low} LPA) is below minimum {min_salary_lpa} LPA."
            )

    return True, None


def extract_experience_years(exp_str: str) -> tuple[Optional[int], Optional[int]]:
    """
    Extracts min and max experience requirement.
    "0-2 years" -> (0, 2)
    "Freshers" -> (0, 0)
    "3 - 5 Years" -> (3, 5)
    "5+ years" -> (5, None)
    Return None if unparseable.
    """
    if not exp_str:
        return None, None
        
    exp = exp_str.lower()
    
    if any(term in exp for term in ("fresher", "trainee", "intern", "graduate")):
        return 0, 0
        
    match_range = re.search(r'(\d+)\s*(?:-|to)\s*(\d+)\s*y', exp)
    if match_range:
        return int(match_range.group(1)), int(match_range.group(2))
        
    match_plus = re.search(r'(\d+)\s*\+\s*y', exp)
    if match_plus:
        return int(match_plus.group(1)), None
        
    match_single = re.search(r'(\d+)\s*y', exp)
    if match_single:
        return int(match_single.group(1)), int(match_single.group(1))
        
    return None, None


def normalize_employment_type(emp_type: str) -> str:
    if not emp_type:
        return ""
    emp = emp_type.lower()
    if "full time" in emp or "full-time" in emp:
        return "full-time"
    if "intern" in emp:
        return "internship"
    if "contract" in emp:
        return "contract"
    return emp


def is_employment_type_allowed(job_emp: str, allowed_emps: list[str]) -> bool:
    if not allowed_emps:
        return True
    if not job_emp:
        return True
        
    normalized_job = normalize_employment_type(job_emp)
    normalized_allowed = [normalize_employment_type(e) for e in allowed_emps]
    
    # If the normalized job type matches any allowed type
    for allowed in normalized_allowed:
        if allowed in normalized_job or normalized_job in allowed:
            return True
    return False


def compute_profile_experience_years(experience_list: list) -> float:
    """
    Compute total years of work experience from a list of Experience dicts/objects.

    For each entry, attempts to parse start_date and end_date (or 'Present').
    Falls back to counting entries (1 year each) when dates are unparseable.

    Returns total years as a float (0.0 if no experience).
    """
    if not experience_list:
        return 0.0

    _DATE_FORMATS = ["%B %Y", "%b %Y", "%Y-%m", "%Y/%m", "%m/%Y", "%Y"]

    def _parse_date(s: str) -> Optional[datetime]:
        if not s:
            return None
        s = s.strip()
        if s.lower() in ("present", "current", "now", "ongoing"):
            return datetime.now()
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    total_years = 0.0
    any_parsed = False

    for entry in experience_list:
        # Support both dict and object representations
        if isinstance(entry, dict):
            start_str = entry.get("start_date") or ""
            end_str = entry.get("end_date") or ""
        else:
            start_str = getattr(entry, "start_date", "") or ""
            end_str = getattr(entry, "end_date", "") or ""

        start = _parse_date(start_str)
        end = _parse_date(end_str)

        if start and end:
            delta_years = (end - start).days / 365.25
            if delta_years > 0:
                total_years += delta_years
            any_parsed = True
        elif start:
            # start known, end unknown — count as 1 year
            total_years += 1.0
            any_parsed = True

    # If no dates were parseable at all, fall back to entry count
    if not any_parsed:
        return float(len(experience_list))

    return total_years
