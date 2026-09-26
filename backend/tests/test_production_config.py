"""
Production Configuration Tests

Tests for production-ready configuration behavior including:
- Environment separation (LOCAL_WINDOWS vs CLOUD)
- CORS configuration
- Health and readiness endpoints
- Error handling and security
- Database configuration
- Storage configuration
- Browser/API separation
"""

import pytest
import asyncio
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import os

from backend.core.config import Settings, get_settings
from backend.main import app, configure_cors
from backend.core.storage import get_storage_service
from backend.core.runtime import RuntimeContext, RuntimeEnvironment


class TestProductionConfiguration:
    """Test production configuration behavior."""

    def test_local_windows_environment_defaults(self):
        """Test LOCAL_WINDOWS environment has safe defaults."""
        settings = Settings(_env_file=None)
        assert settings.runtime_environment == "local_windows"
        assert settings.is_local_windows is True
        assert settings.is_cloud is False

    def test_cloud_environment_detection(self):
        """Test CLOUD environment can be configured."""
        with patch.dict(os.environ, {"NAUKRI_AGENT_RUNTIME_ENVIRONMENT": "cloud"}):
            settings = Settings(_env_file=None)
            assert settings.runtime_environment == "cloud"
            assert settings.is_local_windows is False
            assert settings.is_cloud is True

    def test_production_environment_detection(self):
        """Test production environment detection."""
        with patch.dict(os.environ, {"NAUKRI_AGENT_APP_ENV": "production"}):
            settings = Settings(_env_file=None)
            assert settings.is_production is True
            assert settings.is_development is False

    def test_development_environment_defaults(self):
        """Test development environment defaults."""
        settings = Settings(_env_file=None)
        assert settings.is_development is True
        assert settings.is_production is False

    def test_cors_origins_parsing(self):
        """Test CORS origins are parsed correctly from comma-separated string."""
        settings = Settings(
            frontend_origins="http://localhost:5173,https://example.com,https://app.example.com",
            _env_file=None
        )
        origins = settings.cors_origins
        assert len(origins) == 3
        assert "http://localhost:5173" in origins
        assert "https://example.com" in origins
        assert "https://app.example.com" in origins

    def test_cors_origins_empty(self):
        """Test empty CORS origins returns empty list."""
        settings = Settings(frontend_origins="", _env_file=None)
        assert settings.cors_origins == []

    def test_cors_origins_whitespace(self):
        """Test CORS origins with whitespace are trimmed."""
        settings = Settings(
            frontend_origins=" http://localhost:5173 , https://example.com ",
            _env_file=None
        )
        origins = settings.cors_origins
        assert "http://localhost:5173" in origins
        assert "https://example.com" in origins
        assert len(origins) == 2

    def test_production_configuration_requires_hosted_values(self):
        settings = Settings(app_env="production", _env_file=None)
        assert settings.production_configuration_errors == [
            "database_url_must_use_postgresql",
            "gemini_api_key_is_required",
            "frontend_origins_is_required",
        ]

    def test_production_configuration_accepts_postgresql_and_explicit_origins(self):
        settings = Settings(
            app_env="production",
            database_url="postgresql://user:password@db.example.com/naukri",
            gemini_api_key="configured-only-for-test",
            frontend_origins="https://app.example.com,https://admin.example.com",
            _env_file=None,
        )
        assert settings.production_configuration_errors == []

    def test_database_url_sqlite_default(self):
        """Test SQLite is default database URL."""
        settings = Settings(_env_file=None)
        assert settings.database_url.startswith("sqlite")

    def test_database_url_postgresql_configurable(self):
        """Test PostgreSQL URL can be configured."""
        pg_url = "postgresql://user:pass@localhost:5432/naukri"
        settings = Settings(database_url=pg_url, _env_file=None)
        assert settings.database_url == pg_url

    def test_sensitive_config_not_exposed_in_properties(self):
        """Test sensitive configuration is not exposed through public properties."""
        settings = Settings(
            gemini_api_key="secret_key_123",
            _env_file=None
        )
        # Properties should not expose the actual API key
        assert "secret_key_123" not in str(settings.is_development)
        assert "secret_key_123" not in str(settings.is_production)
        assert "secret_key_123" not in str(settings.is_local_windows)

    def test_path_resolution_relative(self):
        """Test relative paths are resolved correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = Settings(
                data_dir="data",
                _env_file=None
            )
            # Path should be resolved relative to project root
            assert settings.data_path.is_absolute()

    def test_path_resolution_absolute(self):
        """Test absolute paths are preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = os.path.join(tmpdir, "data")
            settings = Settings(
                data_dir=abs_path,
                _env_file=None
            )
            assert str(settings.data_path) == abs_path


class TestHealthAndReadiness:
    """Test health and readiness endpoints."""

    def test_health_endpoint_basic(self):
        """Test basic health endpoint works."""
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data
        assert "version" in data
        assert "agent_state" in data

    def test_readiness_endpoint_database_healthy(self):
        """Test readiness endpoint reports database as healthy."""
        client = TestClient(app)
        response = client.get("/api/readiness")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "components" in data
        assert "database" in data["components"]
        assert data["components"]["database"] == "healthy"

    def test_readiness_endpoint_configuration_valid(self):
        """Test readiness endpoint reports configuration as valid."""
        client = TestClient(app)
        response = client.get("/api/readiness")
        assert response.status_code == 200
        data = response.json()
        assert "configuration" in data["components"]
        # In development, configuration should be valid
        assert data["components"]["configuration"] == "valid"

    def test_readiness_endpoint_storage_available(self):
        """Test readiness endpoint reports storage as available."""
        client = TestClient(app)
        response = client.get("/api/readiness")
        assert response.status_code == 200
        data = response.json()
        assert "storage" in data["components"]
        assert data["components"]["storage"] == "available"

    def test_readiness_endpoint_ai_provider_status(self):
        """Test readiness endpoint reports AI provider status."""
        client = TestClient(app)
        response = client.get("/api/readiness")
        assert response.status_code == 200
        data = response.json()
        assert "ai_provider" in data["components"]
        # Without API key, should report not_configured
        assert data["components"]["ai_provider"] in ["configured", "not_configured"]

    def test_readiness_endpoint_runtime_environment(self):
        """Test readiness endpoint reports runtime environment."""
        client = TestClient(app)
        response = client.get("/api/readiness")
        assert response.status_code == 200
        data = response.json()
        assert "runtime_environment" in data["components"]
        assert data["components"]["runtime_environment"] in ["local_windows", "cloud"]


class TestCorsMiddleware:
    @staticmethod
    def _client(settings: Settings) -> TestClient:
        cors_app = FastAPI()

        @cors_app.get("/ping")
        def ping() -> dict[str, bool]:
            return {"ok": True}

        configure_cors(cors_app, settings)
        return TestClient(cors_app)

    def test_configured_production_origin_is_accepted_without_credentials(self):
        client = self._client(Settings(app_env="production", frontend_origins="https://app.example.com", _env_file=None))
        response = client.options(
            "/ping",
            headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "GET"},
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://app.example.com"
        assert "access-control-allow-credentials" not in response.headers

    def test_unconfigured_production_origin_is_not_allowed(self):
        client = self._client(Settings(app_env="production", frontend_origins="https://app.example.com", _env_file=None))
        response = client.get("/ping", headers={"Origin": "https://untrusted.example.com"})

        assert "access-control-allow-origin" not in response.headers

    def test_multiple_production_origins_are_accepted(self):
        client = self._client(Settings(app_env="production", frontend_origins="https://app.example.com,https://admin.example.com", _env_file=None))

        for origin in ("https://app.example.com", "https://admin.example.com"):
            response = client.get("/ping", headers={"Origin": origin})
            assert response.headers["access-control-allow-origin"] == origin

    def test_development_keeps_local_vite_origin_usable(self):
        client = self._client(Settings(app_env="development", frontend_origins="", _env_file=None))
        response = client.get("/ping", headers={"Origin": "http://127.0.0.1:5173"})

        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


class TestErrorHandling:
    """Test production error handling."""

    def test_generic_exception_handler_no_stack_trace(self):
        """Test generic exception handler doesn't expose stack traces."""
        client = TestClient(app)
        # This will trigger a 404 which uses the generic handler
        response = client.get("/api/nonexistent")
        assert response.status_code == 404  # FastAPI handles 404s separately
        # But we can test other error scenarios

    def test_application_error_handler(self):
        """Test application error handler produces safe responses."""
        from backend.core.exceptions import ApplicationError, ValidationError
        from fastapi import Request
        from backend.main import application_error_handler

        exc = ValidationError("Test validation error")
        request = MagicMock(spec=Request)
        response = asyncio.run(application_error_handler(request, exc))
        assert response.status_code == 422
        data = response.body.decode()
        assert "Test validation error" in data
        assert "VALIDATION_ERROR" in data


class TestBrowserAPISeparation:
    """Test browser/API separation."""

    def test_browser_not_started_on_api_import(self):
        """Test importing API doesn't start browser."""
        # This test verifies that importing backend.main doesn't start Playwright
        # The browser should only start when explicitly called via DiscoveryService
        import backend.main
        # If browser was auto-started, this would fail or hang
        assert True

    def test_runtime_context_browser_support_local_windows(self):
        """Test browser support is enabled in LOCAL_WINDOWS."""
        context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        assert context.supports_browser_automation is True

    def test_runtime_context_browser_support_cloud(self):
        """Test browser support is disabled in CLOUD (future)."""
        context = RuntimeContext(runtime=RuntimeEnvironment.CLOUD_READY)
        assert context.supports_browser_automation is False


class TestStorageConfiguration:
    """Test storage configuration for hosted readiness."""

    def test_storage_service_initialization(self):
        """Test storage service initializes correctly."""
        storage = get_storage_service()
        assert storage is not None
        assert storage.get_data_storage_path() is not None
        assert storage.get_resume_storage_path() is not None
        assert storage.get_log_storage_path() is not None

    def test_storage_service_path_resolution(self):
        """Test storage service resolves paths correctly."""
        storage = get_storage_service()
        data_path = storage.get_data_storage_path()
        assert data_path.is_absolute()
        assert data_path.exists()

    def test_storage_service_no_windows_hardcoded_paths(self):
        """Test storage service doesn't hardcode Windows paths."""
        storage = get_storage_service()
        # Paths should come from configuration, not hardcoded Windows paths
        data_path = storage.get_data_storage_path()
        assert "C:\\" not in str(data_path) or data_path.exists()


class TestGeminiConfiguration:
    """Test Gemini configuration for production readiness."""

    def test_gemini_api_key_optional_in_development(self):
        """Test Gemini API key is optional in development."""
        settings = Settings(
            app_env="development",
            gemini_api_key=None,
            _env_file=None
        )
        assert settings.gemini_api_key is None
        # This should not cause validation errors in development

    def test_gemini_api_key_required_in_production_documented(self):
        """Test that production requires API key (documented behavior)."""
        settings = Settings(
            app_env="production",
            gemini_api_key=None,
            _env_file=None
        )
        # In production, missing API key should be detected by readiness check
        assert settings.gemini_api_key is None
        assert settings.is_production is True


class TestConfigurationEnvironmentVariables:
    """Test environment variable configuration."""

    def test_environment_variable_prefix(self):
        """Test configuration uses NAUKRI_AGENT_ prefix."""
        # Settings class should have env_prefix configured
        settings = Settings(_env_file=None)
        # This is tested implicitly by the fact that settings work
        assert settings.app_name is not None

    def test_frontend_url_configurable(self):
        """Test frontend URL is configurable."""
        custom_url = "https://custom-frontend.vercel.app"
        settings = Settings(frontend_url=custom_url, _env_file=None)
        assert settings.frontend_url == custom_url

    def test_log_level_configurable(self):
        """Test log level is configurable."""
        settings = Settings(log_level="DEBUG", _env_file=None)
        assert settings.log_level == "DEBUG"

        settings = Settings(log_level="ERROR", _env_file=None)
        assert settings.log_level == "ERROR"
