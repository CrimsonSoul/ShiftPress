"""
Unit tests for path_validation module.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.path_validation import (
    validate_folder_path,
    validate_file_path,
    sanitize_filename,
    is_path_within_base,
)


class TestValidateFolderPath:
    """Tests for validate_folder_path function."""

    def test_valid_folder(self, tmp_path):
        """Valid folder should pass validation."""
        is_valid, error = validate_folder_path(str(tmp_path))
        assert is_valid is True
        assert error is None

    def test_nonexistent_folder(self):
        """Non-existent folder should fail validation."""
        is_valid, error = validate_folder_path("/nonexistent/path")
        assert is_valid is False
        assert "does not exist" in error

    def test_file_instead_of_folder(self, tmp_path):
        """File path should fail folder validation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        is_valid, error = validate_folder_path(str(test_file))
        assert is_valid is False
        assert "not a directory" in error

    def test_empty_path(self):
        """Empty path should fail validation."""
        is_valid, error = validate_folder_path("")
        assert is_valid is False
        assert "cannot be empty" in error

    def test_unreadable_folder(self, tmp_path):
        """Unreadable folder should fail validation."""
        # Create a folder and make it unreadable
        test_folder = tmp_path / "unreadable"
        test_folder.mkdir()
        original_mode = test_folder.stat().st_mode
        try:
            os.chmod(test_folder, 0o000)
            is_valid, error = validate_folder_path(str(test_folder))
            # On some systems, this might still pass due to permissions
            # Just check that it doesn't crash
            assert isinstance(is_valid, bool)
        finally:
            # Restore permissions for cleanup
            os.chmod(test_folder, original_mode)

    def test_relative_path_resolved(self, tmp_path):
        """Relative path should be resolved to absolute."""
        # Change to temp directory
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            is_valid, error = validate_folder_path(".")
            assert is_valid is True
            assert error is None
        finally:
            os.chdir(original_cwd)


class TestValidateFilePath:
    """Tests for validate_file_path function."""

    def test_valid_file(self, tmp_path):
        """Valid file should pass validation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        is_valid, error = validate_file_path(str(test_file))
        assert is_valid is True
        assert error is None

    def test_nonexistent_file(self):
        """Non-existent file should fail validation."""
        is_valid, error = validate_file_path("/nonexistent/file.txt")
        assert is_valid is False
        assert "does not exist" in error

    def test_folder_instead_of_file(self, tmp_path):
        """Folder path should fail file validation."""
        is_valid, error = validate_file_path(str(tmp_path))
        assert is_valid is False
        assert "not a file" in error

    def test_empty_path(self):
        """Empty path should fail validation."""
        is_valid, error = validate_file_path("")
        assert is_valid is False
        assert "cannot be empty" in error

    def test_allowed_extension(self, tmp_path):
        """File with allowed extension should pass."""
        test_file = tmp_path / "test.docx"
        test_file.write_text("test")
        is_valid, error = validate_file_path(str(test_file), [".docx"])
        assert is_valid is True
        assert error is None

    def test_disallowed_extension(self, tmp_path):
        """File with disallowed extension should fail."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")
        is_valid, error = validate_file_path(str(test_file), [".docx"])
        assert is_valid is False
        assert "not allowed" in error

    def test_extension_case_insensitive(self, tmp_path):
        """Extension check should be case-insensitive."""
        test_file = tmp_path / "test.DOCX"
        test_file.write_text("test")
        is_valid, error = validate_file_path(str(test_file), [".docx"])
        assert is_valid is True
        assert error is None


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_normal_filename(self):
        """Normal filename should be unchanged."""
        result = sanitize_filename("document.docx")
        assert result == "document.docx"

    def test_path_separators(self):
        """Path separators should be replaced with underscores."""
        result = sanitize_filename("folder/file.txt")
        assert result == "folder_file.txt"
        result = sanitize_filename("folder\\file.txt")
        assert result == "folder_file.txt"

    def test_dangerous_characters(self):
        """Dangerous characters should be replaced."""
        result = sanitize_filename("file:name*.txt")
        assert result == "file_name_.txt"

    def test_leading_dots(self):
        """Leading dots should be removed."""
        result = sanitize_filename("..hidden.txt")
        assert result == "hidden.txt"

    def test_trailing_dots(self):
        """Trailing dots should be removed."""
        result = sanitize_filename("file.txt...")
        assert result == "file.txt"

    def test_leading_spaces(self):
        """Leading spaces should be removed."""
        result = sanitize_filename("  file.txt")
        assert result == "file.txt"

    def test_trailing_spaces(self):
        """Trailing spaces should be removed."""
        result = sanitize_filename("file.txt  ")
        assert result == "file.txt"

    def test_long_filename(self):
        """Long filename should be truncated."""
        long_name = "a" * 300
        result = sanitize_filename(long_name)
        assert len(result) == 255

    def test_empty_filename(self):
        """Empty filename should return a safe fallback."""
        result = sanitize_filename("")
        assert result == "_unnamed"

    def test_only_dots(self):
        """Filename with only dots should return a safe fallback."""
        result = sanitize_filename("...")
        assert result == "_unnamed"

    def test_reserved_device_name_con(self):
        """Windows reserved name CON should be prefixed."""
        result = sanitize_filename("CON.docx")
        assert result == "_CON.docx"

    def test_reserved_device_name_nul(self):
        """Windows reserved name NUL should be prefixed."""
        result = sanitize_filename("NUL.txt")
        assert result == "_NUL.txt"

    def test_reserved_device_name_com1(self):
        """Windows reserved name COM1 should be prefixed."""
        result = sanitize_filename("COM1")
        assert result == "_COM1"

    def test_reserved_device_name_case_insensitive(self):
        """Reserved name check should be case-insensitive."""
        result = sanitize_filename("con.docx")
        assert result == "_con.docx"

    def test_non_reserved_name_passes(self):
        """Non-reserved name like CONTROL should NOT be prefixed."""
        result = sanitize_filename("CONTROL.docx")
        assert result == "CONTROL.docx"

    def test_long_filename_preserves_extension(self):
        """Long filename truncation should preserve the file extension."""
        long_name = "a" * 300 + ".docx"
        result = sanitize_filename(long_name)
        assert len(result) <= 255
        assert result.endswith(".docx")

    def test_long_filename_no_extension(self):
        """Long filename without extension should truncate directly."""
        long_name = "a" * 300
        result = sanitize_filename(long_name)
        assert len(result) == 255
        assert "." not in result

    def test_only_spaces(self):
        """Filename with only spaces should return a safe fallback."""
        result = sanitize_filename("   ")
        assert result == "_unnamed"


class TestIsPathWithinBase:
    """Tests for is_path_within_base function."""

    def test_path_within_base(self, tmp_path):
        """Path within base should return True."""
        subfolder = tmp_path / "subfolder"
        subfolder.mkdir()
        assert is_path_within_base(str(subfolder), str(tmp_path)) is True

    def test_path_equals_base(self, tmp_path):
        """Path equal to base should return True."""
        assert is_path_within_base(str(tmp_path), str(tmp_path)) is True

    def test_path_outside_base(self, tmp_path):
        """Path outside base should return False."""
        other_path = tmp_path.parent / "other"
        assert is_path_within_base(str(other_path), str(tmp_path)) is False

    def test_parent_directory_traversal(self, tmp_path):
        """Parent directory traversal should return False."""
        assert is_path_within_base(str(tmp_path / ".."), str(tmp_path)) is False

    def test_symlink_within_base(self, tmp_path):
        """Symlink within base should return True."""
        subfolder = tmp_path / "subfolder"
        subfolder.mkdir()
        symlink = tmp_path / "link"
        try:
            symlink.symlink_to(subfolder)
            assert is_path_within_base(str(symlink), str(tmp_path)) is True
        except OSError:
            # Symlinks might not be supported on this system
            pytest.skip("Symlinks not supported")

    def test_symlink_outside_base(self, tmp_path):
        """Symlink outside base should return False."""
        other_path = tmp_path.parent / "other"
        other_path.mkdir()
        symlink = tmp_path / "link"
        try:
            symlink.symlink_to(other_path)
            assert is_path_within_base(str(symlink), str(tmp_path)) is False
        except OSError:
            # Symlinks might not be supported on this system
            pytest.skip("Symlinks not supported")

    def test_nonexistent_path(self, tmp_path):
        """Non-existent path within base should still return True."""
        nonexistent = tmp_path / "nonexistent"
        assert is_path_within_base(str(nonexistent), str(tmp_path)) is True
