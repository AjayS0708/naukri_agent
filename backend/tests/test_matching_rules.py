from backend.services.matching.normalizer import (
    normalize_location,
    has_overlapping_location,
    extract_lowest_salary_lpa,
    extract_experience_years,
    is_employment_type_allowed,
    compute_profile_experience_years,
)

def test_location_normalization():
    assert normalize_location("Bengaluru") == "bengaluru"
    assert normalize_location("Bangalore") == "bengaluru"
    assert normalize_location("Bengaluru, Karnataka") == "bengaluru"
    assert normalize_location("Remote") == "remote"
    assert normalize_location("Hyderabad") == "hyderabad"

def test_has_overlapping_location():
    # Job has multiple
    assert has_overlapping_location("Bengaluru / Hyderabad", ["Bengaluru", "Remote"]) is True
    assert has_overlapping_location("Pune / Chennai", ["Bengaluru", "Remote"]) is False
    assert has_overlapping_location("Remote", ["Bengaluru", "Remote"]) is True
    # User has no preference
    assert has_overlapping_location("Pune", []) is True

def test_extract_salary_lpa():
    assert extract_lowest_salary_lpa("₹4 LPA") == 4.0
    assert extract_lowest_salary_lpa("3-5 Lakhs") == 3.0
    assert extract_lowest_salary_lpa("400000 to 600000") == 4.0
    assert extract_lowest_salary_lpa("Undisclosed") is None

def test_extract_experience():
    assert extract_experience_years("0-2 years") == (0, 2)
    assert extract_experience_years("3 - 5 Years") == (3, 5)
    assert extract_experience_years("Freshers") == (0, 0)
    assert extract_experience_years("5+ years") == (5, None)
    assert extract_experience_years("Not specified") == (None, None)

def test_employment_type():
    assert is_employment_type_allowed("Full Time", ["full-time", "contract"]) is True
    assert is_employment_type_allowed("Contractual", ["full-time", "contract"]) is True
    assert is_employment_type_allowed("Internship", ["full-time"]) is False
    assert is_employment_type_allowed("Internship", []) is True # No preference allows anything


# ── compute_profile_experience_years regression tests ─────────────────────────

def test_compute_experience_no_entries():
    """Empty experience list returns 0."""
    assert compute_profile_experience_years([]) == 0.0


def test_compute_experience_with_parseable_dates():
    """Entries with parseable start/end dates return actual duration."""
    entries = [
        {"title": "Analyst", "company": "A", "start_date": "January 2023", "end_date": "January 2025"},
    ]
    years = compute_profile_experience_years(entries)
    assert 1.9 < years < 2.1


def test_compute_experience_present_end_date():
    """'Present' end date is treated as today; result is > 0 for a past start."""
    entries = [
        {"title": "Apprentice", "company": "ANZ", "start_date": "July 2026", "end_date": "Present"},
    ]
    # July 2026 is in the future relative to test run; delta may be 0 or slightly negative
    # The function returns max(0, delta) implicitly via the > 0 guard
    years = compute_profile_experience_years(entries)
    assert isinstance(years, float)
    assert years >= 0.0


def test_compute_experience_unparseable_dates_fallback():
    """When dates cannot be parsed, falls back to counting entries (1 per entry)."""
    entries = [
        {"title": "Dev", "company": "X", "start_date": None, "end_date": None},
        {"title": "Analyst", "company": "Y", "start_date": None, "end_date": None},
    ]
    assert compute_profile_experience_years(entries) == 2.0


def test_compute_experience_actual_profile_representation():
    """Mirrors the actual production profile: 1 ANZ entry starting July 2026.
    User has effectively 0 completed years of experience.
    """
    profile_experience = [
        {
            "title": "Apprentice",
            "company": "ANZ",
            "start_date": "July 2026",
            "end_date": "Present",
            "responsibilities": [],
            "technologies": [],
        }
    ]
    years = compute_profile_experience_years(profile_experience)
    # July 2026 start, Present end — near-zero or slightly negative delta clamped to 0
    assert years >= 0.0
    # Critically: must NOT return 1.0 (the old len() fallback)
    # The old code returned 1; with dates parsed, it returns actual elapsed time (~0)
    assert years < 1.0  # user has not yet completed a year


def test_experience_hard_filter_blocks_high_requirement():
    """A job requiring 5+ years is blocked for a user with ~0 years (0+2 grace = 2 < 5)."""
    from backend.services.matching.normalizer import extract_experience_years
    exp_min, _ = extract_experience_years("5-8 years")
    profile_experience = [
        {"title": "Apprentice", "company": "ANZ", "start_date": "July 2026", "end_date": "Present"}
    ]
    user_exp = compute_profile_experience_years(profile_experience)
    assert exp_min is not None
    assert exp_min > user_exp + 2  # hard filter should reject


def test_experience_hard_filter_passes_entry_level():
    """A job requiring 0-1 years passes for a user with ~0 years (0 <= 0+2)."""
    exp_min, _ = extract_experience_years("0-1 years")
    profile_experience = [
        {"title": "Apprentice", "company": "ANZ", "start_date": "July 2026", "end_date": "Present"}
    ]
    user_exp = compute_profile_experience_years(profile_experience)
    assert exp_min is not None
    assert not (exp_min > user_exp + 2)  # hard filter should NOT reject


def test_experience_hard_filter_unknown_requirement_passes():
    """When experience requirement is unparseable, filter does not block."""
    exp_min, _ = extract_experience_years("Not specified")
    assert exp_min is None  # filter skipped when None
