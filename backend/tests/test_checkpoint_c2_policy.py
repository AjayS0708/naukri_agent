import pytest

from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.services.matching.engine import (
    experience_passes_fresher_rule,
    is_strict_it_job,
)


@pytest.fixture
def preference():
    return JobPreference(max_required_experience_years=0)


@pytest.mark.parametrize("experience", ["5-8 Yrs", "2-5 Yrs", "1-3 Yrs"])
def test_experience_above_zero_cap_is_skipped(preference, experience):
    job = Job(title="Software Engineer", experience=experience)
    assert experience_passes_fresher_rule(job, preference)[0] is False


@pytest.mark.parametrize("experience", ["0-1 Yrs", "0-2 Yrs", "Fresher"])
def test_fresher_experience_passes(preference, experience):
    job = Job(title="Software Engineer", experience=experience)
    assert experience_passes_fresher_rule(job, preference)[0] is True


def test_missing_experience_requires_entry_level_title(preference):
    assert experience_passes_fresher_rule(
        Job(title="Software Engineer", experience=None), preference
    )[0] is False
    assert experience_passes_fresher_rule(
        Job(title="Software Trainee", experience=None), preference
    )[0] is True


def test_it_scope_is_deterministic():
    assert is_strict_it_job(Job(title="Data Analyst", industry="IT Services & Consulting"))
    assert not is_strict_it_job(Job(title="Data Analyst", industry="Hospital & Health Care"))
    assert not is_strict_it_job(Job(title="Data Analyst"))
