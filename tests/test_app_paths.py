"""
Unit tests for app_paths module.
"""

import os
import sys
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from src.app_paths import get_data_dir, get_legacy_data_dir, APP_DIRNAME


class TestGetDataDir:
    """Tests for get_data_dir function."""

    def test_windows_appdata(self):
        """Should use APPDATA on Windows when available."""
        with patch("src.app_paths.os.name", "nt"), patch(
            "src.app_paths.Path", PurePosixPath
        ), patch.dict(os.environ, {"APPDATA": "/mock/appdata"}, clear=False):
            result = get_data_dir()
            assert str(result) == f"/mock/appdata/{APP_DIRNAME}"

    def test_windows_localappdata_fallback(self):
        """Should fall back to LOCALAPPDATA if APPDATA is missing."""
        env = {"LOCALAPPDATA": "/mock/local"}
        with patch("src.app_paths.os.name", "nt"), patch(
            "src.app_paths.Path", PurePosixPath
        ), patch.dict(os.environ, env, clear=True):
            result = get_data_dir()
            assert str(result) == f"/mock/local/{APP_DIRNAME}"

    def test_windows_home_fallback(self):
        """Should fall back to home dir if no env vars are set."""

        class _MockPath(PurePosixPath):
            @classmethod
            def home(cls):
                return cls("/mock/home")

        with patch("src.app_paths.os.name", "nt"), patch(
            "src.app_paths.Path", _MockPath
        ), patch.dict(os.environ, {}, clear=True):
            result = get_data_dir()
            assert str(result) == f"/mock/home/{APP_DIRNAME}"

    def test_non_windows(self):
        """Should use ~/.shiftprint on non-Windows."""

        class _MockPath(PurePosixPath):
            @classmethod
            def home(cls):
                return cls("/home/testuser")

        with patch("src.app_paths.os.name", "posix"), patch(
            "src.app_paths.Path", _MockPath
        ):
            result = get_data_dir()
            assert str(result) == "/home/testuser/.shiftprint"

    def test_legacy_dir_differs_from_current_on_windows(self):
        """Migration needs both locations reachable and distinct.

        The "ShiftPress" literal here is deliberate: it pins the pre-rename
        directory an upgrading operator's config still lives in.
        """
        with patch("src.app_paths.os.name", "nt"), patch(
            "src.app_paths.Path", PurePosixPath
        ), patch.dict(os.environ, {"APPDATA": "/mock/appdata"}, clear=False):
            assert str(get_data_dir()) == "/mock/appdata/ShiftPrint"
            assert str(get_legacy_data_dir()) == "/mock/appdata/ShiftPress"

    def test_legacy_dir_differs_from_current_elsewhere(self):
        """The non-Windows dev path also has to be distinguishable."""

        class _MockPath(PurePosixPath):
            @classmethod
            def home(cls):
                return cls("/home/testuser")

        with patch("src.app_paths.os.name", "posix"), patch(
            "src.app_paths.Path", _MockPath
        ):
            assert str(get_data_dir()) == "/home/testuser/.shiftprint"
            assert str(get_legacy_data_dir()) == "/home/testuser/.shiftpress"

    def test_returns_path_object(self):
        """Should always return a Path-like object."""
        result = get_data_dir()
        # Should be a Path or PurePath subclass
        assert hasattr(result, "parts")
        assert hasattr(result, "name")
