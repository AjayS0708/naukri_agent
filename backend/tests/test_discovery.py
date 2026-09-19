import pytest
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
            }

        adapter_instance.search_jobs = mock_search_jobs
        adapter_instance.platform_name = "naukri"
        yield adapter_instance


@pytest.mark.asyncio
async def test_discovery_run_flow_and_state_transitions(
    state_manager, mock_db_session, mock_adapter
):
    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = ["Bengaluru"]

    # Preferences fetch, then three deduplication lookups (id, url, title+company)
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
    assert isinstance(add_calls[1].args[0], Job)
    assert service.current_run.status == DISCOVERY_STATUS_COMPLETED
    assert service.current_run.jobs_discovered == 1
    assert service.current_run.new_jobs == 1
    assert service.current_run.duplicate_jobs == 0
    assert state_manager.current_state == AgentState.IDLE
    mock_adapter.fetch_job_description.assert_awaited_once_with("http://naukri.com/job")


@pytest.mark.asyncio
async def test_discovery_halts_on_auth_required_exception(
    state_manager, mock_db_session, mock_adapter
):
    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter

    async def mock_search_jobs_with_error(*args, **kwargs):
        yield {"dummy": "data"}
        raise Exception("Naukri login required")

    mock_adapter.search_jobs = mock_search_jobs_with_error

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.job_titles = ["Developer"]
    mock_preferences.locations = []

    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
    ]

    await service.run_discovery(mock_db_session)

    assert service.current_run.status == DISCOVERY_STATUS_AUTH_REQUIRED
    assert service.current_run.error_message == "Naukri login required."
    assert state_manager.current_state == AgentState.AUTH_REQUIRED
