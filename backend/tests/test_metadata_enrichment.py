"""
Unit tests for metadata enrichment on NEW jobs.
Tests that DiscoveryService correctly populates industry, department, and role_category
from fetch_job_details results when creating new jobs.
"""

import pytest
from datetime import UTC, datetime
from unittest.mock import MagicMock, AsyncMock, patch

from sqlalchemy.orm import Session

from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.services.discovery.service import DiscoveryService
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.matching import JobPreference


def _initialize_discovery_run(run: DiscoveryRun) -> None:
    run.id = 1
    run.searches_attempted = 0
    run.jobs_discovered = 0
    run.new_jobs = 0
    run.duplicate_jobs = 0
    run.errors = 0
    run.pages_processed = 0


@pytest.fixture
def mock_db_session():
    mock = MagicMock(spec=Session)

    def add_side_effect(obj):
        if isinstance(obj, DiscoveryRun):
            _initialize_discovery_run(obj)

    mock.add.side_effect = add_side_effect
    return mock


@pytest.fixture
def state_manager():
    return AgentStateManager(initial_state=AgentState.IDLE)


@pytest.fixture
def mock_adapter():
    with patch("backend.services.discovery.service.NaukriAdapter") as MockAdapter:
        adapter_instance = MockAdapter.return_value
        adapter_instance.start_session = AsyncMock(return_value=True)
        adapter_instance.stop_session = AsyncMock()

        # Mock fetch_job_details to return realistic metadata
        adapter_instance.fetch_job_details = AsyncMock(return_value={
            "description": "Full job description here",
            "industry": "IT Services & Consulting",
            "department": "Engineering - Software & QA",
            "role_category": "Software Engineer"
        })

        async def mock_search_jobs(*args, **kwargs):
            yield {
                "title": "Software Engineer",
                "company": "Tech Corp",
                "url": "http://naukri.com/job",
                "external_job_id": "12345",
                "location": "Bengaluru",
                "experience": "0-2 Yrs",
                "salary": "10-15 LPA",
                "page_number": 1,
            }

        adapter_instance.search_jobs = mock_search_jobs
        adapter_instance.platform_name = "naukri"
        yield adapter_instance


@pytest.mark.asyncio
async def test_new_job_receives_metadata_from_fetch_details(
    state_manager, mock_db_session, mock_adapter
):
    """Test that NEW jobs receive industry, department, and role_category from fetch_job_details."""
    fixed_now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)

    with patch("backend.services.discovery.service.utc_now", return_value=fixed_now):
        service = DiscoveryService(state_manager)
        service.adapter = mock_adapter

        mock_preferences = MagicMock(spec=JobPreference)
        mock_preferences.job_titles = ["Developer"]
        mock_preferences.locations = ["Bengaluru"]
        mock_preferences.max_required_experience_years = 0

        mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
            mock_preferences,
            None,  # external_id check
            None,  # url check
            None,  # title+company check
        ]

        await service.run_discovery(mock_db_session)

    add_calls = mock_db_session.add.call_args_list
    assert len(add_calls) == 2  # DiscoveryRun + Job

    saved_job = add_calls[1].args[0]
    assert isinstance(saved_job, Job)

    # Verify metadata was populated from fetch_job_details
    assert saved_job.industry == "IT Services & Consulting"
    assert saved_job.department == "Engineering - Software & QA"
    assert saved_job.role_category == "Software Engineer"
    assert saved_job.description == "Full job description here"

    # Verify fetch_job_details was called
    mock_adapter.fetch_job_details.assert_awaited_once_with("http://naukri.com/job")


@pytest.mark.asyncio
async def test_new_job_with_partial_metadata(
    state_manager, mock_db_session, mock_adapter
):
    """Test that NEW jobs receive available metadata even if some fields are missing."""
    fixed_now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)

    # Mock fetch_job_details to return partial metadata
    mock_adapter.fetch_job_details = AsyncMock(return_value={
        "description": "Full job description here",
        "industry": "IT Services & Consulting",
        # department missing
        "role_category": "Software Engineer"
    })

    with patch("backend.services.discovery.service.utc_now", return_value=fixed_now):
        service = DiscoveryService(state_manager)
        service.adapter = mock_adapter

        mock_preferences = MagicMock(spec=JobPreference)
        mock_preferences.job_titles = ["Developer"]
        mock_preferences.locations = ["Bengaluru"]
        mock_preferences.max_required_experience_years = 0

        mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
            mock_preferences,
            None,  # external_id check
            None,  # url check
            None,  # title+company check
        ]

        await service.run_discovery(mock_db_session)

    add_calls = mock_db_session.add.call_args_list
    saved_job = add_calls[1].args[0]

    # Verify available metadata was populated
    assert saved_job.industry == "IT Services & Consulting"
    assert saved_job.role_category == "Software Engineer"
    assert saved_job.department is None  # Missing field should be None


@pytest.mark.asyncio
async def test_new_job_with_no_metadata(
    state_manager, mock_db_session, mock_adapter
):
    """Test that NEW jobs are created even if fetch_job_details returns no metadata."""
    fixed_now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)

    # Mock fetch_job_details to return empty dict
    mock_adapter.fetch_job_details = AsyncMock(return_value={})

    with patch("backend.services.discovery.service.utc_now", return_value=fixed_now):
        service = DiscoveryService(state_manager)
        service.adapter = mock_adapter

        mock_preferences = MagicMock(spec=JobPreference)
        mock_preferences.job_titles = ["Developer"]
        mock_preferences.locations = ["Bengaluru"]
        mock_preferences.max_required_experience_years = 0

        mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
            mock_preferences,
            None,  # external_id check
            None,  # url check
            None,  # title+company check
        ]

        await service.run_discovery(mock_db_session)

    add_calls = mock_db_session.add.call_args_list
    saved_job = add_calls[1].args[0]

    # Verify job was created even without metadata
    assert isinstance(saved_job, Job)
    assert saved_job.title == "Software Engineer"
    assert saved_job.industry is None
    assert saved_job.department is None
    assert saved_job.role_category is None


@pytest.mark.asyncio
async def test_fetch_details_called_for_every_new_job(
    state_manager, mock_db_session, mock_adapter
):
    """Test that fetch_job_details is called for every NEW job."""
    fixed_now = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)

    async def mock_search_jobs_multi(*args, **kwargs):
        yield {
            "title": "Engineer A",
            "company": "Corp A",
            "url": "http://naukri.com/job-a",
            "external_job_id": "a",
            "page_number": 1,
        }
        yield {
            "title": "Engineer B",
            "company": "Corp B",
            "url": "http://naukri.com/job-b",
            "external_job_id": "b",
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs_multi
    mock_adapter.fetch_job_details = AsyncMock(return_value={
        "industry": "IT Services",
        "department": "Engineering",
        "role_category": "Engineer"
    })

    with patch("backend.services.discovery.service.utc_now", return_value=fixed_now):
        service = DiscoveryService(state_manager)
        service.adapter = mock_adapter

        mock_preferences = MagicMock(spec=JobPreference)
        mock_preferences.job_titles = ["Developer"]
        mock_preferences.locations = ["Bengaluru"]

        mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
            mock_preferences,
            None, None, None,  # Job A dedup checks
            None, None, None,  # Job B dedup checks
        ]

        await service.run_discovery(mock_db_session)

    # Verify fetch_job_details was called for both jobs
    assert mock_adapter.fetch_job_details.call_count == 2
    mock_adapter.fetch_job_details.assert_any_await("http://naukri.com/job-a")
    mock_adapter.fetch_job_details.assert_any_await("http://naukri.com/job-b")
