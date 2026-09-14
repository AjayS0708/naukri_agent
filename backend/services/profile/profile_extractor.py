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


class GeminiProfileExtractor(AIProvider):
    """Narrow, source-grounded Gemini integration reserved for profile extraction."""

    provider_name = "gemini"

    def extract(self, resume_text: str) -> ProfileData:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise ProfileExtractionError("Profile extraction requires a configured Gemini API key.")
        prepared_text = prepare_resume_text_for_ai(resume_text, settings.profile_extraction_max_chars)
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=(
                    "Extract only facts explicitly stated in this resume. Return JSON matching the provided schema. "
                    "Never infer, normalize into a more specific value, or add related skills. Use null or [] for missing facts.\n\n"
                    f"RESUME:\n{prepared_text}"
                ),
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            if not response.text:
                raise ProfileExtractionError("The profile extractor returned no structured result.")
            return ProfileData.model_validate(json.loads(response.text))
        except ProfileExtractionError:
            raise
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            raise ProfileExtractionError("The profile extractor returned invalid structured data.") from exc
        except Exception as exc:
            raise ProfileExtractionError("Profile extraction could not be completed.") from exc


def get_profile_extractor() -> ProfileExtractor:
    return GeminiProfileExtractor()
