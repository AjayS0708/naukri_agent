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
