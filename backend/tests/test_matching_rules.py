from backend.services.matching.normalizer import (
    normalize_location,
    has_overlapping_location,
    extract_lowest_salary_lpa,
    extract_experience_years,
    is_employment_type_allowed,
    compute_profile_experience_years,
)
from backend.services.matching.engine import title_matches_allowed_role

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


# ── Role Targeting Tests ─────────────────────────────────────────────────

def test_role_targeting_allowed_data_roles():
    """Data analyst roles should pass role targeting."""
    assert title_matches_allowed_role("Data Analyst Fresher")[0] is True
    assert title_matches_allowed_role("Junior Data Analyst")[0] is True
    assert title_matches_allowed_role("Associate Data Analyst")[0] is True

def test_role_targeting_allowed_software_roles():
    """Software engineer roles should pass role targeting."""
    assert title_matches_allowed_role("Software Engineer Fresher")[0] is True
    assert title_matches_allowed_role("Associate Software Engineer")[0] is True
    assert title_matches_allowed_role("Software Developer Fresher")[0] is True

def test_role_targeting_allowed_data_engineering_roles():
    """Data engineer roles should pass role targeting."""
    assert title_matches_allowed_role("Data Engineer Fresher")[0] is True
    assert title_matches_allowed_role("Junior Data Engineer")[0] is True
    assert title_matches_allowed_role("Associate Data Engineer")[0] is True

def test_role_targeting_allowed_devops_roles():
    """DevOps roles should pass role targeting."""
    assert title_matches_allowed_role("DevOps Trainee")[0] is True
    assert title_matches_allowed_role("Junior DevOps Engineer")[0] is True
    assert title_matches_allowed_role("DevOps Engineer Fresher")[0] is True

def test_role_targeting_allowed_python_roles():
    """Python developer roles should pass role targeting."""
    assert title_matches_allowed_role("Python Developer Fresher")[0] is True
    assert title_matches_allowed_role("Python Developer")[0] is True

def test_role_targeting_allowed_software_development_trainee():
    """Software Development Trainee should pass role targeting (E4-R10)."""
    assert title_matches_allowed_role("Software Development Trainee")[0] is True
    assert title_matches_allowed_role("Software Development")[0] is True

def test_role_targeting_allowed_data_science_roles():
    """Data science roles should pass role targeting (E4-R10)."""
    assert title_matches_allowed_role("Data Science Intern")[0] is True
    assert title_matches_allowed_role("Data Science Fresher")[0] is True
    assert title_matches_allowed_role("Data Science Engineer")[0] is True

def test_role_targeting_allowed_power_bi_roles():
    """Power BI roles should pass role targeting (E4-R10)."""
    assert title_matches_allowed_role("Power BI Internship")[0] is True
    assert title_matches_allowed_role("Power BI Developer")[0] is True
    assert title_matches_allowed_role("Power BI Analyst")[0] is True

def test_role_targeting_allowed_qa_roles():
    """QA roles should pass role targeting (E4-R10)."""
    assert title_matches_allowed_role("QA Engineer")[0] is True
    assert title_matches_allowed_role("QA Engineer Fresher")[0] is True
    assert title_matches_allowed_role("Quality Assurance Engineer")[0] is True
    assert title_matches_allowed_role("QA Tester")[0] is True

def test_role_targeting_allowed_sql_roles():
    """SQL developer roles should pass role targeting (E4-R10)."""
    assert title_matches_allowed_role("SQL Developer")[0] is True
    assert title_matches_allowed_role("SQL Developer Fresher")[0] is True

def test_role_targeting_reject_sql_server_administrator():
    """SQL Server Administrator should not pass solely because it contains SQL (E4-R10.1)."""
    allowed, reason = title_matches_allowed_role("SQL Server Administrator")
    assert allowed is False
    assert "does not match" in reason.lower()

def test_role_targeting_reject_java_specialization():
    """Java roles should be rejected even if they contain 'engineer'."""
    allowed, reason = title_matches_allowed_role("Java Fresher / Trainee")
    assert allowed is False
    assert "java" in reason.lower()

    allowed, reason = title_matches_allowed_role("Java Software Engineer")
    assert allowed is False
    assert "java" in reason.lower()

def test_role_targeting_reject_php_specialization():
    """PHP roles should be rejected."""
    allowed, reason = title_matches_allowed_role("PHP Developer")
    assert allowed is False
    assert "php" in reason.lower()

def test_role_targeting_reject_dotnet_specialization():
    """.NET roles should be rejected."""
    allowed, reason = title_matches_allowed_role(".NET Developer")
    assert allowed is False
    assert ".net" in reason.lower()

def test_role_targeting_reject_power_platform():
    """Power Platform roles should be rejected."""
    allowed, reason = title_matches_allowed_role("Power Platform Developer")
    assert allowed is False
    assert "power platform" in reason.lower()

def test_role_targeting_reject_platform_engineer():
    """Platform Engineer roles should be rejected."""
    allowed, reason = title_matches_allowed_role("Platform Engineer")
    assert allowed is False
    assert "platform engineer" in reason.lower()

def test_role_targeting_reject_electrical_engineer():
    """Electrical Engineer roles should be rejected."""
    allowed, reason = title_matches_allowed_role("Electrical Engineer")
    assert allowed is False
    assert "electrical" in reason.lower()

def test_role_targeting_reject_sales_roles():
    """Sales roles should be rejected."""
    allowed, reason = title_matches_allowed_role("Trainee Sales Executive")
    assert allowed is False
    assert "sales" in reason.lower()

def test_role_targeting_reject_hardware_firmware():
    """Hardware/firmware roles should be rejected."""
    assert title_matches_allowed_role("Embedded Software Engineer")[0] is False
    assert title_matches_allowed_role("Firmware Engineer")[0] is False
    assert title_matches_allowed_role("Hardware Engineer")[0] is False

def test_role_targeting_reject_generic_unrelated():
    """Generic titles without role family match should be rejected."""
    allowed, reason = title_matches_allowed_role("Management Trainee")
    assert allowed is False
    assert "does not match" in reason.lower()

    allowed, reason = title_matches_allowed_role("Quality Engineer")
    assert allowed is False
    assert "does not match" in reason.lower()

def test_role_targeting_case_insensitive():
    """Role matching should be case-insensitive."""
    assert title_matches_allowed_role("DATA ANALYST FRESHER")[0] is True
    assert title_matches_allowed_role("SOFTWARE ENGINEER FRESHER")[0] is True
    assert title_matches_allowed_role("JAVA DEVELOPER")[0] is False

def test_role_targeting_boundary_case_sales_mention_in_tech_role():
    """Technical role mentioning sales (e.g., pre-sales) should be rejected by unwanted specialization."""
    allowed, reason = title_matches_allowed_role("Pre-Sales Engineer")
    assert allowed is False
    assert "sales" in reason.lower()

def test_role_targeting_boundary_case_hardware_with_software():
    """Hardware role mentioning software should be rejected by unwanted specialization."""
    allowed, reason = title_matches_allowed_role("Hardware Software Engineer")
    assert allowed is False
    assert "hardware" in reason.lower()

def test_role_targeting_reject_pure_sales_roles():
    """Pure sales roles should be rejected (E4-R10 regression)."""
    assert title_matches_allowed_role("Sales Executive")[0] is False
    assert title_matches_allowed_role("Sales Manager")[0] is False
    assert title_matches_allowed_role("Business Development - Sales")[0] is False

def test_role_targeting_reject_mechanical_roles():
    """Mechanical roles should be rejected (E4-R10 regression)."""
    assert title_matches_allowed_role("Mechanical Engineer")[0] is False
    assert title_matches_allowed_role("Mechanical Design Engineer")[0] is False

def test_role_targeting_reject_manufacturing_roles():
    """Manufacturing roles should be rejected (E4-R10 regression)."""
    assert title_matches_allowed_role("Manufacturing Engineer")[0] is False
    assert title_matches_allowed_role("Production Engineer")[0] is False

def test_role_targeting_reject_hr_roles():
    """HR roles should be rejected (E4-R10 regression)."""
    assert title_matches_allowed_role("HR Manager")[0] is False
    assert title_matches_allowed_role("HR Executive")[0] is False

def test_role_targeting_reject_operations_roles():
    """Operations roles should be rejected (E4-R10 regression)."""
    assert title_matches_allowed_role("Operations Manager")[0] is False
    assert title_matches_allowed_role("Operations Executive")[0] is False


# ── IT Metadata Tests ───────────────────────────────────────────────────

def test_it_filter_with_valid_metadata():
    """Job with valid IT metadata should pass IT filter."""
    from backend.services.matching.engine import is_strict_it_job
    from backend.models.job import Job

    job = Job(
        title="Software Engineer Fresher",
        industry="IT Services & Consulting",
        department="Engineering - Software & QA",
        role_category="Software Engineer"
    )
    assert is_strict_it_job(job) is True

def test_it_filter_with_non_it_industry_even_with_it_role():
    """Job with non-IT industry should fail IT filter even with IT role category."""
    from backend.services.matching.engine import is_strict_it_job
    from backend.models.job import Job

    job = Job(
        title="Software Engineer Fresher",
        industry="Travel & Tourism",
        department="Engineering - Software & QA",
        role_category="Software Engineer"
    )
    assert is_strict_it_job(job) is False

def test_it_filter_with_missing_metadata():
    """Job with missing industry should pass IT filter if title has IT keywords."""
    from backend.services.matching.engine import is_strict_it_job
    from backend.models.job import Job

    job = Job(
        title="Software Engineer Fresher",
        industry=None,
        department="Engineering - Software & QA",
        role_category="Software Engineer"
    )
    # Should pass because title contains "software" and "engineer" keywords
    assert is_strict_it_job(job) is True

def test_it_filter_with_missing_metadata_no_it_keywords():
    """Job with missing industry and no IT keywords should fail IT filter."""
    from backend.services.matching.engine import is_strict_it_job
    from backend.models.job import Job

    job = Job(
        title="Marketing Manager",
        industry=None,
        department="Marketing",
        role_category="Marketing"
    )
    # Should fail because title has no IT keywords
    assert is_strict_it_job(job) is False

def test_it_filter_with_non_it_industry():
    """Job with non-IT industry should fail IT filter."""
    from backend.services.matching.engine import is_strict_it_job
    from backend.models.job import Job

    job = Job(
        title="Data Analyst Fresher",
        industry="Healthcare",
        department="Analytics",
        role_category="Data Analyst"
    )
    assert is_strict_it_job(job) is False

def test_it_filter_with_financial_services_industry():
    """Job with Financial Services industry should fail IT filter."""
    from backend.services.matching.engine import is_strict_it_job
    from backend.models.job import Job

    job = Job(
        title="Software Engineer Fresher",
        industry="Financial Services",
        department="Engineering - Software & QA",
        role_category="Software Engineer"
    )
    assert is_strict_it_job(job) is False


# ── Experience Rule Tests ───────────────────────────────────────────────

def test_experience_rule_reject_1_to_3():
    """1-3 years experience should be rejected for fresher profile."""
    from backend.services.matching.engine import experience_passes_fresher_rule
    from backend.models.job import Job
    from backend.models.matching import JobPreference

    job = Job(title="Software Engineer", experience="1-3 years")
    preference = JobPreference(max_required_experience_years=0)
    allowed, reason = experience_passes_fresher_rule(job, preference)
    assert allowed is False
    assert "exceeds cap" in reason.lower()

def test_experience_rule_reject_2_to_5():
    """2-5 years experience should be rejected for fresher profile."""
    from backend.services.matching.engine import experience_passes_fresher_rule
    from backend.models.job import Job
    from backend.models.matching import JobPreference

    job = Job(title="Software Engineer", experience="2-5 years")
    preference = JobPreference(max_required_experience_years=0)
    allowed, reason = experience_passes_fresher_rule(job, preference)
    assert allowed is False

def test_experience_rule_allow_0_to_1():
    """0-1 years experience should be allowed for fresher profile."""
    from backend.services.matching.engine import experience_passes_fresher_rule
    from backend.models.job import Job
    from backend.models.matching import JobPreference

    job = Job(title="Software Engineer Fresher", experience="0-1 years")
    preference = JobPreference(max_required_experience_years=0)
    allowed, reason = experience_passes_fresher_rule(job, preference)
    assert allowed is True

def test_experience_rule_allow_0_to_2():
    """0-2 years experience should be allowed for fresher profile."""
    from backend.services.matching.engine import experience_passes_fresher_rule
    from backend.models.job import Job
    from backend.models.matching import JobPreference

    job = Job(title="Software Engineer Fresher", experience="0-2 years")
    preference = JobPreference(max_required_experience_years=0)
    allowed, reason = experience_passes_fresher_rule(job, preference)
    assert allowed is True

def test_experience_rule_allow_fresher():
    """Fresher experience should be allowed."""
    from backend.services.matching.engine import experience_passes_fresher_rule
    from backend.models.job import Job
    from backend.models.matching import JobPreference

    job = Job(title="Software Engineer Fresher", experience="Fresher")
    preference = JobPreference(max_required_experience_years=0)
    allowed, reason = experience_passes_fresher_rule(job, preference)
    assert allowed is True

def test_experience_rule_reject_missing_without_fresher_title():
    """Missing experience without fresher keyword in title should be rejected."""
    from backend.services.matching.engine import experience_passes_fresher_rule
    from backend.models.job import Job
    from backend.models.matching import JobPreference

    job = Job(title="Marketing Manager", experience=None)
    preference = JobPreference(max_required_experience_years=0)
    allowed, reason = experience_passes_fresher_rule(job, preference)
    assert allowed is False
    assert "missing or unparseable" in reason.lower()

def test_experience_rule_allow_missing_with_fresher_title():
    """Missing experience with fresher keyword in title should be allowed."""
    from backend.services.matching.engine import experience_passes_fresher_rule
    from backend.models.job import Job
    from backend.models.matching import JobPreference

    job = Job(title="Software Engineer Fresher", experience=None)
    preference = JobPreference(max_required_experience_years=0)
    allowed, reason = experience_passes_fresher_rule(job, preference)
    assert allowed is True
    assert "entry-level" in reason.lower()


# ── E5-R7: job_titles-derived role targeting ──────────────────────────────

# The user's configured job_titles (source of truth for allowed roles).
E5R7_CONFIGURED_JOB_TITLES = [
    "Software Engineer Fresher", "Graduate Engineer Trainee",
    "Software Developer Trainee", "Associate Software Engineer",
    "Junior Data Analyst", "Data Analyst Fresher", "Data Engineer Fresher",
    "DevOps Trainee", "Python Developer Fresher", "QA Engineer Fresher",
    "SQL Developer Fresher",
]


def test_e5r7_graduate_engineer_trainee_allowed():
    """Graduate Engineer Trainee family must pass (previously starved)."""
    for title in (
        "Graduate Engineer Trainee",
        "Post Graduate Engineer Trainee",
        "Graduate Trainee (Cloud Test Engineering)",
        "InstaSafe Technologies u Graduate Engineer Trainee",
        "Graduate Engineer Trainee ( GET)",
    ):
        assert title_matches_allowed_role(title)[0] is True, title
        assert title_matches_allowed_role(title, E5R7_CONFIGURED_JOB_TITLES)[0] is True, title


def test_e5r7_data_analyst_allowed():
    """Data Analyst family must pass, with and without configured titles."""
    for title in ("Data Analyst", "Data Analyst (Fresher)", "Junior Data Analyst"):
        assert title_matches_allowed_role(title)[0] is True, title
        assert title_matches_allowed_role(title, E5R7_CONFIGURED_JOB_TITLES)[0] is True, title


def test_e5r7_ai_ml_cloud_elk_mis_allowed():
    """Curated fresher families (AI/ML, cloud, ELK, MIS) must pass."""
    for title in (
        "AI/ML Computational Science Associate",
        "AI Engineering Intern Generative Models",
        "ELK Engineer",
        "Mis Analyst , fresher",
        "Cloud Engineer",
    ):
        assert title_matches_allowed_role(title)[0] is True, title


def test_e5r7_irrelevant_titles_still_rejected():
    """Titles outside the configured interests must stay rejected."""
    for title in (
        "Associate Strategy & Transformation",
        "Quality control associate",
        "Graphic Designer",
        "HR Executive",
        "Sales Executive",
        "Management Trainee",
        "Quality Engineer",
        "Data Entry Operator",
    ):
        assert title_matches_allowed_role(title)[0] is False, title


def test_e5r7_unwanted_specializations_still_rejected_with_job_titles():
    """Even with configured job_titles, unwanted specializations are rejected."""
    for title in (
        "Java Developer",
        "Power Platform Developer",
        "Graduate Engineer Trainee - Sales",
        "PHP Developer",
    ):
        allowed, reason = title_matches_allowed_role(title, E5R7_CONFIGURED_JOB_TITLES)
        assert allowed is False, title
        assert (
            "unwanted specialization" in reason.lower()
            or "does not match" in reason.lower()
        ), reason


def test_e5r7_build_patterns_derives_cores_from_job_titles():
    """Configured titles contribute exact phrases plus modifier-stripped cores."""
    from backend.services.matching.engine import build_allowed_role_patterns

    patterns = build_allowed_role_patterns(["Data Analyst Fresher", "Graduate Engineer Trainee"])
    assert "data analyst fresher" in patterns
    assert "data analyst" in patterns          # fresher stripped
    assert "graduate engineer trainee" in patterns
    assert "graduate engineer" in patterns     # trainee stripped


def test_e5r7_job_titles_match_bare_core_variant():
    """A configured 'X Fresher' title also matches a bare 'X' job title."""
    allowed_titles = ["Data Analyst Fresher"]
    assert title_matches_allowed_role("Data Analyst", allowed_titles)[0] is True


def test_e5r7_it_scope_accepts_ai_ml_and_cloud_titles():
    """IT keyword expansion accepts AI/ML and cloud titles with no industry."""
    from backend.services.matching.engine import is_strict_it_job
    from backend.models.job import Job

    assert is_strict_it_job(Job(title="AI/ML Computational Science Associate")) is True
    assert is_strict_it_job(Job(title="ELK Engineer")) is True
    assert is_strict_it_job(Job(title="MIS Analyst")) is True
    assert is_strict_it_job(Job(title="Marketing Manager")) is False
