import logging
from typing import Any, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from backend.core.config import get_settings
from backend.services.ai_provider import AIProvider
from backend.schemas.ai import (
    JobAnalysis, ApplicationAnswer
)
from backend.schemas.profile import ProfileData

logger = logging.getLogger(__name__)

class APIQuotaExhaustedError(Exception):
    pass

class GeminiProvider(AIProvider):
    provider_name = "gemini"

    def __init__(self):
        self.settings = get_settings()
        if not self.settings.gemini_api_key:
            logger.warning("Gemini API key is not configured.")
            self.client = None
        else:
            self.client = genai.Client(
                api_key=self.settings.gemini_api_key, 
                http_options={'timeout': self.settings.gemini_timeout_seconds * 1000}
            )

    def _generate_structured(self, prompt: str, schema: type[BaseModel]) -> Optional[BaseModel]:
        if not self.client:
            logger.error("Attempted to call Gemini but client is not initialized.")
            return None
            
        retries = getattr(self.settings, 'gemini_request_retries', 2)
        for attempt in range(retries):
            try:
                response = self.client.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0.0,
                    ),
                )
                data_json = response.text
                if not data_json:
                    return None
                if data_json.startswith("```json"):
                    data_json = data_json[7:-3].strip()
                elif data_json.startswith("```"):
                    data_json = data_json[3:-3].strip()

                return schema.model_validate_json(data_json)
            except ValidationError as e:
                logger.error(f"Pydantic validation failed on attempt {attempt+1}: {str(e)}")
                # Pydantic errors generally don't get fixed by retrying without prompt updates, but maybe
                if attempt == retries - 1:
                    return None
            except APIQuotaExhaustedError:
                raise
            except Exception as e:
                logger.error(f"Gemini API error on attempt {attempt+1}: {str(e)}")
                if "429" in str(e) or "quota" in str(e).lower():
                    raise APIQuotaExhaustedError("Gemini Quota Exhausted")
                if attempt == retries - 1:
                    return None

    def extract_profile(self, resume_text: str) -> Optional[ProfileData]:
        from backend.services.gemini.prompts import profile_extraction_prompt
        prompt = profile_extraction_prompt(resume_text)
        return self._generate_structured(prompt, ProfileData)

    def analyze_job(self, job_context: str, profile_context: str) -> Optional[JobAnalysis]:
        from backend.services.gemini.prompts import job_analysis_prompt
        prompt = job_analysis_prompt(job_context, profile_context)
        return self._generate_structured(prompt, JobAnalysis)

    def answer_question(self, job_context: str, profile_context: str, question: str) -> Optional[ApplicationAnswer]:
        from backend.services.gemini.prompts import application_answer_prompt
        prompt = application_answer_prompt(job_context, profile_context, question)
        return self._generate_structured(prompt, ApplicationAnswer)
