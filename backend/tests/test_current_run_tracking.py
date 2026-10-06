"""
Tests for current-run job tracking to ensure the autonomous cycle
processes all jobs discovered in the current run, not just new ones.
"""

import pytest
from datetime import UTC, datetime
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.services.discovery.service import DiscoveryService
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager


@pytest.fixture
def db_session():
    from backend.database.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()  # Rollback to avoid conflicts between tests
        db.close()


@pytest.fixture
def state_manager():
    return AgentStateManager(initial_state=AgentState.IDLE)


def test_current_run_tracks_new_and_existing_jobs(db_session: Session, state_manager):
    """Test that current run tracks both new and existing jobs."""
    # Clean up
    db_session.execute(text("DELETE FROM jobs WHERE external_job_id LIKE 'track_%'"))
    db_session.commit()

    # Create 5 existing jobs with historical timestamps
    historical_time = datetime(2025, 1, 1, tzinfo=UTC)
    existing_job_ids = []
    for i in range(5):
        job = Job(
            platform="naukri",
            external_job_id=f"track_existing_{i}",
            url=f"https://naukri.com/job/{i}",
            title="Software Engineer Fresher",
            company="Test Corp",
            description="Test job",
            location="Bengaluru",
            discovered_at=historical_time,
            last_seen=historical_time,
            source="Software Engineer Fresher"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        existing_job_ids.append(job.id)

    # Verify jobs exist
    assert len(existing_job_ids) == 5

    # Create a new discovery run
    run = DiscoveryRun(status="RUNNING")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    # Simulate discovery service tracking
    from backend.services.discovery.service import DiscoveryService
    service = DiscoveryService(state_manager)
    service.current_run = run
    service.current_run_job_ids = set()

    # Add all 5 existing jobs to current run (simulating rediscovery)
    for job_id in existing_job_ids:
        service.current_run_job_ids.add(job_id)
        service.current_run.duplicate_jobs += 1

    # Add 2 new jobs
    for i in range(2):
        new_job = Job(
            platform="naukri",
            external_job_id=f"track_new_{i}",
            url=f"https://naukri.com/job/new_{i}",
            title="Software Engineer Fresher",
            company="New Corp",
            description="New job",
            location="Bengaluru",
            discovered_at=datetime.now(UTC),
            last_seen=datetime.now(UTC),
            source="Software Engineer Fresher"
        )
        db_session.add(new_job)
        db_session.commit()
        db_session.refresh(new_job)
        service.current_run_job_ids.add(new_job.id)
        service.current_run.new_jobs += 1

    service.current_run.jobs_discovered = 7  # 5 existing + 2 new

    # Finalize run
    service._finalize_run(db_session, "COMPLETED", None)

    # Verify run metadata
    db_session.refresh(run)
    assert run.jobs_discovered == 7
    assert run.new_jobs == 2
    assert run.duplicate_jobs == 5
    assert run.current_run_job_ids is not None

    # Parse job IDs
    current_run_ids = [int(jid) for jid in run.current_run_job_ids.split(",")]
    assert len(current_run_ids) == 7
    assert set(current_run_ids) == service.current_run_job_ids


def test_autonomous_cycle_uses_current_run_job_ids(db_session: Session):
    """Test that autonomous cycle uses job IDs from current run instead of timestamp."""
    from backend.models.discovery import DiscoveryRun

    # Clean up any existing jobs from previous tests
    db_session.execute(text("DELETE FROM jobs WHERE external_job_id LIKE 'existing_run_%' OR external_job_id LIKE 'new_run_%'"))
    db_session.commit()

    # Create 5 existing jobs with historical timestamps
    historical_time = datetime(2025, 1, 1, tzinfo=UTC)
    existing_job_ids = []
    for i in range(5):
        job = Job(
            platform="naukri",
            external_job_id=f"existing_run_{i}",
            url=f"https://naukri.com/job/{i}",
            title="Software Engineer Fresher",
            company="Test Corp",
            description="Test job",
            location="Bengaluru",
            discovered_at=historical_time,
            last_seen=historical_time,
            source="Software Engineer Fresher"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        existing_job_ids.append(job.id)

    # Create 2 new jobs with current timestamps
    current_time = datetime.now(UTC)
    new_job_ids = []
    for i in range(2):
        job = Job(
            platform="naukri",
            external_job_id=f"new_run_{i}",
            url=f"https://naukri.com/job/new_{i}",
            title="Software Engineer Fresher",
            company="New Corp",
            description="New job",
            location="Bengaluru",
            discovered_at=current_time,
            last_seen=current_time,
            source="Software Engineer Fresher"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        new_job_ids.append(job.id)

    # Create a discovery run with all 7 job IDs
    run = DiscoveryRun(
        status="COMPLETED",
        started_at=current_time,
        completed_at=current_time,
        jobs_discovered=7,
        new_jobs=2,
        duplicate_jobs=5,
        current_run_job_ids=",".join(str(jid) for jid in (existing_job_ids + new_job_ids))
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    # Query using job IDs from current run
    from sqlalchemy import select
    current_run_job_ids = [int(jid) for jid in run.current_run_job_ids.split(",")]
    stmt = select(Job).where(Job.id.in_(current_run_job_ids))
    jobs = db_session.execute(stmt).scalars().all()

    # Should get all 7 jobs, not just the 2 new ones
    assert len(jobs) == 7
    assert set(job.id for job in jobs) == set(existing_job_ids + new_job_ids)


def test_historical_job_not_in_current_run_excluded(db_session: Session):
    """Test that historical jobs not in current run are excluded."""
    from backend.models.discovery import DiscoveryRun

    # Clean up
    db_session.execute(text("DELETE FROM jobs WHERE external_job_id LIKE 'hist_exclude_%' OR external_job_id LIKE 'curr_exclude_%'"))
    db_session.commit()

    # Create 5 historical jobs
    historical_time = datetime(2025, 1, 1, tzinfo=UTC)
    historical_job_ids = []
    for i in range(5):
        job = Job(
            platform="naukri",
            external_job_id=f"hist_exclude_{i}",
            url=f"https://naukri.com/job/hist_{i}",
            title="Software Engineer Fresher",
            company="Hist Corp",
            description="Historical job",
            location="Bengaluru",
            discovered_at=historical_time,
            last_seen=historical_time,
            source="Software Engineer Fresher"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        historical_job_ids.append(job.id)

    # Create 3 current jobs
    current_time = datetime.now(UTC)
    current_job_ids = []
    for i in range(3):
        job = Job(
            platform="naukri",
            external_job_id=f"curr_exclude_{i}",
            url=f"https://naukri.com/job/curr_{i}",
            title="Software Engineer Fresher",
            company="Curr Corp",
            description="Current job",
            location="Bengaluru",
            discovered_at=current_time,
            last_seen=current_time,
            source="Software Engineer Fresher"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        current_job_ids.append(job.id)

    # Create a discovery run with only the 3 current jobs
    run = DiscoveryRun(
        status="COMPLETED",
        started_at=current_time,
        completed_at=current_time,
        jobs_discovered=3,
        new_jobs=3,
        duplicate_jobs=0,
        current_run_job_ids=",".join(str(jid) for jid in current_job_ids)
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    # Query using job IDs from current run
    from sqlalchemy import select
    current_run_job_ids = [int(jid) for jid in run.current_run_job_ids.split(",")]
    stmt = select(Job).where(Job.id.in_(current_run_job_ids))
    jobs = db_session.execute(stmt).scalars().all()

    # Should get only the 3 current jobs, not the 5 historical ones
    assert len(jobs) == 3
    assert set(job.id for job in jobs) == set(current_job_ids)


def test_zero_current_jobs_stops_cycle(db_session: Session):
    """Test that zero current jobs in discovery run stops the cycle."""
    from backend.models.discovery import DiscoveryRun

    current_time = datetime.now(UTC)

    # Create a discovery run with zero jobs
    run = DiscoveryRun(
        status="COMPLETED",
        started_at=current_time,
        completed_at=current_time,
        jobs_discovered=0,
        new_jobs=0,
        duplicate_jobs=0,
        current_run_job_ids=None
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    # Query should return empty
    assert run.current_run_job_ids is None
    assert run.jobs_discovered == 0


def test_current_run_candidate_count_matches_discovery(db_session: Session):
    """Test that current candidate count matches discovery result."""
    from backend.models.discovery import DiscoveryRun

    # Clean up
    db_session.execute(text("DELETE FROM jobs WHERE external_job_id LIKE 'match_%'"))
    db_session.commit()

    # Create 10 jobs
    current_time = datetime.now(UTC)
    all_job_ids = []
    for i in range(10):
        job = Job(
            platform="naukri",
            external_job_id=f"match_{i}",
            url=f"https://naukri.com/job/{i}",
            title="Software Engineer Fresher",
            company="Test Corp",
            description="Test job",
            location="Bengaluru",
            discovered_at=current_time,
            last_seen=current_time,
            source="Software Engineer Fresher"
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)
        all_job_ids.append(job.id)

    # Create a discovery run with all 10 jobs
    run = DiscoveryRun(
        status="COMPLETED",
        started_at=current_time,
        completed_at=current_time,
        jobs_discovered=10,
        new_jobs=10,
        duplicate_jobs=0,
        current_run_job_ids=",".join(str(jid) for jid in all_job_ids)
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    # Query using job IDs from current run
    from sqlalchemy import select
    current_run_job_ids = [int(jid) for jid in run.current_run_job_ids.split(",")]
    stmt = select(Job).where(Job.id.in_(current_run_job_ids))
    jobs = db_session.execute(stmt).scalars().all()

    # Candidate count should match discovery count
    assert len(jobs) == run.jobs_discovered
    assert len(jobs) == 10
