"""E5-R22: idempotent start + shared relevance candidate filtering.

Regression coverage for the three defects observed in the first controlled
live run (run #80):

1. Double-run appearance — the backend must remain a single atomic claim
   (no independent runner per duplicate POST) and surface the active run's
   identity so the client can distinguish a real second run from a retried
   start; a dead-pid orphan is adopted, and a completed run allows a
   legitimate subsequent run.
2. Irrelevant-job leak — BPO / voice-call / customer-support / telemarketing
   / apprenticeship titles are rejected at the shared relevance gate, and
   unambiguous process/support phrases in the JD reject on a single hit even
   when the short JD cannot reach the two-hit threshold. Genuine technical
   roles with a minor support mention are not swept away.
3. Single-application symptom — _run_applications pre-filters candidates
   through the shared relevance gate before the progress document and the
   apply loop, so irrelevant jobs never become candidates (and never show
   up as skipped-only noise in the dashboard).

All browser/runner behavior is mocked: no live Naukri pages, no Apply
clicks, no real browser sessions, no database writes beyond the test DBs.
"""
import asyncio
from datetime import UTC, datetime
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
from backend.services.applications import ApplicationService
from backend.services.autonomous_cycle.coordinator import CycleCoordinator
from backend.services.autonomous_cycle.service import AutonomousCycle
from backend.services.matching.engine import (
    job_relevance_check,
    title_matches_allowed_role,
    irrelevant_role_reason,
    MIN_EXCLUDED_RESPONSIBILITY_HITS,
)
from backend.schemas.ai import AIRecommendation, JobQuality

TEST_DATABASE_URL = "sqlite:///:memory:"


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
            "education": [{"degree": "B.Tech", "university": "Test University"}],
            "location": "Bengaluru",
            "current_ctc": "5 LPA",
            "notice_period": "30 days",
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
    title: str = "Software Engineer",
    description: str = "Python developer role",
    role_category: str | None = None,
    department: str | None = None,
    application_mode: str = "NAUKRI_NATIVE",
) -> Job:
    job = Job(
        platform="naukri",
        external_job_id=f"e5r22job{index}",
        url=f"https://www.naukri.com/e5r22job{index}",
        title=title,
        company=f"Company {index}",
        description=description,
        location="Bengaluru",
        salary="5-7 LPA",
        experience="0-2 years",
        employment_type="Full-time",
        status="DISCOVERED",
        application_mode=application_mode,
        role_category=role_category,
        department=department,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def _make_analysis(db_session: Session, job_id: int, *, score: int = 80) -> None:
    db_session.add(
        JobAnalysisModel(
            job_id=job_id,
            match_score=score,
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


# ── Defect 1: double-run guard ────────────────────────────────────────────


class TestStartGuardIdentity:
    """The atomic claim must never launch two runners for one active run."""

    def test_second_acquire_sees_same_active_run_identity(self, db_session: Session):
        coord = CycleCoordinator()
        ok1, token1, snap1 = coord.try_acquire(db=db_session)
        assert ok1 is True
        assert snap1["active_state"] == "RUNNING"

        # A duplicate (rapid double-click / browser retry) must be rejected
        # and must see the SAME active run identity — not a new token.
        ok2, token2, snap2 = coord.try_acquire(db=db_session)
        assert ok2 is False
        assert token2 is None
        assert snap2["active_state"] == "RUNNING"
        assert snap2["active_run"]["run_token"] == token1
        assert snap2["active_run"]["status"] == "RUNNING"

        coord.complete(
            token1,
            {"status": "COMPLETED", "run_id": 1, "stats": {"applied": 1}},
            db=db_session,
        )

    def test_legit_subsequent_run_after_complete(self, db_session: Session):
        coord = CycleCoordinator()
        ok1, token1, _ = coord.try_acquire(db=db_session)
        assert ok1 is True
        coord.complete(token1, {"status": "COMPLETED", "run_id": 1, "stats": {}}, db=db_session)

        # A genuine second run (previous completed) must acquire a NEW token.
        ok2, token2, snap2 = coord.try_acquire(db=db_session)
        assert ok2 is True
        assert token2 is not None
        assert token2 != token1
        assert snap2["active_state"] == "RUNNING"
        coord.complete(token2, {"status": "COMPLETED", "run_id": 2, "stats": {}}, db=db_session)

    def test_acquire_with_dead_pid_adopts_orphan(self, db_session: Session):
        """A RUNNING row owned by a dead process is adopted, not deadlocked."""
        from backend.models.cycle_run import CycleRunControl

        coord = CycleCoordinator()
        # Simulate a stale lock: RUNNING with a pid that cannot be alive.
        row = CycleRunControl(
            id=1,
            status="RUNNING",
            run_token="cycle-stale-dead",
            pid=2**22 + 12345,  # beyond any real Windows/Linux pid
            started_at=datetime.now(UTC),
        )
        db_session.add(row)
        db_session.commit()

        ok, token, snap = coord.try_acquire(db=db_session)
        assert ok is True, "dead-pid orphan lock must be adopted"
        assert token != "cycle-stale-dead"
        assert snap["active_run"]["run_token"] == token
        coord.complete(token, {"status": "COMPLETED", "run_id": 9, "stats": {}}, db=db_session)

    def test_concurrent_acquire_only_one_wins(self, db_session: Session):
        """Sequential rapid acquires: first wins, rest rejected — one runner."""
        coord = CycleCoordinator()
        results = [coord.try_acquire(db=db_session) for _ in range(5)]
        winners = [r for r in results if r[0]]
        assert len(winners) == 1, "exactly one acquire may win while RUNNING"
        winner_token = winners[0][1]
        for acquired, token, snap in results:
            if not acquired:
                assert token is None
                assert snap["active_run"]["run_token"] == winner_token
        coord.complete(winner_token, {"status": "COMPLETED", "run_id": 1, "stats": {}}, db=db_session)


# ── Defect 2: shared relevance filtering ──────────────────────────────────


class TestSharedRelevanceExclusions:
    """BPO / voice / customer-support / apprenticeship titles and JDs."""

    @pytest.mark.parametrize(
        "title",
        [
            "Apprentice - Trainee",
            "Software Engineer Apprenticeship",
            "Customer Support Executive",
            "International Voice Process Executive",
            "BPO Voice Process Executive",
            "Telecalling Executive",
            "Telemarketing Agent",
            "Hiring Freshers - International Voice/Customer Support",
            "Call Center Support Associate",
        ],
    )
    def test_unwanted_titles_rejected(self, title: str):
        allowed, reason = title_matches_allowed_role(title)
        assert allowed is False, f"{title!r} must be rejected"
        assert "unwanted specialization" in reason.lower() or "does not match" in reason.lower()

    @pytest.mark.parametrize(
        "title",
        [
            "Apprentice - Trainee",
            "Software Engineer Apprenticeship",
            "Customer Support Executive",
            "International Voice Process Executive",
        ],
    )
    def test_apprentice_and_support_rejected_even_with_configured_titles(self, title: str):
        """Configured job_titles must not resurrect excluded specializations."""
        allowed, _ = title_matches_allowed_role(
            title, ["Data Analyst", "Software Engineer", "Apprentice"]
        )
        assert allowed is False, f"{title!r} must stay rejected with configured titles"

    @pytest.mark.parametrize(
        "description",
        [
            "Handle voice process calls for international clients.",
            "Provide customer support via chat and email for the product.",
            "BPO process for UK night-shift voice process.",
            "Inbound call centre operations for a telecom client.",
        ],
    )
    def test_strong_single_hit_responsibility_rejection(self, description: str):
        """One unambiguous phrase rejects a short JD (two-hit threshold not needed)."""
        reason = irrelevant_role_reason(
            title="Associate Software Engineer", description=description
        )
        assert reason is not None, f"JD must be rejected: {description!r}"
        assert "excluded role" in reason.lower()

    def test_two_hit_threshold_still_works_for_loose_phrases(self):
        """Non-strong phrases still require the documented two-hit threshold."""
        # One loose phrase alone: not rejected (IT JD mentions lead generation).
        single = irrelevant_role_reason(
            title="Data Analyst",
            description="Work on data pipelines and lead generation dashboards.",
        )
        assert single is None, "one loose phrase must not reject an IT JD"

        # Two loose phrases: rejected (existing behaviour).
        double = irrelevant_role_reason(
            title="Data Analyst",
            description="Cold calling and field sales for the product line.",
        )
        assert double is not None
        assert "excluded role" in double.lower()

    def test_technical_data_role_not_rejected_by_minor_mention(self):
        """A genuine data role with one support mention is not swept away."""
        ok, reason = job_relevance_check(
            "Data Analyst",
            ["Data Analyst"],
            description=(
                "Build SQL dashboards and Power BI reports. Occasional customer "
                "handling for requirement gathering. Python and pandas for ETL."
            ),
        )
        # "customer handling" is a single non-strong phrase; the technical
        # signals and allowed title must keep the job relevant.
        assert ok is True, f"Data Analyst must stay relevant, got: {reason}"

    def test_scope_categories_include_customer_support(self):
        """role_category / department 'Customer Support' is excluded scope."""
        reason = irrelevant_role_reason(
            title="Associate Software Engineer",
            role_category="Customer Support",
            description="Handle client queries and process service requests.",
        )
        assert reason is not None
        assert "customer support" in reason.lower() or "scope" in reason.lower()

    def test_final_safety_gate_enforces_apprentice_rejection(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference,
    ):
        """The final application safety gate rejects apprenticeship jobs."""
        job = _make_job(
            db_session, 900, title="Apprentice - Trainee",
            description="12-month apprenticeship program for graduates.",
        )
        service = ApplicationService(db_session)
        allowed, reason = service.run_final_safety_gate(job, confirmed_profile, job_preferences)
        assert allowed is False
        assert "apprentice" in reason.lower() or "unwanted specialization" in reason.lower()


# ── Defect 3: candidate pre-filter in _run_applications ───────────────────


class TestCandidatePreFilter:
    """Irrelevant jobs never become candidates in _run_applications."""

    def _prepare_cycle(
        self, db_session: Session, jobs: list[Job]
    ) -> AutonomousCycle:
        for j in jobs:
            _make_analysis(db_session, j.id)
        run = DiscoveryRun(
            status="COMPLETED",
            jobs_discovered=len(jobs),
            current_run_job_ids=",".join(str(j.id) for j in jobs),
        )
        db_session.add(run)
        db_session.commit()
        cycle = AutonomousCycle(max_applications=None, enable_cli_output=False)
        cycle.current_discovery_run = run
        return cycle

    @pytest.mark.asyncio
    async def test_irrelevant_jobs_excluded_from_candidates(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference,
    ):
        """BPO / voice / customer-support jobs never enter the candidate list."""
        relevant = _make_job(db_session, 1, title="Data Analyst")
        irrelevant_voice = _make_job(
            db_session, 2,
            title="International Voice Process Executive",
            description="Handle voice process calls for international clients.",
        )
        irrelevant_support = _make_job(
            db_session, 3,
            title="Customer Support Executive",
            description="Provide customer support via chat and email.",
        )
        irrelevant_apprentice = _make_job(
            db_session, 4, title="Apprentice - Trainee",
            description="12-month apprenticeship program for graduates.",
        )
        jobs = [relevant, irrelevant_voice, irrelevant_support, irrelevant_apprentice]
        cycle = self._prepare_cycle(db_session, jobs)

        visited: list[int] = []

        async def _fake_process(db, job, profile, preferences):
            visited.append(job.id)
            return "APPLIED"

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            stats = await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        assert stats["candidates"] == 1, "only the Data Analyst is a candidate"
        assert stats["relevance_rejected"] == 3
        assert visited == [relevant.id], "only the relevant job reaches the apply loop"
        assert stats["applied"] == 1

    @pytest.mark.asyncio
    async def test_progress_doc_counts_only_relevant_candidates(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference,
    ):
        """The progress document candidates_total reflects only relevant jobs."""
        relevant = _make_job(db_session, 10, title="Software Engineer")
        irrelevant = _make_job(
            db_session, 11, title="BPO Voice Process Executive",
            description="BPO voice process for UK clients.",
        )
        jobs = [relevant, irrelevant]
        cycle = self._prepare_cycle(db_session, jobs)

        async def _fake_process(db, job, profile, preferences):
            return "SKIPPED"

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            stats = await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        assert stats["candidates"] == 1
        assert stats["relevance_rejected"] == 1
        assert cycle._run_progress["candidates_total"] == 1
        assert cycle._run_progress["remaining"] == 0

    @pytest.mark.asyncio
    async def test_all_candidates_irrelevant_short_circuits(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference,
    ):
        """When nothing survives the pre-filter, the loop never starts."""
        j1 = _make_job(
            db_session, 20, title="Telecalling Executive",
            description="Telecalling for sales targets.",
        )
        j2 = _make_job(
            db_session, 21, title="Customer Service Associate",
            description="Customer service via inbound calls.",
        )
        cycle = self._prepare_cycle(db_session, [j1, j2])

        with patch.object(
            cycle, "_process_single_job", new=AsyncMock(return_value="APPLIED")
        ) as mock_process:
            stats = await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        assert stats["candidates"] == 0
        assert stats["relevance_rejected"] == 2
        assert mock_process.await_count == 0, "apply loop must not run for zero candidates"
        assert stats["applied"] == 0

    @pytest.mark.asyncio
    async def test_relevant_jobs_still_all_reachable(
        self,
        db_session: Session,
        confirmed_profile: Profile,
        job_preferences: JobPreference,
    ):
        """P1/P2/P3 technical roles all remain candidates (no false cull)."""
        titles = [
            "Data Analyst",
            "Power BI Developer",
            "Data Engineer",
            "Machine Learning Engineer",
            "Graduate Software Engineer Trainee",
            "Fresher Software Engineer",
        ]
        jobs = [
            _make_job(db_session, 30 + i, title=t) for i, t in enumerate(titles)
        ]
        cycle = self._prepare_cycle(db_session, jobs)

        visited: list[int] = []

        async def _fake_process(db, job, profile, preferences):
            visited.append(job.id)
            return "APPLIED"

        with patch.object(cycle, "_process_single_job", side_effect=_fake_process):
            stats = await cycle._run_applications(db_session, confirmed_profile, job_preferences)

        assert stats["candidates"] == len(titles)
        assert stats["relevance_rejected"] == 0
        assert sorted(visited) == sorted(j.id for j in jobs)
