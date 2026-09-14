from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Naukri AI Job Application Agent"
    service_slug: str = "naukri-ai-agent"
    app_version: str = "0.1.0"
    app_env: str = Field(default="development")
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite:///./data/naukri_agent.db"
    gemini_api_key: str | None = None
    log_level: str = "INFO"
    frontend_url: str = "http://127.0.0.1:5173"
    resume_storage_dir: Path = PROJECT_ROOT / "data" / "resume"
    max_resume_file_size_bytes: int = 10 * 1024 * 1024
    min_resume_text_chars: int = 80
    gemini_model: str = "gemini-2.0-flash"
    profile_extraction_retries: int = 1

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
