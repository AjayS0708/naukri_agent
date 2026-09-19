import pytest

from backend.schemas.agent import AgentState
from backend.services.agent_state import AgentStateManager


def test_agent_state_supports_valid_transition() -> None:
    manager = AgentStateManager()
    manager.transition_to(AgentState.RUNNING)
    assert manager.current_state is AgentState.RUNNING


def test_agent_state_rejects_invalid_transition() -> None:
    with pytest.raises(ValueError):
        AgentStateManager().transition_to(AgentState.APPLYING)


def test_agent_state_supports_discovery_completion_path() -> None:
    manager = AgentStateManager()
    manager.transition_to(AgentState.RUNNING)
    manager.transition_to(AgentState.SEARCHING)
    manager.transition_to(AgentState.FILTERING)
    manager.transition_to(AgentState.STOPPED)
    manager.transition_to(AgentState.IDLE)
    assert manager.current_state is AgentState.IDLE


def test_agent_state_supports_auth_required_from_filtering() -> None:
    manager = AgentStateManager()
    manager.transition_to(AgentState.RUNNING)
    manager.transition_to(AgentState.SEARCHING)
    manager.transition_to(AgentState.FILTERING)
    manager.transition_to(AgentState.AUTH_REQUIRED)
    assert manager.current_state is AgentState.AUTH_REQUIRED
