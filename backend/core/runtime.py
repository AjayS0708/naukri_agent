"""
Runtime/Environment Abstraction

This module provides a clean abstraction for different runtime environments.
It distinguishes between local Windows execution and future cloud/server execution.

The purpose is to allow future runtime-specific behavior without scattering
'if cloud' checks throughout the codebase.

V1 Implementation:
- LOCAL_WINDOWS: Current desktop/local application on Windows
- CLOUD_READY: Future server/cloud environment (NOT implemented in V1)

All V1 code should run in LOCAL_WINDOWS mode.
Future cloud deployment will use CLOUD_READY mode with appropriate implementations.
"""

from enum import Enum
from typing import Optional
import sys
import platform

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class RuntimeEnvironment(str, Enum):
    """
    Runtime environment types.
    
    LOCAL_WINDOWS: Desktop application running on Windows (V1 current)
    CLOUD_READY: Server/cloud environment (future, not implemented in V1)
    """
    LOCAL_WINDOWS = "local_windows"
    CLOUD_READY = "cloud_ready"


class RuntimeContext:
    """
    Runtime context providing environment-specific information and behavior.
    
    This class encapsulates runtime-specific logic to avoid scattering
    environment checks throughout the codebase.
    
    V1 Implementation:
    - Detects current runtime (Windows vs others)
    - Provides runtime-specific configuration
    - Future: Will support cloud-specific implementations
    """
    
    def __init__(self, runtime: Optional[RuntimeEnvironment] = None):
        """
        Initialize runtime context.
        
        Args:
            runtime: Explicit runtime (for testing). If None, auto-detects.
        """
        self._runtime = runtime or self._detect_runtime()
        self._settings = get_settings()
        
        logger.info(
            "runtime_context_initialized",
            extra={
                "runtime": self._runtime.value,
                "platform": platform.system(),
                "python_version": sys.version
            }
        )
    
    @property
    def runtime(self) -> RuntimeEnvironment:
        """Get the current runtime environment."""
        return self._runtime
    
    @property
    def is_local_windows(self) -> bool:
        """Check if running in local Windows environment."""
        return self._runtime == RuntimeEnvironment.LOCAL_WINDOWS
    
    @property
    def is_cloud_ready(self) -> bool:
        """Check if running in cloud-ready environment."""
        return self._runtime == RuntimeEnvironment.CLOUD_READY
    
    @property
    def supports_browser_automation(self) -> bool:
        """
        Check if browser automation is supported.
        
        V1: Supported in LOCAL_WINDOWS only.
        Future: May be supported in CLOUD_READY with remote browser.
        """
        return self.is_local_windows
    
    @property
    def supports_windows_autostart(self) -> bool:
        """
        Check if Windows auto-start is supported.
        
        V1: Supported in LOCAL_WINDOWS only.
        Future: Not applicable in cloud environments.
        """
        return self.is_local_windows
    
    @property
    def supports_persistent_browser_session(self) -> bool:
        """
        Check if persistent browser session storage is supported.
        
        V1: Supported in LOCAL_WINDOWS with local filesystem.
        Future: Will need alternative strategy in cloud (object storage, etc.).
        """
        return self.is_local_windows
    
    @property
    def browser_user_data_dir(self) -> Optional[str]:
        """
        Get browser user data directory for persistent sessions.
        
        V1: Returns local filesystem path on Windows.
        Future: Cloud environments will return None (needs remote browser strategy).
        """
        if not self.supports_persistent_browser_session:
            return None
        
        return str(self._settings.browser_user_data_path)
    
    @property
    def data_directory(self) -> str:
        """
        Get the data directory for application data.
        
        V1: Local filesystem path.
        Future: Cloud environments may use object storage or mounted volumes.
        """
        return str(self._settings.data_path)
    
    @property
    def log_directory(self) -> str:
        """
        Get the log directory.
        
        V1: Local filesystem path.
        Future: Cloud environments may use centralized logging.
        """
        return str(self._settings.log_path)
    
    def get_database_url(self) -> str:
        """
        Get the database URL for the current runtime.
        
        V1: Returns configured DATABASE_URL (SQLite by default).
        Future: Cloud environments may use PostgreSQL from environment.
        """
        return self._settings.database_url
    
    def get_storage_path(self, relative_path: str) -> str:
        """
        Get absolute path for a storage-relative path.
        
        Args:
            relative_path: Relative path within storage directory
            
        Returns:
            Absolute path in local filesystem (V1)
            
        Future: Cloud environments will use object storage URLs.
        """
        import os
        return os.path.join(self.data_directory, relative_path)
    
    @staticmethod
    def _detect_runtime() -> RuntimeEnvironment:
        """
        Auto-detect the current runtime environment.
        
        V1: Returns LOCAL_WINDOWS if on Windows, otherwise LOCAL_WINDOWS (fallback).
        Future: Will detect cloud environment via environment variables.
        """
        # V1: Always treat as LOCAL_WINDOWS
        # Future: Check for cloud-specific environment variables
        # e.g., os.getenv("CLOUD_ENVIRONMENT") or os.getenv("KUBERNETES_SERVICE_HOST")
        
        if platform.system() == "Windows":
            return RuntimeEnvironment.LOCAL_WINDOWS
        
        # Fallback to LOCAL_WINDOWS for development on other platforms
        # In production cloud, this would be detected via environment variables
        return RuntimeEnvironment.LOCAL_WINDOWS


# Global runtime context instance
_runtime_context: Optional[RuntimeContext] = None


def get_runtime_context() -> RuntimeContext:
    """
    Get the global runtime context instance.
    
    Returns:
        RuntimeContext: The singleton runtime context
    """
    global _runtime_context
    if _runtime_context is None:
        _runtime_context = RuntimeContext()
    return _runtime_context


def set_runtime_context(runtime: RuntimeEnvironment) -> None:
    """
    Set the runtime context explicitly (for testing).
    
    Args:
        runtime: The runtime environment to set
    """
    global _runtime_context
    _runtime_context = RuntimeContext(runtime=runtime)
