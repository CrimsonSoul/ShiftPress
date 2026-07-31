"""
Logging configuration for ShiftPress application.

This module sets up the logging system with both file and console handlers.
"""

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

from .constants import LOG_FILENAME
from .app_paths import get_data_dir

__all__ = ["setup_logging", "get_logger"]


def setup_logging(
    log_level: Optional[int] = None,
    log_dir: Optional[str] = None,
    log_filename: str = LOG_FILENAME,
) -> logging.Logger:
    """
    Set up logging configuration for the application.

    Args:
        log_level: The logging level (default: check DEBUG env or logging.INFO)
        log_dir: Directory for log files (default: per-user data directory)
        log_filename: Name of the log file

    Returns:
        Configured logger instance
    """
    if log_level is None:
        if (
            os.environ.get("DEBUG") == "1"
            or os.environ.get("DEBUG", "").lower() == "true"
        ):
            log_level = logging.DEBUG
        else:
            log_level = logging.INFO

    # Determine log file path
    # Default to an OS-appropriate per-user data directory.
    if log_dir is None:
        log_path = get_data_dir()
    else:
        log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / log_filename

    # Configure the *root* logger so module loggers (e.g. "src.main") inherit handlers.
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove only handlers previously added by this module to avoid
    # destroying third-party or test-framework handlers.
    _TAG = "_shiftpress"
    for h in root_logger.handlers[:]:
        if getattr(h, _TAG, False):
            root_logger.removeHandler(h)

    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    simple_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
    )

    # File handler (detailed, with rotation: 5MB max, keep 3 backups)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        setattr(file_handler, _TAG, True)
        root_logger.addHandler(file_handler)
    except (IOError, OSError) as e:
        # If we can't write to file, at least log to console
        print(f"Warning: Could not create log file: {e}")

    # Console handler (simple)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter)
    setattr(console_handler, _TAG, True)
    root_logger.addHandler(console_handler)

    return root_logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (default: "shiftpress")

    Returns:
        Logger instance
    """
    return logging.getLogger(name or "shiftpress")
