import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from sqlalchemy.orm import Session

from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager
from backend.services.discovery.service import DiscoveryService
from backend.models.discovery import DiscoveryRun
from backend.models.job import Job
from backend.models.matching import JobPreference
from backend.schemas.matching import DailyLimitConfig

@pytest.fixture
def mock_db_session():
    mock = MagicMock(spec=Session)
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
                 "salary": "10-15 LPA"
             }
        
        adapter_instance.search_jobs = mock_search_jobs
        adapter_instance.platform_name = "naukri"
        yield adapter_instance


@pytest.mark.asyncio
async def test_discovery_run_flow_and_state_transitions(state_manager, mock_db_session, mock_adapter):
    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter
    
    # Setup mock db side-effects
    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.target_roles = ["Developer"]
    mock_preferences.locations = ["Bengaluru"]
    
    # Return mock preferences on first execute (preferences fetch)
    # Return no existing job on second execute (deduplication check)
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
        mock_preferences,
        None, 
    ]
    
    await service.run_discovery(mock_db_session)
    
    # Assert DB got a discovery run added and updated
    assert mock_db_session.add.call_count == 2
    assert service.current_run.status == AgentState.IDLE
    assert service.current_run.new_jobs == 1


@pytest.mark.asyncio
async def test_discovery_halts_on_auth_required_exception(state_manager, mock_db_session, mock_adapter):
    service = DiscoveryService(state_manager)
    service.adapter = mock_adapter
    
    # Mock adapter to raise security exception during search generator
    async def mock_search_jobs_with_error(*args, **kwargs):
         yield {"dummy": "data"} 
         raise Exception("Naukri login required")
         
    mock_adapter.search_jobs = mock_search_jobs_with_error

    mock_preferences = MagicMock(spec=JobPreference)
    mock_preferences.target_roles = ["Developer"]
    
    mock_db_session.execute.return_value.scalars.return_value.first.side_effect = [
         mock_preferences, 
         None
    ]

    await service.run_discovery(mock_db_session)
    assert service.current_run.status == AgentState.AUTH_REQUIRED
    assert state_manager.current_state == AgentState.AUTH_REQUIRED
