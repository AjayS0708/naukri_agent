import pytest
from unittest.mock import patch, MagicMock
import platform

from backend.services.windows.autostart import WindowsAutoStartService


@pytest.fixture
def autostart_service():
    """Create an auto-start service for testing."""
    return WindowsAutoStartService()


class TestWindowsAutoStartService:
    """Tests for WindowsAutoStartService."""
    
    def test_initialization(self, autostart_service: WindowsAutoStartService):
        """Test service initialization."""
        assert autostart_service.task_name == "NaukriAgent"
        assert autostart_service.is_windows == (platform.system() == "Windows")
    
    def test_is_enabled_on_windows(self, autostart_service: WindowsAutoStartService):
        """Test checking auto-start status on Windows."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        with patch('subprocess.run') as mock_run:
            # Task exists and is enabled
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Task: NaukriAgent\nStatus: Ready"
            )
            
            result = autostart_service.is_enabled()
            assert result is True
    
    def test_is_enabled_disabled_task(self, autostart_service: WindowsAutoStartService):
        """Test checking auto-start status when task is disabled."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        with patch('subprocess.run') as mock_run:
            # Task exists but is disabled
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Task: NaukriAgent\nStatus: Disabled"
            )
            
            result = autostart_service.is_enabled()
            assert result is False
    
    def test_is_enabled_task_not_found(self, autostart_service: WindowsAutoStartService):
        """Test checking auto-start status when task doesn't exist."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        with patch('subprocess.run') as mock_run:
            # Task doesn't exist
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="ERROR: The system cannot find the file specified"
            )
            
            result = autostart_service.is_enabled()
            assert result is False
    
    def test_is_enabled_on_non_windows(self, autostart_service: WindowsAutoStartService):
        """Test checking auto-start status on non-Windows platform."""
        with patch.object(autostart_service, 'is_windows', False):
            result = autostart_service.is_enabled()
            assert result is False
    
    def test_enable_on_windows(self, autostart_service: WindowsAutoStartService):
        """Test enabling auto-start on Windows."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.dirname', return_value='/path/to/python'):
            
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            result = autostart_service.enable()
            assert result["success"] is True
            assert "enabled successfully" in result["message"]
            assert "script_path" in result
    
    def test_enable_script_not_found(self, autostart_service: WindowsAutoStartService):
        """Test enabling auto-start when script doesn't exist."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        with patch('os.path.exists', return_value=False):
            result = autostart_service.enable("/nonexistent/path.py")
            assert result["success"] is False
            assert "Script not found" in result["reason"]
    
    def test_enable_on_non_windows(self, autostart_service: WindowsAutoStartService):
        """Test enabling auto-start on non-Windows platform."""
        with patch.object(autostart_service, 'is_windows', False):
            result = autostart_service.enable()
            assert result["success"] is False
            assert "not supported" in result["reason"]
    
    def test_disable_on_windows(self, autostart_service: WindowsAutoStartService):
        """Test disabling auto-start on Windows."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            result = autostart_service.disable()
            assert result["success"] is True
            assert "disabled successfully" in result["message"]
    
    def test_disable_task_not_found(self, autostart_service: WindowsAutoStartService):
        """Test disabling auto-start when task doesn't exist."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="ERROR: The system cannot find the file specified",
                stdout="ERROR: The task does not exist"
            )
            
            result = autostart_service.disable()
            # Should succeed even if task doesn't exist
            assert result["success"] is True
            assert "not enabled" in result["message"]
    
    def test_disable_on_non_windows(self, autostart_service: WindowsAutoStartService):
        """Test disabling auto-start on non-Windows platform."""
        with patch.object(autostart_service, 'is_windows', False):
            result = autostart_service.disable()
            assert result["success"] is False
            assert "not supported" in result["reason"]
    
    def test_get_status(self, autostart_service: WindowsAutoStartService):
        """Test getting auto-start status."""
        status = autostart_service.get_status()
        
        assert "enabled" in status
        assert "platform" in status
        assert "task_name" in status
        assert "supported" in status
        assert status["task_name"] == "NaukriAgent"
        assert status["platform"] == platform.system()
        assert status["supported"] == autostart_service.is_windows
    
    def test_get_status_with_mocked_enabled(self, autostart_service: WindowsAutoStartService):
        """Test getting auto-start status with mocked enabled state."""
        with patch.object(autostart_service, 'is_enabled', return_value=True):
            status = autostart_service.get_status()
            assert status["enabled"] is True
    
    def test_subprocess_flags_on_windows(self, autostart_service: WindowsAutoStartService):
        """Test that subprocess flags are set correctly on Windows."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        # Check that the subprocess_flags variable is defined
        from backend.services.windows.autostart import subprocess_flags
        assert subprocess_flags is not None
    
    def test_enable_with_custom_script_path(self, autostart_service: WindowsAutoStartService):
        """Test enabling auto-start with custom script path."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        custom_path = "/custom/path/to/script.py"
        
        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.dirname', return_value='/path/to/python'):
            
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            result = autostart_service.enable(custom_path)
            assert result["success"] is True
            assert result["script_path"] == custom_path
    
    def test_enable_with_default_script_path(self, autostart_service: WindowsAutoStartService):
        """Test enabling auto-start with default script path."""
        if not autostart_service.is_windows:
            pytest.skip("Test only runs on Windows")
        
        from pathlib import Path
        mock_cwd = Path('/current/dir')
        
        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.dirname', return_value='/path/to/python'), \
             patch('pathlib.Path.cwd', return_value=mock_cwd):
            
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            result = autostart_service.enable()
            assert result["success"] is True
            assert "script_path" in result
