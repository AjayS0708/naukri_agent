from backend.services.matching.normalizer import (
    normalize_location,
    has_overlapping_location,
    extract_lowest_salary_lpa,
    extract_experience_years,
    is_employment_type_allowed
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
