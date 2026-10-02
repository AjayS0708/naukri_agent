import re
from datetime import datetime
from typing import Optional


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


def parse_salary_to_range(salary_str: str) -> tuple[Optional[float], Optional[float]]:
    """
    Parses salary string to (salary_min, salary_max) in LPA.
    Handles: "Unpaid", "Not disclosed", "3-5 Lacs PA", "50,000/month", etc.
    Returns (min_lpa, max_lpa) or (None, None) for undisclosed.

    Special case: "Unpaid" (any case, with/without "P.M"/"per month") -> (0.0, 0.0)
    "Not disclosed"/empty -> (None, None)

    Monthly amounts are annualized: 50,000/month -> 50,000 * 12 / 100,000 = 6.0 LPA
    """
    if not salary_str or not isinstance(salary_str, str):
        return None, None

    s = salary_str.strip().lower().replace(",", "")

    # Check for undisclosed or empty
    if not s or "not disclos" in s:
        return None, None

    # Check for unpaid (including "Unpaid P.M", "Unpaid per month", etc.)
    if "unpaid" in s:
        return 0.0, 0.0

    # Handle "Lacs PA" or "Lacs" (common Naukri format)
    # Example: "3-5 Lacs PA" -> (3.0, 5.0)
    lacs_match = re.search(r'([\d\.]+)\s*(?:-|to)\s*([\d\.]+)\s*(?:lacs?|lakhs?)\s*(?:pa)?', s)
    if lacs_match:
        try:
            min_val = float(lacs_match.group(1))
            max_val = float(lacs_match.group(2))
            return min(min_val, max_val), max(min_val, max_val)
        except ValueError:
            pass

    # Handle single "Lacs PA" value
    single_lacs = re.search(r'([\d\.]+)\s*(?:lacs?|lakhs?)\s*(?:pa)?', s)
    if single_lacs:
        try:
            val = float(single_lacs.group(1))
            return val, val
        except ValueError:
            pass

    # Handle monthly ranges FIRST (before single monthly amounts)
    # Example: "Rs 15,000 - 20,000 per month" -> (1.8, 2.4)
    #          "30,000-50,000/month" -> (3.6, 6.0)
    monthly_range_match = re.search(r'([\d\.]+)\s*(?:-|to)\s*([\d\.]+)\s*(?:(?:/|per)\s*month|p\.?m\.?)', s)
    if monthly_range_match:
        try:
            min_monthly = float(monthly_range_match.group(1))
            max_monthly = float(monthly_range_match.group(2))
            # Annualize both: monthly * 12 / 100,000 = LPA
            min_lpa = (min_monthly * 12) / 100000.0
            max_lpa = (max_monthly * 12) / 100000.0
            return min(min_lpa, max_lpa), max(min_lpa, max_lpa)
        except ValueError:
            pass

    # Handle single monthly amounts ("/month", "per month", "p.m.", "pm")
    # Example: "50,000/month" -> annualize to 6.0 LPA, "15,000 p.m." -> 1.8 LPA
    monthly_match = re.search(r'([\d\.]+)\s*(?:(?:/|per)\s*month|p\.?m\.?)', s)
    if monthly_match:
        try:
            monthly_val = float(monthly_match.group(1))
            # Annualize: monthly * 12 / 100,000 = LPA
            annualized_lpa = (monthly_val * 12) / 100000.0
            return annualized_lpa, annualized_lpa
        except ValueError:
            pass

    # Handle "LPA" format ranges
    # Example: "5-7 LPA" -> (5.0, 7.0)
    lpa_range_match = re.search(r'([\d\.]+)\s*(?:-|to)\s*([\d\.]+)\s*(?:lakhs?|lpa)', s)
    if lpa_range_match:
        try:
            min_val = float(lpa_range_match.group(1))
            max_val = float(lpa_range_match.group(2))
            return min(min_val, max_val), max(min_val, max_val)
        except ValueError:
            pass

    # Handle single "LPA" value
    single_lpa_match = re.search(r'([\d\.]+)\s*(?:lakhs?|lpa)', s)
    if single_lpa_match:
        try:
            val = float(single_lpa_match.group(1))
            return val, val
        except ValueError:
            pass

    # Handle absolute values in rupees (e.g., "400000 - 600000" without currency)
    # Only if values are large enough (> 100k implies yearly)
    abs_match = re.search(r'([\d\.]+)\s*(?:-|to)\s*([\d\.]+)', s)
    if abs_match:
        try:
            val1 = float(abs_match.group(1))
            val2 = float(abs_match.group(2))
            # If both are large, assume yearly rupees
            if val1 >= 100000 and val2 >= 100000:
                min_val = (min(val1, val2)) / 100000.0
                max_val = (max(val1, val2)) / 100000.0
                return min_val, max_val
        except ValueError:
            pass

    # Handle single absolute value
    single_abs = re.search(r'^([\d\.]+)$', s)
    if single_abs:
        try:
            val = float(single_abs.group(1))
            if val >= 100000:
                lpa = val / 100000.0
                return lpa, lpa
        except ValueError:
            pass

    return None, None


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
    
    if "fresher" in exp:
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
