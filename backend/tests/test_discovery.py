import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from sqlalchemy.orm import Session

from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.services.discovery.service import DiscoveryService
from backend.models.discovery import DiscoveryRun
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


@pytest.fixture
def mock_match_engine():
    with patch("backend.services.discovery.service.MatchEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.evaluate_job = MagicMock()
        yield engine_instance


@pytest.mark.asyncio
async def test_discovery_run_flow_and_state_transitions(
    state_manager, mock_db_session, mock_adapter, mock_match_engine
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

    assert mock_db_session.add.call_count == 2
    assert service.current_run.status == AgentState.IDLE
    assert service.current_run.new_jobs == 1
    mock_match_engine.evaluate_job.assert_called_once()


@pytest.mark.asyncio
async def test_discovery_halts_on_auth_required_exception(
    state_manager, mock_db_session, mock_adapter, mock_match_engine
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

    assert service.current_run.status == AgentState.AUTH_REQUIRED
    assert service.current_run.error_message == "Naukri login required."
    # AgentStateManager does not yet allow SEARCHING -> AUTH_REQUIRED (Step 4 scope).
    assert state_manager.current_state == AgentState.SEARCHING
