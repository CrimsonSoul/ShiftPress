"""
Configuration management for ShiftPress application.

This module handles loading, saving, and validating configuration settings.
"""

import contextlib
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from .constants import CONFIG_FILENAME
from .app_paths import get_data_dir
from .logger import get_logger

__all__ = ["AppConfig", "ConfigManager"]

logger = get_logger(__name__)


@dataclass
class AppConfig:
    """Application configuration data class."""

    day_folder: str = ""
    night_folder: str = ""
    printer_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary.

        Returns:
            Dict with keys ``day_folder``, ``night_folder``,
            and ``printer_name``.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """Create config from dictionary.

        Args:
            data: Dictionary with config keys. Missing keys use defaults.
                Unknown keys are silently ignored.

        Returns:
            A new ``AppConfig`` instance.
        """
        return cls(
            day_folder=str(data.get("day_folder", "") or ""),
            night_folder=str(data.get("night_folder", "") or ""),
            printer_name=str(data.get("printer_name", "") or ""),
        )


class ConfigManager:
    """Manages application configuration loading and saving."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize ConfigManager.

        Args:
            config_path: Path to config file (default: per-user data
                directory / CONFIG_FILENAME, i.e. ``%APPDATA%`` on Windows)
        """
        self._legacy_config_path = Path(CONFIG_FILENAME).resolve()
        self._allow_legacy_migration = config_path is None
        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = get_data_dir() / CONFIG_FILENAME
        self._config: Optional[AppConfig] = None

    def load(self) -> AppConfig:
        """
        Load configuration from file.

        Returns:
            AppConfig instance with loaded values, or defaults if the
            config file does not exist.

        Raises:
            json.JSONDecodeError: If the primary config file exists but
                contains invalid JSON.
            IOError: If the primary config file exists but cannot be read.
        """
        if not self.config_path.exists():
            # Backward-compatibility: older versions stored config.json in the working directory.
            if self._allow_legacy_migration and self._legacy_config_path.exists():
                try:
                    with open(self._legacy_config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._config = AppConfig.from_dict(data)
                        logger.info(
                            f"Configuration loaded from legacy path {self._legacy_config_path}; "
                            f"migrating to {self.config_path}"
                        )
                    try:
                        self.save(self._config)
                    except Exception as e:
                        logger.warning(
                            f"Could not migrate legacy config to {self.config_path}: {e}"
                        )
                    # Rename old file so it doesn't get picked up on the next launch.
                    try:
                        migrated = self._legacy_config_path.with_suffix(
                            ".json.migrated"
                        )
                        self._legacy_config_path.rename(migrated)
                        logger.info(f"Legacy config renamed to {migrated}")
                    except Exception as e:
                        logger.debug(f"Could not rename legacy config: {e}")
                    return self._config
                except Exception as e:
                    logger.warning(
                        f"Could not load legacy config at {self._legacy_config_path}: {e}"
                    )

            logger.info(f"Config file not found at {self.config_path}, using defaults")
            self._config = AppConfig()
            return self._config

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._config = AppConfig.from_dict(data)
                logger.info(f"Configuration loaded from {self.config_path}")
                return self._config
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.warning(
                f"Could not read config at {self.config_path}, using defaults: {e}"
            )
            self._config = AppConfig()
            return self._config

    def save(self, config: Optional[AppConfig] = None) -> None:
        """
        Save configuration to file.

        Args:
            config: AppConfig instance to save (uses current config if None)

        Raises:
            IOError/OSError: If the config file cannot be written.
        """
        config_to_save = config or self._config
        if config_to_save is None:
            logger.warning("No configuration to save")
            return

        tmp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        try:
            # Ensure parent directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            # Write atomically: write to a temp file then replace.
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config_to_save.to_dict(), f, indent=4)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path, self.config_path)
            logger.info(f"Configuration saved to {self.config_path}")
        except Exception:
            # Clean up orphaned temp file on any failure.
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)
            raise

    @property
    def config(self) -> AppConfig:
        """Get current configuration, loading from disk on first access.

        Returns:
            The current ``AppConfig`` instance.
        """
        if self._config is None:
            self._config = self.load()
        return self._config

    @config.setter
    def config(self, value: AppConfig) -> None:
        """Set current configuration."""
        self._config = value
