"""CHECKPOINT A3: Comprehensive tests for salary parsing and filter consistency."""

import pytest
from datetime import UTC, datetime
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.services.discovery.service import DiscoveryService
from backend.services.matching.engine import MatchEngine
from backend.services.applications.service import ApplicationService
from backend.services.matching.normalizer import parse_salary_to_range, is_employment_type_allowed
from backend.schemas.ai import JobAnalysis, AIRecommendation, JobQuality


@pytest.fixture
def test_session():
    engine = create_engine("sqlite:///:memory:")
    from backend.database.database import Base
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def profile_and_prefs(test_session):
    resume = Resume(stored_filename="test.pdf", original_filename="test.pdf", sha256="0" * 64, file_size=1000, text_length=500)
    test_session.add(resume)
    test_session.flush()
    profile = Profile(resume_id=resume.id, confirmed=True, data={"experience": [{"company": "Acme", "years": 5}]})
    test_session.add(profile)
    prefs = JobPreference(job_titles=["DevOps"], locations=["Bengaluru"], min_salary_lpa=4.0, employment_types=["Full Time", "Internship"])
    test_session.add(prefs)
    test_session.commit()
    return profile, prefs


class TestParseSalaryComprehensive:
    def test_unpaid(self): assert parse_salary_to_range("Unpaid") == (0.0, 0.0)
    def test_not_disclosed(self): assert parse_salary_to_range("Not disclosed") == (None, None)
    def test_3_5_lacs(self): assert parse_salary_to_range("3-5 Lacs PA") == (3.0, 5.0)
    def test_2_4_lacs(self): assert parse_salary_to_range("2-4 Lacs PA") == (2.0, 4.0)
    def test_50k_month(self): 
        m, n = parse_salary_to_range("50,000/month")
        assert abs(m - 6.0) < 0.1 and abs(n - 6.0) < 0.1
    def test_monthly_range(self):
        m, n = parse_salary_to_range("Rs 15,000 - 20,000 per month")
        assert abs(m - 1.8) < 0.1 and abs(n - 2.4) < 0.1
    def test_unpaid_pm(self): assert parse_salary_to_range("Unpaid P.M") == (0.0, 0.0)
    def test_empty(self): assert parse_salary_to_range("") == (None, None)
    def test_none(self): assert parse_salary_to_range(None) == (None, None)
    def test_unpaid_lower(self): assert parse_salary_to_range("unpaid") == (0.0, 0.0)
    def test_unpaid_upper(self): assert parse_salary_to_range("UNPAID") == (0.0, 0.0)
    def test_not_disclosed_case(self): assert parse_salary_to_range("Not Disclosed") == (None, None)
    def test_15k_pm(self):
        m, n = parse_salary_to_range("15,000 p.m.")
        assert abs(m - 1.8) < 0.1 and abs(n - 1.8) < 0.1
    def test_5_lpa(self): assert parse_salary_to_range("5 LPA") == (5.0, 5.0)
    def test_5_7_lpa(self): assert parse_salary_to_range("5-7 LPA") == (5.0, 7.0)
    def test_30k_50k_month(self):
        m, n = parse_salary_to_range("30,000-50,000/month")
        assert abs(m - 3.6) < 0.1 and abs(n - 6.0) < 0.1
    def test_15k_25k_pm(self):
        m, n = parse_salary_to_range("15,000 - 25,000 p.m.")
        assert abs(m - 1.8) < 0.1 and abs(n - 3.0) < 0.1


class TestEmploymentType:
    def test_none(self): assert is_employment_type_allowed(None, ["Full Time"]) is True
    def test_full_time_permanent(self): assert is_employment_type_allowed("Full Time, Permanent", ["Full Time"]) is True
    def test_internship(self): assert is_employment_type_allowed("Internship", ["Full Time", "Internship"]) is True
    def test_part_time(self): assert is_employment_type_allowed("Part Time", ["Full Time"]) is False
    def test_contract(self): assert is_employment_type_allowed("Contract", ["Full Time"]) is False


class TestEndToEndSalary:
    def test_unpaid_skip(self, test_session, profile_and_prefs):
        profile, prefs = profile_and_prefs
        class MA:
            platform_name = "naukri"
        svc = DiscoveryService.__new__(DiscoveryService)
        svc.adapter = MA()
        job = svc._build_job({"title": "E", "company": "A", "salary": "Unpaid", "url": "http://x/1"}, "t")
        assert job.salary_max == 0.0
        test_session.add(job)
        test_session.commit()
        mock_ai = MagicMock()
        eng = MatchEngine(test_session, ai_provider=mock_ai)
        dec = eng.evaluate_job(job, profile, prefs)
        assert dec.decision.value == "SKIP"
        svc2 = ApplicationService(test_session)
        allowed, _ = svc2.run_final_safety_gate(job, profile, prefs)
        assert not allowed
