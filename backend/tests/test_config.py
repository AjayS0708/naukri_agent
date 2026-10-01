from backend.core.config import Settings


def test_settings_have_local_safe_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_host == "127.0.0.1"
    assert settings.database_url.startswith("sqlite")
    assert settings.gemini_api_key is None
    assert settings.gemini_model == "gemini-flash-lite-latest"


def test_gemini_model_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("NAUKRI_AGENT_GEMINI_MODEL", "custom-gemini-model")
    settings = Settings(_env_file=None)
    assert settings.gemini_model == "custom-gemini-model"
