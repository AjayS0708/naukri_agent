"""E5-R24: target-title coverage + honest candidate pool.

Evidence from controlled live run #86 (2026-10-14):

1. Candidate-selection defect — 19 of the 23 "candidates" had already failed
   a deterministic hard filter at enqueue time (SALARY_BELOW_MINIMUM /
   OUTSIDE_SEARCH_SCOPE). The candidate query never re-applied that gate, so
   the runner skipped them a second time: the run reported 20 skips against
   2 real attempts and the funnel looked like valid jobs were being rejected.
2. Proven false rejection — interest_priority_rank already ranks
   "business analyst" (P1) and "data scientist" / "mlops" (P2) as targets, and
   test_autonomous_cycle asserts "Data Scientist" keeps tier 1, but the shared
   title gate had no such phrase. Real postings were lost: job #231 "Data
   Scientist - Generative AI (LLM | RAG | Agentic AI)" (NAUKRI_NATIVE),
   job #527 "Business Analyst" (NAUKRI_NATIVE) and job #336 "MLOps Engineer".
   A bare "Business Analyst" also carries no structural IT signal, so the
   IT-scope keyword fallback had to agree with the title gate.
3. Diagnostics — DecisionTracker only printed its table, so a skipped job's
   reason never survived the run.

Browser behavior is mocked: no live Naukri pages, no apply clicks, no
credential or application-record changes.
"""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database.database import Base
from backend.models.ai import JobAnalysisModel
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.models.profile import Profile, Resume
from backend.services.autonomous_cycle.service import AutonomousCycle
from backend.services.matching.engine import (
    is_strict_it_job,
    job_relevance_check,
    title_matches_allowed_role,
)
from backend.schemas.ai import AIRecommendation, JobQuality

TEST_DATABASE_URL = "sqlite:///:memory:"

TARGET_TITLES = (
    "Business Analyst",
    "Business Analyst Traineeship",
    "Data Scientist",
    "Data Scientist - Generative AI (LLM | RAG | Agentic AI)",
    "MLOps Engineer",
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
        data={
            "name": "Test User",
            "experience": [
                {"title": "Software Engineer", "company": "Tech Corp", "years": 2}
            ],
            "skills": ["Python", "SQL"],
            "location": "Bengaluru",
        },
    )
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return profile


@pytest.fixture
def job_preferences(db_session: Session):
    preferences = JobPreference(
        locations=["Bengaluru", "Remote"],
        job_titles=["Software Engineer", "Data Analyst"],
        employment_types=["Full-time", "Contract"],
        min_salary_lpa=4.0,
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
    title: str = "Data Analyst",
    description: str = "Python developer role",
    salary: str = "5-7 LPA",
    application_mode: str = "NAUKRI_NATIVE",
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"e5r24job{index}",
        url=f"https://www.naukri.com/e5r24job{index}",
        title=title,
        company=f"Company {index}",
        description=description,
        location="Bengaluru",
        salary=salary,
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
        application_mode=application_mode,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_analysis(db_session: Session, job_id: int) -> None:
    db_session.add(
        JobAnalysisModel(
            job_id=job_id,
            match_score=80,
            role_match=True,
            skill_match=True,
            experience_match=True,
            location_match=True,
            salary_match=True,
            job_quality=JobQuality.GOOD.value,
            duplicate_probability=0.05,
            suspicious=False,
            recommendation=AIRecommendation.APPLY.value,
            short_reason="ok",
            model="gemini",
            prompt_version="v1",
        )
    )
    db_session.commit()


def _prepare_cycle(db_session: Session, jobs: list[Job]) -> AutonomousCycle:
    for job in jobs:
        _make_analysis(db_session, job.id)
    run = DiscoveryRun(
        status="COMPLETED",
        jobs_discovered=len(jobs),
        current_run_job_ids=",".join(str(job.id) for job in jobs),
    )
    db_session.add(run)
    db_session.commit()
    cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
    cycle.current_discovery_run = run
    return cycle


# ── Defect: title gate missed P1/P2 target phrases ────────────────────────


class TestTargetTitleCoverage:
    @pytest.mark.parametrize("title", TARGET_TITLES)
    def test_p1_p2_target_titles_match_an_allowed_family(self, title):
        allowed, reason = title_matches_allowed_role(title)
        assert allowed is True, reason

    @pytest.mark.parametrize("title", TARGET_TITLES)
    def test_p1_p2_target_titles_pass_the_shared_relevance_gate(self, title):
        ok, reason = job_relevance_check(
            title,
            ["Software Engineer", "Data Analyst"],
            description="Build dashboards and pipelines in Python and SQL.",
        )
        assert ok is True, reason

    @pytest.mark.parametrize(
        "title",
        (
            "Business Analyst (Sales)",
            "Business Analyst - Finance",
            "Data Scientist - Marketing",
            "MLOps Engineer Sales",
        ),
    )
    def test_unwanted_specializations_still_win_over_target_phrases(self, title):
        allowed, reason = title_matches_allowed_role(title)
        assert allowed is False, title
        assert "unwanted specialization" in reason.lower(), reason

    @pytest.mark.parametrize(
        "title",
        (
            "International Voice Process Executive",
            "Customer Support Executive",
            "Graphic Designer",
        ),
    )
    def test_irrelevant_titles_stay_rejected(self, title):
        allowed, _ = title_matches_allowed_role(title)
        assert allowed is False, title

    def test_bare_business_analyst_title_carries_it_scope(self):
        assert is_strict_it_job(Job(title="Business Analyst")) is True
        # The keyword expansion must not turn a non-target into an IT job.
        assert is_strict_it_job(Job(title="Marketing Manager")) is False


# ── Defect: candidate pool ignored deterministic hard filters ─────────────


class TestCandidatePoolReappliesHardFilters:
    @pytest.mark.asyncio
    async def test_salary_rejected_job_never_becomes_a_candidate(
        self, db_session, confirmed_profile, job_preferences
    ):
        """A job the enqueue stage rejected stays rejected in the apply loop."""
        low_salary = _make_job(db_session, 1, title="Data Analyst", salary="2 LPA")
        cycle = self._cycle(db_session, [low_salary])

        with patch.object(
            cycle, "_process_single_job", new=AsyncMock(return_value="APPLIED")
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["candidates"] == 0
        assert stats["hard_filtered_candidates"] == 1
        assert stats["relevance_rejected"] == 0
        assert mock_process.await_count == 0, "the apply loop must not run"

        decisions = cycle._candidate_stage_decisions()
        assert [d["outcome"] for d in decisions] == ["HARD_FILTERED"]
        assert "below minimum" in decisions[0]["reason"]
        assert decisions[0]["job_id"] == low_salary.id

    @pytest.mark.asyncio
    async def test_eligible_job_survives_alongside_the_filtered_one(
        self, db_session, confirmed_profile, job_preferences
    ):
        """The hard-filter re-check must not cull a job that can be attempted."""
        eligible = _make_job(db_session, 10, title="Data Analyst")
        filtered = _make_job(db_session, 11, title="Data Analyst", salary="3 LPA")
        cycle = self._cycle(db_session, [eligible, filtered])
        visited: list[int] = []

        async def _fake_process(db, job, profile, preferences):
            visited.append(job.id)
            cycle.tracker.add_decision(
                job.id, job.company, job.title, "NATIVE",
                True, True, True, "APPLY", "PASSED", "APPLIED",
            )
            return "APPLIED"

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["candidates"] == 1
        assert stats["hard_filtered_candidates"] == 1
        assert visited == [eligible.id]
        assert stats["applied"] == 1

        outcomes = {d["job_id"]: d["outcome"] for d in cycle._candidate_stage_decisions()}
        assert outcomes == {eligible.id: "APPLIED", filtered.id: "HARD_FILTERED"}

    @pytest.mark.asyncio
    async def test_relevance_rejection_reason_is_persisted_on_the_decision_rows(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Skip and rejection reasons survive the run instead of stdout only."""
        irrelevant = _make_job(
            db_session,
            20,
            title="International Voice Process Executive",
            description="Handle voice process calls for international clients.",
        )
        cycle = self._cycle(db_session, [irrelevant])

        with patch.object(
            cycle, "_process_single_job", new=AsyncMock(return_value="APPLIED")
        ) as mock_process:
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["relevance_rejected"] == 1
        assert stats["candidates"] == 0
        assert mock_process.await_count == 0

        decisions = cycle._candidate_stage_decisions()
        assert [d["outcome"] for d in decisions] == ["RELEVANCE_REJECTED"]
        assert decisions[0]["reason"]
        assert decisions[0]["job_id"] == irrelevant.id

    @pytest.mark.asyncio
    async def test_enqueue_stage_rows_are_excluded_from_the_decision_slice(
        self, db_session, confirmed_profile, job_preferences
    ):
        """Only candidate-stage reasons are persisted (keeps the payload small)."""
        job = _make_job(db_session, 30, title="Data Analyst", salary="2 LPA")
        cycle = self._cycle(db_session, [job])
        # Enqueue-stage row recorded before _run_applications begins.
        cycle.tracker.add_decision(
            job.id, job.company, job.title, "N/A",
            False, False, False, "N/A",
            "Salary (2.5 LPA) is below minimum 4 LPA.", "HARD_FILTERED",
        )

        with patch.object(
            cycle, "_process_single_job", new=AsyncMock(return_value="APPLIED")
        ):
            stats = await cycle._run_applications(
                db_session, confirmed_profile, job_preferences
            )

        assert stats["candidates"] == 0
        decisions = cycle._candidate_stage_decisions()
        assert len(decisions) == 1, "the enqueue-stage row must stay out of the slice"
        assert decisions[0]["job_id"] == job.id
        assert decisions[0]["outcome"] == "HARD_FILTERED"
        assert "below minimum" in decisions[0]["reason"]
        assert set(decisions[0]) == {"job_id", "title", "outcome", "reason"}

    @staticmethod
    def _cycle(db_session: Session, jobs: list[Job]) -> AutonomousCycle:
        return _prepare_cycle(db_session, jobs)
