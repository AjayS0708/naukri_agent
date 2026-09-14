from backend.core.config import Settings


def test_settings_have_local_safe_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_host == "127.0.0.1"
    assert settings.database_url.startswith("sqlite")
    assert settings.gemini_api_key is None
