from abc import ABC


class JobPlatformAdapter(ABC):
    """Boundary for future platform-specific discovery and application behavior."""
    platform_name: str
