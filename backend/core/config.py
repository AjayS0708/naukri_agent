from functools import lru_cache
from pathlib import Path
import os

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

    # Runtime environment - supports LOCAL_WINDOWS (V1) and CLOUD (future)
    runtime_environment: str = Field(default="local_windows")

    # Database configuration - environment variable driven
    # Can be SQLite (sqlite:///./data/naukri_agent.db) or PostgreSQL (postgresql://user:pass@host/db)
    database_url: str = Field(default="sqlite:///./data/naukri_agent.db")

    # API keys - must be configured via environment variables in production
    gemini_api_key: str | None = Field(default=None)

    # Logging configuration
    log_level: str = Field(default="INFO")

    # Frontend configuration - supports multiple origins for CORS
    frontend_url: str = Field(default="http://127.0.0.1:5173")
    frontend_origins: str = Field(default="")  # Comma-separated list for CORS

    # Storage directories - environment variable driven
    # Can be absolute paths or relative to PROJECT_ROOT
    data_dir: str = Field(default="data")
    resume_storage_dir: str = Field(default="data/resume")
    log_dir: str = Field(default="data/logs")

    # AI configuration
    gemini_model: str = Field(default="gemini-2.0-flash")
    profile_extraction_retries: int = Field(default=1)
    profile_extraction_max_chars: int = Field(default=12000)
    gemini_timeout_seconds: float = Field(default=20.0)
    gemini_request_retries: int = Field(default=2)
    ai_cache_enabled: bool = Field(default=True)

    # Browser configuration
    browser_type: str = Field(default="chrome")
    browser_user_data_dir: str = Field(default=".agent/browser_session")

    # Scheduler configuration
    scheduler_enabled: bool = Field(default=True)
    scheduler_interval_minutes: int = Field(default=60)
    scheduler_max_instances: int = Field(default=1)

    # Application limits
    max_resume_file_size_bytes: int = Field(default=10 * 1024 * 1024)
    min_resume_text_chars: int = Field(default=80)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="NAUKRI_AGENT_"  # Prefix all environment variables
    )

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def is_local_windows(self) -> bool:
        return self.runtime_environment.lower() == "local_windows"

    @property
    def is_cloud(self) -> bool:
        return self.runtime_environment.lower() == "cloud"

    @property
    def cors_origins(self) -> list[str]:
        """Get list of CORS origins from comma-separated string."""
        origins_str = self.frontend_origins.strip()
        if not origins_str:
            return []
        return [origin.strip() for origin in origins_str.split(",") if origin.strip()]

    @property
    def production_configuration_errors(self) -> list[str]:
        """Return safe, actionable readiness errors for hosted production."""
        if not self.is_production:
            return []

        errors: list[str] = []
        if not self.database_url.startswith("postgresql"):
            errors.append("database_url_must_use_postgresql")
        if not self.gemini_api_key:
            errors.append("gemini_api_key_is_required")
        if not self.cors_origins:
            errors.append("frontend_origins_is_required")
        if "*" in self.cors_origins:
            errors.append("frontend_origins_must_not_include_wildcard")
        return errors

    @property
    def resume_storage_path(self) -> Path:
        """Get resolved resume storage path (absolute)."""
        path_str = self.resume_storage_dir
        if os.path.isabs(path_str):
            return Path(path_str)
        return PROJECT_ROOT / path_str

    @property
    def data_path(self) -> Path:
        """Get resolved data directory path (absolute)."""
        path_str = self.data_dir
        if os.path.isabs(path_str):
            return Path(path_str)
        return PROJECT_ROOT / path_str

    @property
    def log_path(self) -> Path:
        """Get resolved log directory path (absolute)."""
        path_str = self.log_dir
        if os.path.isabs(path_str):
            return Path(path_str)
        return PROJECT_ROOT / path_str

    @property
    def browser_user_data_path(self) -> Path:
        """Get resolved browser user data path (absolute)."""
        path_str = self.browser_user_data_dir
        if os.path.isabs(path_str):
            return Path(path_str)
        return PROJECT_ROOT / path_str


@lru_cache
def get_settings() -> Settings:
    return Settings()
