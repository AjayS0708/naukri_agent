import json
from typing import Protocol

from pydantic import ValidationError as PydanticValidationError

from backend.core.config import get_settings
from backend.core.exceptions import ProfileExtractionError
from backend.schemas.profile import ProfileData
from backend.services.ai_provider import AIProvider


class ProfileExtractor(Protocol):
    def extract(self, resume_text: str) -> ProfileData: ...


class GeminiProfileExtractor(AIProvider):
    """Narrow, source-grounded Gemini integration reserved for profile extraction."""

    provider_name = "gemini"

    def extract(self, resume_text: str) -> ProfileData:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise ProfileExtractionError("Profile extraction requires a configured Gemini API key.")
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=settings.gemini_api_key)
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=(
                    "Extract only facts explicitly stated in this resume. Return JSON matching the provided schema. "
                    "Never infer, normalize into a more specific value, or add related skills. Use null or [] for missing facts.\n\n"
                    f"RESUME:\n{resume_text}"
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
