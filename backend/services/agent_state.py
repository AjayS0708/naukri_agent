from backend.schemas.agent import AgentState


class AgentStateManager:
    """Phase 1 transition boundary; later phases persist state."""
    _allowed = {
        AgentState.IDLE: {AgentState.RUNNING, AgentState.STOPPED},
        AgentState.RUNNING: {AgentState.SEARCHING, AgentState.PAUSED, AgentState.STOPPED, AgentState.CRITICAL_ERROR},
        AgentState.SEARCHING: {
            AgentState.FILTERING,
            AgentState.PAUSED,
            AgentState.CRITICAL_ERROR,
            AgentState.STOPPED,
            AgentState.AUTH_REQUIRED,
            AgentState.SECURITY_REQUIRED,
        },
        AgentState.FILTERING: {
            AgentState.ANALYZING,
            AgentState.APPLYING,
            AgentState.PAUSED,
            AgentState.CRITICAL_ERROR,
            AgentState.STOPPED,
            AgentState.AUTH_REQUIRED,
            AgentState.SECURITY_REQUIRED,
        },
        AgentState.ANALYZING: {AgentState.APPLYING, AgentState.NEEDS_ATTENTION, AgentState.PAUSED},
        AgentState.APPLYING: {AgentState.RUNNING, AgentState.NEEDS_ATTENTION, AgentState.PAUSED, AgentState.STOPPED, AgentState.CRITICAL_ERROR, AgentState.SECURITY_REQUIRED, AgentState.AUTH_REQUIRED},
        AgentState.PAUSED: {AgentState.RUNNING, AgentState.STOPPED},
        AgentState.AUTH_REQUIRED: {AgentState.PAUSED, AgentState.STOPPED},
        AgentState.SECURITY_REQUIRED: {AgentState.PAUSED, AgentState.STOPPED},
        AgentState.AI_QUOTA_EXHAUSTED: {AgentState.PAUSED, AgentState.RUNNING, AgentState.STOPPED},
        AgentState.NEEDS_ATTENTION: {AgentState.PAUSED, AgentState.RUNNING, AgentState.STOPPED},
        AgentState.STOPPED: {AgentState.IDLE},
        AgentState.CRITICAL_ERROR: {AgentState.STOPPED},
    }

    def __init__(self, initial_state: AgentState = AgentState.IDLE) -> None:
        self._state = initial_state

    @property
    def current_state(self) -> AgentState:
        return self._state

    def transition_to(self, next_state: AgentState) -> None:
        if next_state not in self._allowed[self._state]:
            raise ValueError(f"Cannot transition from {self._state} to {next_state}.")
        self._state = next_state
