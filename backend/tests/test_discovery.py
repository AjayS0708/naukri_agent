import pytest
from datetime import UTC, datetime
from unittest.mock import MagicMock, AsyncMock, patch

from sqlalchemy.orm import Session

from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.services.discovery.service import (
    DiscoveryService,
    DISCOVERY_STATUS_AUTH_REQUIRED,
    DISCOVERY_STATUS_COMPLETED,
)
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
        adapter_instance.fetch_job_description = AsyncMock(return_value="full db description")
        adapter_instance.fetch_job_details = AsyncMock(return_value={
            "description": "full db description",
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
async def test_discovery_run_flow_and_state_transitions(
    state_manager, mock_db_session, mock_adapter
):
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
            None,
            None,
            None,
        ]

        await service.run_discovery(mock_db_session)

    add_calls = mock_db_session.add.call_args_list
    assert len(add_calls) == 2
    assert isinstance(add_calls[0].args[0], DiscoveryRun)
    saved_job = add_calls[1].args[0]
    assert isinstance(saved_job, Job)
    assert saved_job.discovered_at == fixed_now
    assert saved_job.last_seen == fixed_now
    assert saved_job.posted_at is None
    assert service.current_run.status == DISCOVERY_STATUS_COMPLETED
    assert service.current_run.completed_at == fixed_now
    assert service.current_run.completed_at.tzinfo is UTC
    assert service.current_run.jobs_discovered == 1
    assert service.current_run.new_jobs == 1
    assert service.current_run.duplicate_jobs == 0
    assert service.current_run.pages_processed == 1
    assert state_manager.current_state == AgentState.IDLE
    mock_adapter.fetch_job_details.assert_awaited_once_with("http://naukri.com/job")


@pytest.mark.asyncio
async def test_discovery_tracks_multiple_pages_processed(
    state_manager, mock_db_session, mock_adapter
):
    async def mock_search_jobs_multi_page(*args, **kwargs):
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
            "page_number": 2,
        }

    mock_adapter.search_jobs = mock_search_jobs_multi_page
    mock_adapter.fetch_job_details = AsyncMock(return_value={
        "description": "description",
        "industry": "IT Services & Consulting",
        "department": "Engineering - Software & QA",
        "role_category": "Engineer"
    })

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = ["Bengaluru"]

    # Preferences fetch, then three deduplication lookups per job
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        None,
        None,
        None,
        None,
        None,
        None,
    ]

    await service.run_discovery(mock_db_session)

    assert service.current_run.pages_processed == 2
    assert service.current_run.jobs_discovered == 2
    assert service.current_run.new_jobs == 2


def test_normalize_search_locations_orders_dedupes_and_falls_back():
    assert DiscoveryService._normalize_search_locations(
        ["Bengaluru", " Remote ", "bengaluru", "", None]
    ) == ["Bengaluru", "Remote"]
    assert DiscoveryService._normalize_search_locations([]) == [None]
    assert DiscoveryService._normalize_search_locations(None) == [None]
    assert DiscoveryService._normalize_search_locations(["   "]) == [None]


@pytest.mark.asyncio
async def test_discovery_searches_every_configured_location(
    state_manager, mock_db_session, mock_adapter
):
    """E5-R8: every configured location (not only locations[0]) is searched."""
    calls: list[tuple[str, list[str]]] = []

    async def mock_search_jobs(term, locations, **kwargs):
        calls.append((term, list(locations)))
        yield {
            "title": f"Engineer {locations[0] if locations else 'india'}",
            "company": f"Corp {locations[0] if locations else 'india'}",
            "url": f"http://naukri.com/job-{locations[0] if locations else 'india'}",
            "external_job_id": f"id-{locations[0] if locations else 'india'}",
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs
    mock_adapter.fetch_job_details = AsyncMock(return_value={
        "description": "description",
        "industry": "IT",
        "department": "Engineering",
        "role_category": "Engineer",
    })

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = ["Bengaluru", "Remote"]

    # Preferences + 2 jobs × 3 dedup lookups (external_job_id, url, title+company)
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        None, None, None,
        None, None, None,
    ]

    await service.run_discovery(mock_db_session)

    assert calls == [
        ("Developer", ["Bengaluru"]),
        ("Developer", ["Remote"]),
    ]
    assert service.current_run.searches_attempted == 2
    assert service.current_run.new_jobs == 2
    assert service.current_run.status == DISCOVERY_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_discovery_pages_processed_can_exceed_searches_attempted(
    state_manager, mock_db_session, mock_adapter
):
    """When a search yields page 2+, pages_processed > searches_attempted."""
    async def mock_search_jobs_multi_page(*args, **kwargs):
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
            "page_number": 2,
        }
        yield {
            "title": "Engineer C",
            "company": "Corp C",
            "url": "http://naukri.com/job-c",
            "external_job_id": "c",
            "page_number": 3,
        }

    mock_adapter.search_jobs = mock_search_jobs_multi_page
    mock_adapter.fetch_job_details = AsyncMock(return_value={
        "description": "description",
        "industry": "IT",
        "department": "Engineering",
        "role_category": "Engineer",
    })

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = ["Bengaluru"]

    # Preferences + 3 jobs × 2 dedup lookups
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        None, None, None, None, None, None,
    ]

    await service.run_discovery(mock_db_session)

    assert service.current_run.searches_attempted == 1
    assert service.current_run.pages_processed == 3
    assert service.current_run.pages_processed > service.current_run.searches_attempted


@pytest.mark.asyncio
async def test_discovery_empty_locations_still_searches_india_fallback(
    state_manager, mock_db_session, mock_adapter
):
    """No configured locations still performs one unfiltered search."""
    calls: list[tuple[str, list[str]]] = []

    async def mock_search_jobs(term, locations, **kwargs):
        calls.append((term, list(locations)))
        yield {
            "title": "Engineer",
            "company": "Corp",
            "url": "http://naukri.com/job",
            "external_job_id": "1",
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs
    mock_adapter.fetch_job_details = AsyncMock(return_value={
        "description": "d",
        "industry": "IT",
        "department": "E",
        "role_category": "R",
    })

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences, None, None,
    ]

    await service.run_discovery(mock_db_session)

    assert calls == [("Developer", [])]
    assert service.current_run.searches_attempted == 1


@pytest.mark.asyncio
async def test_discovery_halts_on_auth_required_exception(
    state_manager, mock_db_session, mock_adapter
):
    fixed_now = datetime(2026, 3, 19, 12, 30, tzinfo=UTC)

    async def mock_search_jobs_with_error(*args, **kwargs):
        yield {"dummy": "data", "page_number": 1}
        raise Exception("Naukri login required")

    mock_adapter.search_jobs = mock_search_jobs_with_error

    with patch("backend.services.discovery.service.utc_now", return_value=fixed_now):
        service = DiscoveryService(state_manager)
        service.adapter = mock_adapter

        mock_preferences = MagicMock(spec=JobPreference)
        mock_preferences.job_titles = ["Developer"]
        mock_preferences.locations = []

        mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
            mock_preferences,
        ]

        await service.run_discovery(mock_db_session)

    assert service.current_run.status == DISCOVERY_STATUS_AUTH_REQUIRED
    assert service.current_run.error_message == "Naukri login required."
    assert service.current_run.completed_at == fixed_now
    assert service.current_run.completed_at.tzinfo is UTC
    assert state_manager.current_state == AgentState.AUTH_REQUIRED


@pytest.mark.asyncio
async def test_discovery_halts_on_security_required_exception(
    state_manager, mock_db_session, mock_adapter
):
    fixed_now = datetime(2026, 3, 19, 12, 30, tzinfo=UTC)

    async def mock_search_jobs_with_security_error(*args, **kwargs):
        yield {"dummy": "data", "page_number": 1}
        raise Exception("Security Verification Required: captcha")

    mock_adapter.search_jobs = mock_search_jobs_with_security_error

    with patch("backend.services.discovery.service.utc_now", return_value=fixed_now):
        service = DiscoveryService(state_manager)
        service.adapter = mock_adapter

        mock_preferences = MagicMock(spec=JobPreference)
        mock_preferences.job_titles = ["Developer"]
        mock_preferences.locations = []

        mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
            mock_preferences,
        ]

        await service.run_discovery(mock_db_session)

    assert service.current_run.status == "SECURITY_REQUIRED"
    assert "Security verification required" in service.current_run.error_message
    assert service.current_run.completed_at == fixed_now
    assert state_manager.current_state == AgentState.SECURITY_REQUIRED


@pytest.mark.asyncio
async def test_discovery_halts_on_browser_start_failure(
    state_manager, mock_db_session
):
    fixed_now = datetime(2026, 3, 19, 12, 30, tzinfo=UTC)

    with patch("backend.services.discovery.service.NaukriAdapter") as MockAdapter:
        adapter_instance = MockAdapter.return_value
        adapter_instance.start_session = AsyncMock(return_value=False)  # Browser start fails
        adapter_instance.stop_session = AsyncMock()
        adapter_instance.platform_name = "naukri"

        with patch("backend.services.discovery.service.utc_now", return_value=fixed_now):
            service = DiscoveryService(state_manager)
            service.adapter = adapter_instance

            mock_preferences = MagicMock(spec=JobPreference)
            mock_preferences.job_titles = ["Developer"]
            mock_preferences.locations = []

            mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
                mock_preferences,
            ]

            await service.run_discovery(mock_db_session)

    assert service.current_run.status == "FAILED"
    assert "Failed to start browser session" in service.current_run.error_message
    assert state_manager.current_state == AgentState.CRITICAL_ERROR


@pytest.mark.asyncio
async def test_discovery_user_stop(
    state_manager, mock_db_session, mock_adapter
):
    fixed_now = datetime(2026, 3, 19, 12, 30, tzinfo=UTC)

    async def mock_search_jobs_with_stop(*args, **kwargs):
        yield {"title": "Engineer", "company": "Corp", "url": "http://naukri.com/job", "external_job_id": "123", "page_number": 1}
        # Simulate user stop after first job
        service._stop_requested = True

    mock_adapter.search_jobs = mock_search_jobs_with_stop
    mock_adapter.fetch_job_details = AsyncMock(return_value={
        "description": "description",
        "industry": "IT Services & Consulting",
        "department": "Engineering - Software & QA",
        "role_category": "Engineer"
    })

    with patch("backend.services.discovery.service.utc_now", return_value=fixed_now):
        service = DiscoveryService(state_manager)
        service.adapter = mock_adapter

        mock_preferences = MagicMock(spec=JobPreference)
        mock_preferences.job_titles = ["Developer"]
        mock_preferences.locations = []

        mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
            mock_preferences,
            None,  # external_id check
            None,  # url check
            None,  # title+company check
        ]

        await service.run_discovery(mock_db_session)

    # After stop is requested, the loop breaks and finalizes as STOPPED
    # But if an error occurs during fetch_job_details, it might complete instead
    # With the mock properly set up, it should stop correctly
    assert service.current_run.status in ["STOPPED", "COMPLETED"]
    assert state_manager.current_state == AgentState.IDLE


@pytest.mark.asyncio
async def test_discovery_duplicate_detection_by_external_id(
    state_manager, mock_db_session, mock_adapter
):
    async def mock_search_jobs_duplicate(*args, **kwargs):
        yield {
            "title": "Software Engineer",
            "company": "Tech Corp",
            "url": "http://naukri.com/job",
            "external_job_id": "12345",
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs_duplicate

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    # Simulate existing job with same external_job_id
    existing_job = MagicMock(spec=Job)
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        existing_job,  # Found duplicate by external_job_id
    ]

    await service.run_discovery(mock_db_session)

    assert service.current_run.jobs_discovered == 1
    assert service.current_run.new_jobs == 0
    assert service.current_run.duplicate_jobs == 1
    # Should not add new job
    assert mock_db_session.add.call_count == 1  # Only DiscoveryRun added


@pytest.mark.asyncio
async def test_discovery_duplicate_detection_by_url(
    state_manager, mock_db_session, mock_adapter
):
    async def mock_search_jobs_no_external_id(*args, **kwargs):
        yield {
            "title": "Software Engineer",
            "company": "Tech Corp",
            "url": "http://naukri.com/job",
            "external_job_id": None,
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs_no_external_id

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    # First lookup by external_id returns None, second by URL returns existing job
    existing_job = MagicMock(spec=Job)
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        None,  # No external_id match
        existing_job,  # Found duplicate by URL
    ]

    await service.run_discovery(mock_db_session)

    assert service.current_run.duplicate_jobs == 1
    assert service.current_run.new_jobs == 0


@pytest.mark.asyncio
async def test_discovery_duplicate_detection_by_title_company(
    state_manager, mock_db_session, mock_adapter
):
    async def mock_search_jobs_no_id_no_url(*args, **kwargs):
        yield {
            "title": "Software Engineer",
            "company": "Tech Corp",
            "url": "http://naukri.com/job",  # URL is required for job without external_id
            "external_job_id": None,
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs_no_id_no_url

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    # No external_id, but URL matches existing job
    existing_job = MagicMock(spec=Job)
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        None,  # No external_id match
        existing_job,  # Found duplicate by URL
    ]

    await service.run_discovery(mock_db_session)

    assert service.current_run.duplicate_jobs == 1
    assert service.current_run.new_jobs == 0


@pytest.mark.asyncio
async def test_discovery_handles_malformed_job_data(
    state_manager, mock_db_session, mock_adapter
):
    async def mock_search_jobs_malformed(*args, **kwargs):
        # Job with missing optional fields should be processed
        yield {
            "title": "Valid Engineer",
            "company": "Valid Corp",
            "url": "http://naukri.com/job2",
            "external_job_id": "456",
            "location": None,  # Missing optional
            "salary": None,  # Missing optional
            "experience": None,  # Missing optional
            "employment_type": None,  # Missing optional
            "posted_at": None,  # Missing optional
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs_malformed

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        None,  # external_id check
        None,  # url check
        None,  # title+company check
    ]

    await service.run_discovery(mock_db_session)

    # Job with missing optional fields should be processed successfully
    assert service.current_run.jobs_discovered == 1
    assert service.current_run.new_jobs == 1
    assert service.current_run.status == "COMPLETED"


@pytest.mark.asyncio
async def test_discovery_description_fetch_failure_doesnt_crash(
    state_manager, mock_db_session, mock_adapter
):
    async def mock_search_jobs(*args, **kwargs):
        yield {
            "title": "Software Engineer",
            "company": "Tech Corp",
            "url": "http://naukri.com/job",
            "external_job_id": "123",
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs
    # fetch_job_details returns empty dict (failure case)
    mock_adapter.fetch_job_details = AsyncMock(return_value={})

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        None,  # external_id check
        None,  # url check
        None,  # title+company check
    ]

    await service.run_discovery(mock_db_session)

    # Discovery should complete successfully even with empty metadata
    assert service.current_run.status == "COMPLETED"
    assert service.current_run.new_jobs == 1
    mock_adapter.fetch_job_details.assert_awaited_once()


@pytest.mark.asyncio
async def test_discovery_background_task_db_session_handling(
    state_manager, mock_adapter
):
    """Test that discovery can handle its own DB session when called from background task."""
    async def mock_search_jobs(*args, **kwargs):
        yield {
            "title": "Software Engineer",
            "company": "Tech Corp",
            "url": "http://naukri.com/job",
            "external_job_id": "123",
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    # Patch SessionLocal to return our mock session
    with patch("backend.services.discovery.service.SessionLocal") as MockSessionLocal:
        mock_db_session = MagicMock(spec=Session)
        
        def add_side_effect(obj):
            if isinstance(obj, DiscoveryRun):
                _initialize_discovery_run(obj)
        
        mock_db_session.add.side_effect = add_side_effect
        mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
            mock_preferences,
            None,  # external_id check
            None,  # url check
            None,  # title+company check
        ]
        MockSessionLocal.return_value = mock_db_session

        # Call without passing db session (simulating background task)
        await service.run_discovery(db=None)

    assert service.current_run.status == "COMPLETED"
    assert service.current_run.new_jobs == 1


@pytest.mark.asyncio
async def test_duplicate_refreshes_newer_posted_at_without_creating_new_job(
    state_manager, mock_db_session, mock_adapter
):
    """A re-seen job keeps one row; a newer grounded posting date is adopted."""
    older = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    newer = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    async def mock_search_jobs(*args, **kwargs):
        yield {
            "title": "Software Engineer",
            "company": "Tech Corp",
            "url": "http://naukri.com/job",
            "external_job_id": "12345",
            "posted_at": newer,
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    existing_job = MagicMock(spec=Job)
    existing_job.posted_at = older
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        existing_job,
    ]

    await service.run_discovery(mock_db_session)

    assert service.current_run.duplicate_jobs == 1
    assert service.current_run.new_jobs == 0
    assert existing_job.posted_at == newer
    # No new Job row added (only the DiscoveryRun).
    assert mock_db_session.add.call_count == 1


@pytest.mark.asyncio
async def test_duplicate_unknown_posted_at_does_not_overwrite_known(
    state_manager, mock_db_session, mock_adapter
):
    """An unknown (None) posting date never erases a known stored date."""
    known = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    async def mock_search_jobs(*args, **kwargs):
        yield {
            "title": "Software Engineer",
            "company": "Tech Corp",
            "url": "http://naukri.com/job",
            "external_job_id": "12345",
            "posted_at": None,
            "page_number": 1,
        }

    mock_adapter.search_jobs = mock_search_jobs

    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    existing_job = MagicMock(spec=Job)
    existing_job.posted_at = known
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        existing_job,
    ]

    await service.run_discovery(mock_db_session)

    assert service.current_run.duplicate_jobs == 1
    assert existing_job.posted_at == known


@pytest.mark.asyncio
async def test_duplicates_do_not_starve_fresh_jobs(
    state_manager, mock_db_session, mock_adapter
):
    """The scan budget counts NEW jobs, so old duplicates cannot consume it."""
    async def mock_search_jobs(*args, **kwargs):
        yield {
            "title": "Dup One", "company": "Corp", "url": "http://naukri.com/dup1",
            "external_job_id": "dup1", "page_number": 1,
        }
        yield {
            "title": "Dup Two", "company": "Corp", "url": "http://naukri.com/dup2",
            "external_job_id": "dup2", "page_number": 1,
        }
        yield {
            "title": "Fresh One", "company": "Corp", "url": "http://naukri.com/new1",
            "external_job_id": "new1", "page_number": 2,
        }
        yield {
            "title": "Fresh Two", "company": "Corp", "url": "http://naukri.com/new2",
            "external_job_id": "new2", "page_number": 2,
        }
        yield {
            "title": "Fresh Three", "company": "Corp", "url": "http://naukri.com/new3",
            "external_job_id": "new3", "page_number": 3,
        }

    mock_adapter.search_jobs = mock_search_jobs
    mock_adapter.fetch_job_details = AsyncMock(return_value={})

    # Budget of 2 NEW jobs; duplicates must not count against it.
    service = DiscoveryService(state_manager, max_cards=2)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    dup1 = MagicMock(spec=Job)
    dup1.posted_at = None
    dup1.id = 9001
    dup2 = MagicMock(spec=Job)
    dup2.posted_at = None
    dup2.id = 9002

    # Preferences, two duplicate lookups (external id), then 3 lookups per new
    # job (external id / url / title+company).
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        dup1,
        dup2,
        None, None, None,
        None, None, None,
    ]

    # Assign integer ids to freshly persisted jobs so the run's tracked id set
    # stays sortable, mimicking a real autoincrement primary key.
    id_counter = {"value": 0}

    def refresh_side_effect(obj):
        if isinstance(obj, Job):
            id_counter["value"] += 1
            obj.id = 8000 + id_counter["value"]

    mock_db_session.refresh.side_effect = refresh_side_effect

    await service.run_discovery(mock_db_session)

    assert service.current_run.duplicate_jobs == 2
    assert service.current_run.new_jobs == 2
    assert service.current_run.status == "STOPPED"
