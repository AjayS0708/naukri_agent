"""
Storage/Path Abstraction

This module provides a clean abstraction for file storage operations.
It encapsulates filesystem access to make future object storage integration easier.

V1 Implementation:
- Local filesystem storage using pathlib
- Resume storage, data storage, log storage
- Path resolution and directory creation

Future:
- S3/Azure Blob/GCS integration without changing business logic
- Cloud storage providers
- Storage abstraction layer
"""

from pathlib import Path
from typing import Optional, BinaryIO
import os
import shutil

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class StorageService:
    """
    Service for managing file storage operations.
    
    This service provides a clean interface for file operations,
    abstracting the underlying storage mechanism.
    
    V1: Uses local filesystem.
    Future: Can be extended to use S3, Azure Blob, GCS, etc.
    """
    
    def __init__(self):
        """Initialize storage service with configuration."""
        self._settings = get_settings()
        
        # Ensure base directories exist
        self._ensure_directories()
    
    def _ensure_directories(self) -> None:
        """Ensure all required storage directories exist."""
        directories = [
            self._settings.data_path,
            self._settings.resume_storage_path,
            self._settings.log_path,
            self._settings.browser_user_data_path,
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def get_resume_storage_path(self) -> Path:
        """Get the resume storage directory path."""
        return self._settings.resume_storage_path
    
    def get_data_storage_path(self) -> Path:
        """Get the data storage directory path."""
        return self._settings.data_path
    
    def get_log_storage_path(self) -> Path:
        """Get the log storage directory path."""
        return self._settings.log_path
    
    def get_browser_user_data_path(self) -> Path:
        """Get the browser user data directory path."""
        return self._settings.browser_user_data_path
    
    def resolve_path(self, relative_path: str, base_dir: Optional[Path] = None) -> Path:
        """
        Resolve a relative path to an absolute path.
        
        Args:
            relative_path: Relative path (e.g., "resume/file.pdf")
            base_dir: Base directory (defaults to data directory)
            
        Returns:
            Absolute path
        """
        if base_dir is None:
            base_dir = self._settings.data_path
        
        return base_dir / relative_path
    
    def store_file(
        self,
        content: bytes,
        filename: str,
        subdirectory: Optional[str] = None
    ) -> Path:
        """
        Store a file in the storage system.
        
        Args:
            content: File content as bytes
            filename: Name of the file
            subdirectory: Optional subdirectory within base storage
            
        Returns:
            Path to the stored file
        """
        base_path = self._settings.data_path
        if subdirectory:
            base_path = base_path / subdirectory
        
        base_path.mkdir(parents=True, exist_ok=True)
        
        file_path = base_path / filename
        temp_path = base_path / f".{filename}.tmp"
        
        try:
            with temp_path.open("wb") as f:
                f.write(content)
            os.replace(temp_path, file_path)
            logger.info("file_stored", extra={"path": str(file_path), "size": len(content)})
            return file_path
        except OSError as e:
            temp_path.unlink(missing_ok=True)
            logger.error("file_storage_failed", extra={"path": str(file_path), "error": str(e)})
            raise
    
    def read_file(self, file_path: Path) -> bytes:
        """
        Read a file from the storage system.
        
        Args:
            file_path: Path to the file
            
        Returns:
            File content as bytes
        """
        if not file_path.exists():
            logger.error("file_not_found", extra={"path": str(file_path)})
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with file_path.open("rb") as f:
            content = f.read()
        
        logger.info("file_read", extra={"path": str(file_path), "size": len(content)})
        return content
    
    def delete_file(self, file_path: Path) -> bool:
        """
        Delete a file from the storage system.
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if deleted, False if not found
        """
        if not file_path.exists():
            logger.warning("file_not_found_for_deletion", extra={"path": str(file_path)})
            return False
        
        file_path.unlink()
        logger.info("file_deleted", extra={"path": str(file_path)})
        return True
    
    def file_exists(self, file_path: Path) -> bool:
        """
        Check if a file exists in the storage system.
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if file exists, False otherwise
        """
        return file_path.exists()
    
    def get_file_size(self, file_path: Path) -> int:
        """
        Get the size of a file in bytes.
        
        Args:
            file_path: Path to the file
            
        Returns:
            File size in bytes
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        return file_path.stat().st_size
    
    def list_files(
        self,
        directory: Path,
        pattern: Optional[str] = None
    ) -> list[Path]:
        """
        List files in a directory.
        
        Args:
            directory: Directory to list
            pattern: Optional glob pattern (e.g., "*.pdf")
            
        Returns:
            List of file paths
        """
        if not directory.exists():
            logger.warning("directory_not_found", extra={"path": str(directory)})
            return []
        
        if pattern:
            files = list(directory.glob(pattern))
        else:
            files = list(directory.iterdir())
        
        logger.info("files_listed", extra={"directory": str(directory), "count": len(files)})
        return files
    
    def create_directory(self, directory_path: Path) -> None:
        """
        Create a directory in the storage system.
        
        Args:
            directory_path: Path to the directory to create
        """
        directory_path.mkdir(parents=True, exist_ok=True)
        logger.info("directory_created", extra={"path": str(directory_path)})
    
    def delete_directory(self, directory_path: Path, recursive: bool = False) -> bool:
        """
        Delete a directory from the storage system.
        
        Args:
            directory_path: Path to the directory
            recursive: Whether to delete recursively
            
        Returns:
            True if deleted, False if not found
        """
        if not directory_path.exists():
            logger.warning("directory_not_found_for_deletion", extra={"path": str(directory_path)})
            return False
        
        if recursive:
            shutil.rmtree(directory_path)
        else:
            directory_path.rmdir()
        
        logger.info("directory_deleted", extra={"path": str(directory_path), "recursive": recursive})
        return True


# Global storage service instance
_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    """
    Get the global storage service instance.
    
    Returns:
        StorageService: The singleton storage service
    """
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
