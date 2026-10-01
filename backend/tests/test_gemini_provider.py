from types import SimpleNamespace

from backend.schemas.ai import AIRecommendation
from backend.services.gemini.provider import GeminiProvider


class FakeModels:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.model = None

    def generate_content(self, *, model, contents, config):
        self.model = model
        return SimpleNamespace(text=self.response_text)


def test_provider_passes_configured_model_and_parses_job_analysis() -> None:
    response = (
        '{"match_score":85,"role_match":true,"skill_match":true,'
        '"experience_match":true,"location_match":true,"salary_match":true,'
        '"job_quality":"GOOD","duplicate_probability":0.1,"suspicious":false,'
        '"recommendation":"APPLY","short_reason":"Strong skills match"}'
    )
    fake_models = FakeModels(response)
    provider = GeminiProvider.__new__(GeminiProvider)
    provider.client = SimpleNamespace(models=fake_models)
    provider.settings = SimpleNamespace(
        gemini_model="gemini-flash-lite-latest",
        gemini_request_retries=1,
    )

    result = provider.analyze_job("minimal job", "minimal profile")

    assert fake_models.model == "gemini-flash-lite-latest"
    assert result is not None
    assert result.recommendation is AIRecommendation.APPLY
    assert result.match_score == 85
