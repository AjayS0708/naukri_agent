import os
import platform
import subprocess
from typing import Optional
from pathlib import Path

from backend.core.logging import get_logger

logger = get_logger(__name__)

# Windows-specific subprocess flags
if platform.system() == "Windows":
    subprocess_flags = subprocess.CREATE_NO_WINDOW
else:
    subprocess_flags = 0


class WindowsAutoStartService:
    """
    Service for managing Windows auto-start using Task Scheduler.
    
    This provides a clean Windows-first auto-start mechanism that:
    - Does NOT require administrator privileges (for user-level tasks)
    - Is user-controlled (enable/disable/check status)
    - Does NOT install automatically during development
    - Does NOT auto-submit applications merely because Windows started the app
    """
    
    def __init__(self):
        self.task_name = "NaukriAgent"
        self.is_windows = platform.system() == "Windows"
    
    def is_enabled(self) -> bool:
        """
        Check if auto-start is enabled.
        
        Returns True if the task exists and is enabled in Task Scheduler.
        """
        if not self.is_windows:
            logger.info("auto_start_not_supported_on_platform", extra={"platform": platform.system()})
            return False
        
        try:
            # Query Task Scheduler for the task
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", self.task_name],
                capture_output=True,
                text=True,
                creationflags=subprocess_flags
            )
            
            # Task exists if return code is 0
            if result.returncode == 0:
                # Check if task is enabled (not disabled)
                if "Disabled" in result.stdout:
                    return False
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check auto-start status: {e}", exc_info=True)
            return False
    
    def enable(self, script_path: Optional[str] = None) -> dict:
        """
        Enable auto-start by creating a Task Scheduler task.
        
        Args:
            script_path: Optional path to the startup script. If None, uses current working directory.
        
        Returns dict with success status and message.
        """
        if not self.is_windows:
            return {
                "success": False,
                "reason": f"Auto-start not supported on {platform.system()}"
            }
        
        try:
            # Determine script path
            if script_path is None:
                # Use run.py in current directory
                cwd = Path.cwd()
                script_path = str(cwd / "run.py")
            
            if not os.path.exists(script_path):
                return {
                    "success": False,
                    "reason": f"Script not found: {script_path}"
                }
            
            # Get Python executable path
            python_path = os.path.join(os.path.dirname(os.__file__), "python.exe")
            if not os.path.exists(python_path):
                # Fallback to system python
                python_path = "python"
            
            # Create the task using schtasks
            # /SC ONLOGON: Run when user logs on
            # /RL HIGHEST: Run with highest privileges (may be needed for browser automation)
            # /F: Force overwrite if task exists
            # /NP: No password (stored in Windows credential manager)
            command = [
                "schtasks",
                "/Create",
                "/TN", self.task_name,
                "/TR", f'"{python_path}" "{script_path}"',
                "/SC", "ONLOGON",
                "/RL", "HIGHEST",
                "/F",
                "/NP"
            ]
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                creationflags=subprocess_flags
            )
            
            if result.returncode == 0:
                logger.info("auto_start_enabled", extra={"script_path": script_path})
                return {
                    "success": True,
                    "message": "Auto-start enabled successfully",
                    "script_path": script_path
                }
            else:
                logger.error(f"Failed to enable auto-start: {result.stderr}")
                return {
                    "success": False,
                    "reason": result.stderr or "Unknown error"
                }
                
        except Exception as e:
            logger.error(f"Failed to enable auto-start: {e}", exc_info=True)
            return {
                "success": False,
                "reason": str(e)
            }
    
    def disable(self) -> dict:
        """
        Disable auto-start by deleting the Task Scheduler task.
        
        Returns dict with success status and message.
        """
        if not self.is_windows:
            return {
                "success": False,
                "reason": f"Auto-start not supported on {platform.system()}"
            }
        
        try:
            # Delete the task
            result = subprocess.run(
                ["schtasks", "/Delete", "/TN", self.task_name, "/F"],
                capture_output=True,
                text=True,
                creationflags=subprocess_flags
            )
            
            if result.returncode == 0:
                logger.info("auto_start_disabled")
                return {
                    "success": True,
                    "message": "Auto-start disabled successfully"
                }
            else:
                # Task might not exist, which is fine
                stderr_lower = result.stderr.lower() if result.stderr else ""
                stdout_lower = result.stdout.lower() if result.stdout else ""
                if "not found" in stderr_lower or "does not exist" in stderr_lower or "not found" in stdout_lower or "does not exist" in stdout_lower:
                    logger.info("auto_start_task_not_found")
                    return {
                        "success": True,
                        "message": "Auto-start was not enabled"
                    }
                
                logger.error(f"Failed to disable auto-start: {result.stderr}")
                return {
                    "success": False,
                    "reason": result.stderr or "Unknown error"
                }
                
        except Exception as e:
            logger.error(f"Failed to disable auto-start: {e}", exc_info=True)
            return {
                "success": False,
                "reason": str(e)
            }
    
    def get_status(self) -> dict:
        """
        Get auto-start status.
        
        Returns dict with:
        - enabled: bool
        - platform: str
        - task_name: str
        """
        return {
            "enabled": self.is_enabled(),
            "platform": platform.system(),
            "task_name": self.task_name,
            "supported": self.is_windows
        }
