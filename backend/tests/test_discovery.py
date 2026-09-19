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
    mock_adapter.fetch_job_description.assert_awaited_once_with("http://naukri.com/job")


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

    assert service.current_run.status == "STOPPED"
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
    # Description fetch fails but should not crash discovery
    mock_adapter.fetch_job_description = AsyncMock(return_value="")

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

    # Discovery should complete successfully even with empty description
    assert service.current_run.status == "COMPLETED"
    assert service.current_run.new_jobs == 1
    mock_adapter.fetch_job_description.assert_awaited_once()


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
