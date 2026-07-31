"""
Unit tests for logger module.
"""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.logger import setup_logging, get_logger


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_returns_root_logger(self, tmp_path):
        """Should return the root logger."""
        result = setup_logging(log_dir=str(tmp_path))
        assert isinstance(result, logging.Logger)
        assert result.name == "root"

    def test_default_level_is_info(self, tmp_path):
        """Should default to INFO when DEBUG env is not set."""
        with patch.dict(os.environ, {}, clear=True):
            logger = setup_logging(log_dir=str(tmp_path))
            assert logger.level == logging.INFO

    def test_debug_env_enables_debug_level(self, tmp_path):
        """Should set DEBUG level when DEBUG=1 env var is set."""
        with patch.dict(os.environ, {"DEBUG": "1"}, clear=False):
            logger = setup_logging(log_dir=str(tmp_path))
            assert logger.level == logging.DEBUG

    def test_debug_env_true_string(self, tmp_path):
        """Should set DEBUG level when DEBUG=true env var is set."""
        with patch.dict(os.environ, {"DEBUG": "true"}, clear=False):
            logger = setup_logging(log_dir=str(tmp_path))
            assert logger.level == logging.DEBUG

    def test_explicit_log_level(self, tmp_path):
        """Should use the explicitly provided log_level."""
        logger = setup_logging(log_level=logging.WARNING, log_dir=str(tmp_path))
        assert logger.level == logging.WARNING

    def test_creates_log_file(self, tmp_path):
        """Should create a log file in the specified directory."""
        setup_logging(log_dir=str(tmp_path))
        log_files = list(tmp_path.glob("*.log"))
        assert len(log_files) == 1
        assert log_files[0].name == "shiftprint.log"

    def test_custom_log_filename(self, tmp_path):
        """Should use a custom log filename when specified."""
        setup_logging(log_dir=str(tmp_path), log_filename="custom.log")
        assert (tmp_path / "custom.log").exists()

    def test_creates_log_directory(self, tmp_path):
        """Should create the log directory if it doesn't exist."""
        log_dir = tmp_path / "subdir" / "logs"
        setup_logging(log_dir=str(log_dir))
        assert log_dir.exists()

    def test_has_file_and_console_handlers(self, tmp_path):
        """Should have both a file handler and a console handler."""
        logger = setup_logging(log_dir=str(tmp_path))
        handler_types = [type(h) for h in logger.handlers]
        assert logging.handlers.RotatingFileHandler in handler_types
        assert logging.StreamHandler in handler_types

    def test_clears_existing_handlers(self, tmp_path):
        """Should clear its own handlers on re-init but preserve third-party ones."""
        root = logging.getLogger()
        # Add a handler that is NOT tagged as ours.
        third_party = logging.StreamHandler()
        root.addHandler(third_party)

        setup_logging(log_dir=str(tmp_path))
        # Our 2 tagged handlers are added; the third-party handler survives.
        tagged = [h for h in root.handlers if getattr(h, "_shiftpress", False)]
        assert len(tagged) == 2
        assert third_party in root.handlers
        root.removeHandler(third_party)

    def test_graceful_fallback_on_unwritable_dir(self, tmp_path):
        """Should still add a console handler if file handler fails."""
        # Use a path that can't be written to
        with patch(
            "logging.handlers.RotatingFileHandler",
            side_effect=IOError("Permission denied"),
        ):
            logger = setup_logging(log_dir=str(tmp_path))
            # Should have at least the console handler
            assert len(logger.handlers) >= 1
            assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_named_logger(self):
        """Should return a logger with the given name."""
        logger = get_logger("test.module")
        assert logger.name == "test.module"

    def test_default_name(self):
        """Should return 'shiftpress' when no name provided."""
        logger = get_logger()
        assert logger.name == "shiftpress"

    def test_none_name(self):
        """Should return 'shiftpress' when name is None."""
        logger = get_logger(None)
        assert logger.name == "shiftpress"


class TestSetupLoggingIdempotency:
    """Tests for re-initialization idempotency."""

    def test_double_init_does_not_duplicate_handlers(self, tmp_path):
        """Calling setup_logging twice should not leave duplicate tagged handlers."""
        root = logging.getLogger()

        # Record third-party handlers before our test
        pre_existing = len(
            [h for h in root.handlers if not getattr(h, "_shiftpress", False)]
        )

        setup_logging(log_dir=str(tmp_path))
        tagged_after_first = [
            h for h in root.handlers if getattr(h, "_shiftpress", False)
        ]
        count_first = len(tagged_after_first)

        setup_logging(log_dir=str(tmp_path))
        tagged_after_second = [
            h for h in root.handlers if getattr(h, "_shiftpress", False)
        ]
        count_second = len(tagged_after_second)

        # Should have exactly the same number of tagged handlers (2: file + console)
        assert count_first == 2
        assert count_second == 2

        # Third-party handlers should be untouched
        third_party_after = len(
            [h for h in root.handlers if not getattr(h, "_shiftpress", False)]
        )
        assert third_party_after == pre_existing
