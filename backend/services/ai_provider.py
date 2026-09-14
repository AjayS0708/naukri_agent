from abc import ABC


class AIProvider(ABC):
    """Controlled reasoning boundary; providers never receive browser control."""
    provider_name: str
