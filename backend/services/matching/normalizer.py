import re
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


def extract_lowest_salary_lpa(salary_str: str) -> Optional[float]:
    """
    Extracts the minimum salary in LPA from a string.
    Example:
    "3-5 Lakhs" -> 3.0
    "₹ 400000 - 600000" -> 4.0
    "4 LPA" -> 4.0
    If salary is undisclosed or ambiguous, returns None.
    """
    if not salary_str:
        return None
    
    s = salary_str.lower().replace(",", "")
    
    # Handle "lakhs" or "lpa"
    # Example: 3-5 lakhs, 3 - 5 lpa, 3.5-4.5 lpa
    lpa_match = re.search(r'([\d\.]+)\s*(?:-|to)\s*([\d\.]+)\s*(?:lakhs?|lpa)', s)
    if lpa_match:
        try:
            return float(lpa_match.group(1))
        except ValueError:
            pass
        
    single_lpa_match = re.search(r'([\d\.]+)\s*(?:lakhs?|lpa)', s)
    if single_lpa_match:
        try:
            return float(single_lpa_match.group(1))
        except ValueError:
            pass
        
    # Handle absolute values (e.g. 400000)
    abs_match = re.search(r'(\d+)\s*(?:-|to)\s*(\d+)', s)
    if abs_match:
        try:
            val1 = float(abs_match.group(1))
            val2 = float(abs_match.group(2))
            min_val = min(val1, val2)
            if min_val >= 100000: # Assuming it's yearly if > 100k
                return min_val / 100000.0
        except ValueError:
            pass
            
    return None


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
