"""
Tests for storage service abstraction.
"""

import pytest
from pathlib import Path
from backend.core.storage import StorageService, get_storage_service


class TestStorageService:
    """Test StorageService class."""

    def test_initialization(self, tmp_path):
        """Test storage service initialization."""
        service = StorageService()
        assert service is not None

    def test_get_resume_storage_path(self):
        """Test getting resume storage path."""
        service = StorageService()
        path = service.get_resume_storage_path()
        assert isinstance(path, Path)
        assert path.exists()  # Should be created during initialization

    def test_get_data_storage_path(self):
        """Test getting data storage path."""
        service = StorageService()
        path = service.get_data_storage_path()
        assert isinstance(path, Path)
        assert path.exists()

    def test_get_log_storage_path(self):
        """Test getting log storage path."""
        service = StorageService()
        path = service.get_log_storage_path()
        assert isinstance(path, Path)
        assert path.exists()

    def test_get_browser_user_data_path(self):
        """Test getting browser user data path."""
        service = StorageService()
        path = service.get_browser_user_data_path()
        assert isinstance(path, Path)
        assert path.exists()

    def test_resolve_path_with_base_dir(self, tmp_path):
        """Test path resolution with custom base directory."""
        service = StorageService()
        resolved = service.resolve_path("test/file.txt", base_dir=tmp_path)
        assert resolved == tmp_path / "test" / "file.txt"

    def test_resolve_path_without_base_dir(self):
        """Test path resolution without custom base directory."""
        service = StorageService()
        resolved = service.resolve_path("test/file.txt")
        # Should resolve relative to data directory
        assert "test" in str(resolved)
        assert "file.txt" in str(resolved)

    def test_store_file(self, tmp_path, monkeypatch):
        """Test storing a file."""
        service = StorageService()
        
        # Monkeypatch the underlying config field to use temp directory
        monkeypatch.setattr(service._settings, "data_dir", str(tmp_path))
        
        content = b"test content"
        filename = "test.txt"
        subdirectory = "subdir"
        
        path = service.store_file(content, filename, subdirectory)
        
        assert path.exists()
        assert path.read_bytes() == content
        assert path.parent.name == subdirectory
        assert path.name == filename

    def test_store_file_without_subdirectory(self, tmp_path, monkeypatch):
        """Test storing a file without subdirectory."""
        service = StorageService()
        monkeypatch.setattr(service._settings, "data_dir", str(tmp_path))
        
        content = b"test content"
        filename = "test.txt"
        
        path = service.store_file(content, filename)
        
        assert path.exists()
        assert path.read_bytes() == content
        assert path.name == filename

    def test_read_file(self, tmp_path, monkeypatch):
        """Test reading a file."""
        service = StorageService()
        monkeypatch.setattr(service._settings, "data_dir", str(tmp_path))
        
        content = b"test content"
        filename = "test.txt"
        path = service.store_file(content, filename)
        
        read_content = service.read_file(path)
        assert read_content == content

    def test_read_file_not_found(self, tmp_path):
        """Test reading a non-existent file."""
        service = StorageService()
        non_existent = tmp_path / "nonexistent.txt"
        
        with pytest.raises(FileNotFoundError):
            service.read_file(non_existent)

    def test_delete_file(self, tmp_path, monkeypatch):
        """Test deleting a file."""
        service = StorageService()
        monkeypatch.setattr(service._settings, "data_dir", str(tmp_path))
        
        content = b"test content"
        filename = "test.txt"
        path = service.store_file(content, filename)
        
        assert path.exists()
        result = service.delete_file(path)
        assert result is True
        assert not path.exists()

    def test_delete_file_not_found(self, tmp_path):
        """Test deleting a non-existent file."""
        service = StorageService()
        non_existent = tmp_path / "nonexistent.txt"
        
        result = service.delete_file(non_existent)
        assert result is False

    def test_file_exists(self, tmp_path, monkeypatch):
        """Test checking if file exists."""
        service = StorageService()
        monkeypatch.setattr(service._settings, "data_dir", str(tmp_path))
        
        content = b"test content"
        filename = "test.txt"
        path = service.store_file(content, filename)
        
        assert service.file_exists(path) is True
        
        service.delete_file(path)
        assert service.file_exists(path) is False

    def test_get_file_size(self, tmp_path, monkeypatch):
        """Test getting file size."""
        service = StorageService()
        monkeypatch.setattr(service._settings, "data_dir", str(tmp_path))
        
        content = b"test content"
        filename = "test.txt"
        path = service.store_file(content, filename)
        
        size = service.get_file_size(path)
        assert size == len(content)

    def test_get_file_size_not_found(self, tmp_path):
        """Test getting size of non-existent file."""
        service = StorageService()
        non_existent = tmp_path / "nonexistent.txt"
        
        with pytest.raises(FileNotFoundError):
            service.get_file_size(non_existent)

    def test_list_files(self, tmp_path, monkeypatch):
        """Test listing files in directory."""
        service = StorageService()
        monkeypatch.setattr(service._settings, "data_dir", str(tmp_path))
        
        # Create some files
        service.store_file(b"content1", "file1.txt")
        service.store_file(b"content2", "file2.txt")
        service.store_file(b"content3", "file3.pdf")
        
        files = service.list_files(tmp_path)
        assert len(files) == 3

    def test_list_files_with_pattern(self, tmp_path, monkeypatch):
        """Test listing files with pattern."""
        service = StorageService()
        monkeypatch.setattr(service._settings, "data_dir", str(tmp_path))
        
        # Create some files
        service.store_file(b"content1", "file1.txt")
        service.store_file(b"content2", "file2.txt")
        service.store_file(b"content3", "file3.pdf")
        
        txt_files = service.list_files(tmp_path, pattern="*.txt")
        assert len(txt_files) == 2
        
        pdf_files = service.list_files(tmp_path, pattern="*.pdf")
        assert len(pdf_files) == 1

    def test_list_files_directory_not_found(self, tmp_path):
        """Test listing files in non-existent directory."""
        service = StorageService()
        non_existent = tmp_path / "nonexistent"
        
        files = service.list_files(non_existent)
        assert files == []

    def test_create_directory(self, tmp_path):
        """Test creating a directory."""
        service = StorageService()
        new_dir = tmp_path / "new_directory"
        
        assert not new_dir.exists()
        service.create_directory(new_dir)
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_delete_directory(self, tmp_path):
        """Test deleting a directory."""
        service = StorageService()
        new_dir = tmp_path / "new_directory"
        new_dir.mkdir()
        
        assert new_dir.exists()
        result = service.delete_directory(new_dir, recursive=False)
        assert result is True
        assert not new_dir.exists()

    def test_delete_directory_recursive(self, tmp_path):
        """Test deleting a directory recursively."""
        service = StorageService()
        new_dir = tmp_path / "new_directory"
        new_dir.mkdir()
        (new_dir / "file.txt").write_text("content")
        
        assert new_dir.exists()
        result = service.delete_directory(new_dir, recursive=True)
        assert result is True
        assert not new_dir.exists()

    def test_delete_directory_not_found(self, tmp_path):
        """Test deleting non-existent directory."""
        service = StorageService()
        non_existent = tmp_path / "nonexistent"
        
        result = service.delete_directory(non_existent)
        assert result is False


class TestGlobalStorageService:
    """Test global storage service singleton."""

    def test_get_storage_service_singleton(self):
        """Test that get_storage_service returns same instance."""
        service1 = get_storage_service()
        service2 = get_storage_service()
        assert service1 is service2
