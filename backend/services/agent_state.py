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

    # E5-R21: stale active states left behind by a failed job (browser start
    # failure, unhandled runner exception) must not poison every subsequent
    # candidate with "Invalid state". AUTH/SECURITY are genuine stop
    # conditions and are never silently recovered.
    _RECOVERABLE_TO_IDLE = {
        AgentState.STOPPED: (AgentState.IDLE,),
        AgentState.RUNNING: (AgentState.STOPPED, AgentState.IDLE),
        AgentState.SEARCHING: (AgentState.STOPPED, AgentState.IDLE),
        AgentState.FILTERING: (AgentState.STOPPED, AgentState.IDLE),
        AgentState.APPLYING: (AgentState.STOPPED, AgentState.IDLE),
        AgentState.PAUSED: (AgentState.STOPPED, AgentState.IDLE),
        AgentState.NEEDS_ATTENTION: (AgentState.STOPPED, AgentState.IDLE),
        AgentState.CRITICAL_ERROR: (AgentState.STOPPED, AgentState.IDLE),
        AgentState.ANALYZING: (AgentState.PAUSED, AgentState.STOPPED, AgentState.IDLE),
        AgentState.AI_QUOTA_EXHAUSTED: (AgentState.STOPPED, AgentState.IDLE),
    }

    def ensure_idle(self) -> bool:
        """Recover to IDLE from a stale non-terminal state.

        Returns True when the manager is IDLE afterwards. Returns False for
        AUTH_REQUIRED / SECURITY_REQUIRED, which must surface to the operator
        instead of being reset.
        """
        if self._state == AgentState.IDLE:
            return True
        path = self._RECOVERABLE_TO_IDLE.get(self._state)
        if path is None:
            return False
        for state in path:
            if self._state != state:
                self._state = state
        return self._state == AgentState.IDLE
