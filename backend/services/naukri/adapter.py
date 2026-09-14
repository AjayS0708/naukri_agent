from backend.services.platform_adapter import JobPlatformAdapter


class NaukriAdapter(JobPlatformAdapter):
    """Reserved platform boundary. Phase 1 performs no browser interaction."""
    platform_name = "naukri"
