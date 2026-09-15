import json
from typing import Protocol

from pydantic import ValidationError as PydanticValidationError

from backend.core.config import get_settings
from backend.core.exceptions import ProfileExtractionError
from backend.schemas.profile import ProfileData
from backend.services.ai_provider import AIProvider


class ProfileExtractor(Protocol):
    def extract(self, resume_text: str) -> ProfileData: ...


def prepare_resume_text_for_ai(resume_text: str, max_chars: int) -> str:
    normalized = " ".join(resume_text.split())
    if max_chars <= 0 or len(normalized) <= max_chars:
        return normalized

    separator = " ...[TRUNCATED]... "
    if max_chars <= len(separator):
        return normalized[:max_chars]

    remaining = max_chars - len(separator)
    head_chars = int(remaining * 0.7)
    tail_chars = remaining - head_chars
    return f"{normalized[:head_chars]}{separator}{normalized[-tail_chars:]}"


class GeminiProfileExtractor:
    """Delegates to the Centralized GeminiProvider."""

    def extract(self, resume_text: str) -> ProfileData:
        settings = get_settings()
        prepared_text = prepare_resume_text_for_ai(resume_text, settings.profile_extraction_max_chars)
        
        from backend.services.gemini.provider import GeminiProvider
        provider = GeminiProvider()
        
        if not provider.client:
            raise ProfileExtractionError("Profile extraction requires a configured Gemini API key.")
            
        try:
            profile_data = provider.extract_profile(prepared_text)
            if not profile_data:
                raise ProfileExtractionError("The profile extractor returned no structured result.")
            return profile_data
        except ProfileExtractionError:
            raise
        except Exception as exc:
            raise ProfileExtractionError("Profile extraction could not be completed.") from exc


def get_profile_extractor() -> ProfileExtractor:
    return GeminiProfileExtractor()
