"""E5-R30: .NET relevance consistency (shared gate, queue eligibility, badges).

Observed live inconsistency (evidence-backed records in the local database):

- Job #417 "Dot Net Developer" @ Intelliswift — displayed SKIPPED · ELIGIBLE.
  Its JD is C#/.NET/.NET Core/MVC/Web API/Blazor work under
  "Role Category: Software Development", with no excluded phrases.
- Job #422 "Dot Net Developer" @ Nxtwave Disruptive Technologies — displayed
  "Not relevant" with reason "... (matched: resume screening)". Its JD is the
  same kind of role (Required Skills: C#, OOP, .NET/.NET Core, ASP.NET Core,
  Web API, SQL, REST APIs; Role: Software Development - Other; Department:
  Engineering - Software & QA) and mentions "Resume Screening" exactly once,
  inside the *Selection Process* section that describes how the EMPLOYER
  screens candidates — not the employee's work.

Root causes fixed (backend/services/matching/engine.py):

1. "resume screening" was a single-hit STRONG exclusion, so one hiring-process
   mention nuked an otherwise in-scope software JD before title/category were
   considered. It stays in the two-hit weak list, so a real recruitment JD
   (which combines "sourcing candidates" / "campus recruitment" /
   "resume screening") is still rejected.
2. ".net" and "c#" were title-level UNWANTED specializations, so the same
   role's verdict depended on its spelling: "Dot Net Developer" passed via
   the software "developer" family while ".NET Developer" / "ASP.NET
   Developer" / "C# Developer" were title-banned (and job #278 "asp.net
   Developer" had actually been APPLIED historically). .NET/C# postings are
   now judged by responsibilities and scope like every other software role.

These tests reproduce the two actual records from their real data, cover
relevant synthetic .NET/ASP.NET/C# roles, prove unrelated .NET-titled roles
(mechanical work, recruiting, BPO) are still rejected, and assert that the
shared gate, the manual-queue eligibility verdicts, and the displayed reason
agree.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import pytest

from backend.database.database import Base
from backend.models.application import Application
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.schemas.application import ApplicationStatus
from backend.services.applications.protection import protected_job_ids
from backend.services.manual_apply.service import ManualApplyService
from backend.services.matching.engine import (
    EXCLUDED_RESPONSIBILITY_PHRASES,
    STRONG_EXCLUDED_RESPONSIBILITY_PHRASES,
    UNWANTED_SPECIALIZATIONS,
    job_relevance_check,
)

TEST_DATABASE_URL = "sqlite:///:memory:"

# Verbatim excerpts of the two actual database records (jobs #417 and #422).
JOB_417_DESCRIPTION = (
    "Job description \ufffd Strong proficiency in C# and .NET framework "
    "(including .NET Core, MVC, Web API) Solid understanding of "
    "object-oriented programming principles Design and build front-end "
    "applications using Blazor Familiarity with cloud platforms, especially "
    "AWS (EC2, S3, Lambda, etc.) Strong problem-solving and analytical "
    "skills Excellent communication and teamwork abilities Location is "
    "Bangalore Role: Full Stack Developer Industry Type: IT Services & "
    "Consulting Department: Engineering - Software & QA Employment Type: "
    "Full Time, Permanent Role Category: Software Development"
)
JOB_422_DESCRIPTION = (
    "Hiring for a client     Role: .NET Developer Location: Hyderabad | "
    "Work From Office Job Type: 1-Year Apprenticeship Stipend: 21,500/month "
    "CTC on Conversion: 4.5 LPA Working Days: 5 Days/Week Bond: No formal "
    "bond  Required Skills  C# OOP Concepts .NET / .NET Core ASP.NET Core / "
    "Web API SQL Basic REST APIs  Eligibility  Any educational background "
    "with relevant technical skills Any pass-out year Candidates from "
    "Hyderabad or nearby locations preferred Relevant projects, "
    "internships, or hands-on experience will be an advantage  Selection "
    "Process  Resume Screening Aptitude Test Technical Round 1 Technical "
    "Round 2 Managerial Round  Interview: Offline/Online Note: Candidates "
    "should be comfortable with Work From Office in Hyderabad and a 1-year "
    "apprenticeship with potential full-time conversion based on "
    "performance. The offline selection process may take one full day.     "
    "Role: Software Development - Other Industry Type: Education / Training "
    "Department: Engineering - Software & QA Employment Type: Full Time, "
    "Permanent Role Category: Software Development"
)

TECHNICAL_DOTNET_JD = (
    "Required Skills: C#, OOP Concepts, .NET / .NET Core, ASP.NET Core, "
    "Web API, SQL, REST APIs. Responsibilities: analyse, design and develop "
    "web applications; code review and unit testing. Role Category: "
    "Software Development. Department: Engineering - Software & QA."
)


@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = Session(autocommit=False, autoflush=False, bind=engine)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def confirmed_profile(db_session: Session):
    resume = Resume(
        stored_filename="test_resume.pdf",
        original_filename="resume.pdf",
        sha256="abc123",
        file_size=1000,
        text_length=5000,
        is_current=True,
    )
    db_session.add(resume)
    db_session.commit()
    profile = Profile(
        resume_id=resume.id,
        status="CONFIRMED",
        confirmed=True,
        data={"name": "Test User", "skills": ["Python", "SQL", "C#"], "location": "Bengaluru"},
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def job_preferences(db_session: Session):
    preferences = JobPreference(
        locations=["Bengaluru", "Remote"],
        job_titles=["Data Analyst", "Software Engineer"],
        employment_types=["Full-time"],
        min_salary_lpa=3.0,
        aggressiveness="BALANCED",
    )
    db_session.add(preferences)
    db_session.commit()
    db_session.refresh(preferences)
    return preferences


def _make_job(
    db_session: Session,
    index: int,
    *,
    title: str,
    description: str,
    role_category: str | None = "Engineering - Software & QA",
    department: str | None = "Engineering - Software & QA",
    application_mode: str | None = "NAUKRI_NATIVE",
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"dotnet{index}",
        url=f"https://www.naukri.com/dotnet-relevance-{index}",
        title=title,
        company=f"Company {index}",
        description=description,
        location="Bengaluru",
        salary="5-7 LPA",
        salary_max=7.0,
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
        role_category=role_category,
        department=department,
        application_mode=application_mode,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


class TestActualObservedRecords:
    """The two real .NET records, reproduced from their actual data."""

    def test_job_417_dot_net_developer_is_relevant(self) -> None:
        """Job #417 (Intelliswift): C#/.NET/.NET Core/MVC/Web API/Blazor work,
        Role Category Software Development, no excluded phrases — relevant."""
        allowed, reason = job_relevance_check(
            "Dot Net Developer",
            allowed_titles=["Data Analyst", "Software Engineer"],
            role_category="Engineering - Software & QA",
            department="Engineering - Software & QA",
            description=JOB_417_DESCRIPTION,
        )
        assert allowed is True, reason

    def test_job_422_selection_process_phrase_no_longer_rejects(self) -> None:
        """Job #422 (Nxtwave): the JD's Required Skills are C#, OOP,
        .NET/.NET Core, ASP.NET Core, Web API, SQL, REST APIs and its Role is
        Software Development - the sole "Resume Screening" mention sits in
        the Selection Process section (how the employer screens candidates,
        not the work). It must no longer veto the whole posting."""
        allowed, reason = job_relevance_check(
            "Dot Net Developer",
            allowed_titles=["Data Analyst", "Software Engineer"],
            role_category="Engineering - Software & QA",
            department="Engineering - Software & QA",
            description=JOB_422_DESCRIPTION,
        )
        assert allowed is True, reason
        assert "resume screening" not in (reason or "").lower()

    def test_job_422_record_end_to_end_queue_verdict(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        job = _make_job(
            db_session,
            422,
            title="Dot Net Developer",
            description=JOB_422_DESCRIPTION,
        )
        payload = ManualApplyService(db_session).list_eligible()
        by_id = {item["job_id"]: item for item in payload["items"]}
        assert by_id[job.id]["eligible"] is True
        assert by_id[job.id]["exclusion_reason"] is None


class TestRelevantDotNetRoles:
    def test_dot_net_developer_relevant(self) -> None:
        allowed, reason = job_relevance_check(
            "Dot Net Developer",
            allowed_titles=["Software Engineer"],
            role_category="Engineering - Software & QA",
            department="Engineering - Software & QA",
            description=TECHNICAL_DOTNET_JD,
        )
        assert allowed is True, reason

    def test_asp_net_csharp_developer_relevant(self) -> None:
        """ASP.NET / C# software development (dotted spelling) — previously
        title-banned as an 'unwanted specialization'."""
        allowed, reason = job_relevance_check(
            "ASP.NET Core Developer (C#)",
            allowed_titles=["Software Engineer"],
            role_category="Engineering - Software & QA",
            department="Engineering - Software & QA",
            description=TECHNICAL_DOTNET_JD,
        )
        assert allowed is True, reason

    def test_dot_net_spellings_are_consistent(self) -> None:
        """Same role, same JD — the verdict must not depend on spelling."""
        for title in ("Dot Net Developer", ".NET Developer", "ASP.NET Developer", "C# Developer"):
            allowed, reason = job_relevance_check(
                title,
                allowed_titles=["Software Engineer"],
                role_category="Engineering - Software & QA",
                department="Engineering - Software & QA",
                description=TECHNICAL_DOTNET_JD,
            )
            assert allowed is True, f"{title!r}: {reason}"


class TestUnrelatedDotNetTitledRolesStillRejected:
    def test_dotnet_titled_mechanical_responsibilities_rejected(self) -> None:
        """A '.NET Developer' posting whose responsibilities are mechanical /
        production work stays rejected (two-hit excluded-responsibility
        list + excluded scope)."""
        mechanical_jd = (
            "Responsibilities: work on the assembly line and production line, "
            "mechanical engineering tasks, shop floor supervision, "
            "manufacturing plant support. Role Category: Production."
        )
        allowed, reason = job_relevance_check(
            ".NET Developer",
            allowed_titles=["Software Engineer"],
            role_category="Production",
            department="Production",
            description=mechanical_jd,
        )
        assert allowed is False
        assert "excluded" in reason.lower() or "outside the preferred" in reason.lower()

    def test_dotnet_titled_recruiter_jd_still_rejected(self) -> None:
        """'resume screening' still rejects when it appears alongside its
        recruitment companions — only the lone hiring-process mention inside
        a technical JD stopped being decisive."""
        recruiter_jd = (
            "Roles: sourcing candidates, resume screening, campus "
            "recruitment, coordinating interviews and offer letters."
        )
        allowed, reason = job_relevance_check(
            ".NET Developer",
            allowed_titles=["Software Engineer"],
            role_category="Engineering - Software & QA",
            department="Engineering - Software & QA",
            description=recruiter_jd,
        )
        assert allowed is False
        assert "resume screening" in reason.lower()

    def test_dotnet_titled_bpo_single_hit_still_rejected(self) -> None:
        """The strong single-hit list is intact for genuine process roles."""
        bpo_jd = "Voice process executive for international voice process on the voice process floor."
        allowed, reason = job_relevance_check(
            ".NET Developer",
            allowed_titles=["Software Engineer"],
            role_category="Engineering - Software & QA",
            department="Engineering - Software & QA",
            description=bpo_jd,
        )
        assert allowed is False
        assert "voice process" in reason.lower()


class TestListHygiene:
    def test_resume_screening_two_hit_not_single_hit(self) -> None:
        assert "resume screening" not in STRONG_EXCLUDED_RESPONSIBILITY_PHRASES
        assert "resume screening" in EXCLUDED_RESPONSIBILITY_PHRASES

    def test_dotnet_and_csharp_not_title_banned(self) -> None:
        assert ".net" not in UNWANTED_SPECIALIZATIONS
        assert "c#" not in UNWANTED_SPECIALIZATIONS
        # Unrelated stacks remain title-banned.
        assert "c++" in UNWANTED_SPECIALIZATIONS


class TestQueueConsistencyAndProtections:
    def test_queue_matches_shared_gate_and_shows_backend_reason(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """Eligibility badges must reflect the current shared-gate decision:
        the relevant .NET rows show Eligible; the mechanical .NET-titled row
        shows the backend's not_relevant reason (the same string the gate
        returns), not a stale or frontend-specific label."""
        relevant = _make_job(
            db_session, 1, title="Dot Net Developer", description=JOB_422_DESCRIPTION
        )
        irrelevant = _make_job(
            db_session,
            2,
            title=".NET Developer",
            description=(
                "Responsibilities: assembly line support, production line "
                "checks, mechanical engineering drawings, shop floor work."
            ),
            role_category="Production",
            department="Production",
        )

        gate_ok, gate_reason = job_relevance_check(
            irrelevant.title,
            allowed_titles=["Data Analyst", "Software Engineer"],
            role_category=irrelevant.role_category,
            department=irrelevant.department,
            description=irrelevant.description,
        )
        assert gate_ok is False

        payload = ManualApplyService(db_session).list_eligible()
        by_id = {item["job_id"]: item for item in payload["items"]}
        assert by_id[relevant.id]["eligible"] is True
        assert by_id[relevant.id]["exclusion_reason"] is None
        assert by_id[irrelevant.id]["eligible"] is False
        assert by_id[irrelevant.id]["exclusion_reason"] == f"not_relevant: {gate_reason}"

    def test_protected_application_history_stays_protected(
        self, db_session, confirmed_profile, job_preferences
    ) -> None:
        """A relevant .NET job with an APPLIED row keeps its history
        protection (eligibility is blocked before relevance even runs)."""
        job = _make_job(
            db_session, 3, title="ASP.NET Developer", description=TECHNICAL_DOTNET_JD
        )
        db_session.add(
            Application(job_id=job.id, status=ApplicationStatus.APPLIED.value)
        )
        db_session.commit()

        assert job.id in protected_job_ids(db_session, [job.id])
        payload = ManualApplyService(db_session).list_eligible()
        by_id = {item["job_id"]: item for item in payload["items"]}
        assert by_id[job.id]["eligible"] is False
        assert by_id[job.id]["exclusion_reason"] == "application_history"
        assert by_id[job.id]["application_status"] == "APPLIED"
