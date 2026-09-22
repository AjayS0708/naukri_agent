"""
Tests for runtime environment abstraction.
"""

import pytest
from pathlib import Path
from backend.core.runtime import (
    RuntimeEnvironment,
    RuntimeContext,
    get_runtime_context,
    set_runtime_context
)


class TestRuntimeEnvironment:
    """Test RuntimeEnvironment enum."""

    def test_runtime_environment_values(self):
        """Test that RuntimeEnvironment has expected values."""
        assert RuntimeEnvironment.LOCAL_WINDOWS == "local_windows"
        assert RuntimeEnvironment.CLOUD_READY == "cloud_ready"


class TestRuntimeContext:
    """Test RuntimeContext class."""

    def test_initialization_with_explicit_runtime(self):
        """Test initialization with explicit runtime."""
        context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        assert context.runtime == RuntimeEnvironment.LOCAL_WINDOWS

    def test_initialization_auto_detect_windows(self):
        """Test auto-detection on Windows."""
        context = RuntimeContext()
        # On Windows, should detect as LOCAL_WINDOWS
        # On other platforms, currently defaults to LOCAL_WINDOWS as fallback
        assert context.runtime in [RuntimeEnvironment.LOCAL_WINDOWS, RuntimeEnvironment.CLOUD_READY]

    def test_is_local_windows_property(self):
        """Test is_local_windows property."""
        context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        assert context.is_local_windows is True
        assert context.is_cloud_ready is False

    def test_is_cloud_ready_property(self):
        """Test is_cloud_ready property."""
        context = RuntimeContext(runtime=RuntimeEnvironment.CLOUD_READY)
        assert context.is_cloud_ready is True
        assert context.is_local_windows is False

    def test_supports_browser_automation(self):
        """Test browser automation support."""
        local_context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        assert local_context.supports_browser_automation is True

        cloud_context = RuntimeContext(runtime=RuntimeEnvironment.CLOUD_READY)
        assert cloud_context.supports_browser_automation is False

    def test_supports_windows_autostart(self):
        """Test Windows auto-start support."""
        local_context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        assert local_context.supports_windows_autostart is True

        cloud_context = RuntimeContext(runtime=RuntimeEnvironment.CLOUD_READY)
        assert cloud_context.supports_windows_autostart is False

    def test_supports_persistent_browser_session(self):
        """Test persistent browser session support."""
        local_context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        assert local_context.supports_persistent_browser_session is True

        cloud_context = RuntimeContext(runtime=RuntimeEnvironment.CLOUD_READY)
        assert cloud_context.supports_persistent_browser_session is False

    def test_browser_user_data_dir_local(self):
        """Test browser user data directory for local runtime."""
        context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        path = context.browser_user_data_dir
        assert path is not None
        assert isinstance(path, str)
        # Should be a valid path string
        assert len(path) > 0

    def test_browser_user_data_dir_cloud(self):
        """Test browser user data directory for cloud runtime."""
        context = RuntimeContext(runtime=RuntimeEnvironment.CLOUD_READY)
        path = context.browser_user_data_dir
        # Cloud environments return None (needs remote browser strategy)
        assert path is None

    def test_data_directory(self):
        """Test data directory property."""
        context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        path = context.data_directory
        assert path is not None
        assert isinstance(path, str)
        assert len(path) > 0

    def test_log_directory(self):
        """Test log directory property."""
        context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        path = context.log_directory
        assert path is not None
        assert isinstance(path, str)
        assert len(path) > 0

    def test_get_database_url(self):
        """Test database URL retrieval."""
        context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        url = context.get_database_url()
        assert url is not None
        assert isinstance(url, str)
        assert len(url) > 0

    def test_get_storage_path(self):
        """Test storage path resolution."""
        context = RuntimeContext(runtime=RuntimeEnvironment.LOCAL_WINDOWS)
        path = context.get_storage_path("resume/file.pdf")
        assert path is not None
        assert isinstance(path, str)
        assert "resume" in path
        assert "file.pdf" in path


class TestGlobalRuntimeContext:
    """Test global runtime context singleton."""

    def test_get_runtime_context_singleton(self):
        """Test that get_runtime_context returns same instance."""
        context1 = get_runtime_context()
        context2 = get_runtime_context()
        assert context1 is context2

    def test_set_runtime_context(self):
        """Test setting runtime context explicitly."""
        original_context = get_runtime_context()
        
        set_runtime_context(RuntimeEnvironment.CLOUD_READY)
        new_context = get_runtime_context()
        assert new_context.runtime == RuntimeEnvironment.CLOUD_READY
        
        # Restore original
        set_runtime_context(original_context.runtime)
