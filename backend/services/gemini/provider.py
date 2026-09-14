from backend.services.ai_provider import AIProvider


class GeminiProvider(AIProvider):
    """Reserved provider boundary. Phase 1 makes no API calls."""
    provider_name = "gemini"
