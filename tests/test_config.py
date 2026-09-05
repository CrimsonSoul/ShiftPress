"""
Unit tests for config module.
"""

import json

import pytest

from src.config import AppConfig, ConfigManager


class TestAppConfig:
    """Tests for AppConfig dataclass."""

    def test_theme_survives_settings_round_trip(self):
        """Saving Rose must restore Rose instead of silently resetting the theme."""
        config = AppConfig.from_dict({"theme": "rose"})
        assert config.to_dict().get("theme") == "rose"

    def test_unsupported_or_legacy_theme_falls_back_to_dark_midnight(self):
        """Old and edited settings must never select a light or unknown palette."""
        for value in (None, "light", "unknown", [], {}):
            config = AppConfig.from_dict({"theme": value})
            assert config.to_dict().get("theme") == "midnight"

    def test_default_values(self):
        """Default config should have empty strings."""
        config = AppConfig()
        assert config.day_folder == ""
        assert config.night_folder == ""
        assert config.printer_name == ""

    def test_with_values(self):
        """Config should store provided values."""
        config = AppConfig(
            day_folder="/path/to/day",
            night_folder="/path/to/night",
            printer_name="My Printer",
        )
        assert config.day_folder == "/path/to/day"
        assert config.night_folder == "/path/to/night"
        assert config.printer_name == "My Printer"

    def test_to_dict(self):
        """Config should convert to dictionary."""
        config = AppConfig(
            day_folder="/path/to/day",
            night_folder="/path/to/night",
            printer_name="My Printer",
        )
        result = config.to_dict()
        assert result == {
            "day_folder": "/path/to/day",
            "night_folder": "/path/to/night",
            "printer_name": "My Printer",
            "theme": "midnight",
        }

    def test_from_dict(self):
        """Config should create from dictionary."""
        data = {
            "day_folder": "/path/to/day",
            "night_folder": "/path/to/night",
            "printer_name": "My Printer",
        }
        config = AppConfig.from_dict(data)
        assert config.day_folder == "/path/to/day"
        assert config.night_folder == "/path/to/night"
        assert config.printer_name == "My Printer"

    def test_from_dict_with_missing_keys(self):
        """Config should use defaults for missing keys."""
        data = {"day_folder": "/path/to/day"}
        config = AppConfig.from_dict(data)
        assert config.day_folder == "/path/to/day"
        assert config.night_folder == ""
        assert config.printer_name == ""

    def test_from_dict_coerces_null_to_empty_string(self):
        """from_dict should coerce None values to empty strings."""
        data = {"day_folder": None, "night_folder": None, "printer_name": None}
        config = AppConfig.from_dict(data)
        assert config.day_folder == ""
        assert config.night_folder == ""
        assert config.printer_name == ""

    def test_from_dict_coerces_int_to_string(self):
        """from_dict should coerce non-string values to strings."""
        data = {"day_folder": 123, "night_folder": 456}
        config = AppConfig.from_dict(data)
        assert config.day_folder == "123"
        assert config.night_folder == "456"


class TestConfigManager:
    """Tests for ConfigManager class."""

    def test_load_nonexistent_file(self, tmp_path):
        """Loading non-existent file should return default config."""
        config_file = tmp_path / "config.json"
        manager = ConfigManager(str(config_file))
        config = manager.load()
        assert isinstance(config, AppConfig)
        assert config.day_folder == ""
        assert config.night_folder == ""
        assert config.printer_name == ""

    def test_save_and_load(self, tmp_path):
        """Saving and loading should preserve config."""
        config_file = tmp_path / "config.json"
        manager = ConfigManager(str(config_file))

        original_config = AppConfig(
            day_folder="/path/to/day",
            night_folder="/path/to/night",
            printer_name="My Printer",
        )
        manager.save(original_config)

        loaded_config = manager.load()
        assert loaded_config.day_folder == original_config.day_folder
        assert loaded_config.night_folder == original_config.night_folder
        assert loaded_config.printer_name == original_config.printer_name

    def test_load_invalid_json(self, tmp_path):
        """Loading invalid JSON should fall back to defaults (not crash)."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{ invalid json }")

        manager = ConfigManager(str(config_file))
        config = manager.load()
        # Should silently return defaults instead of raising.
        assert isinstance(config, AppConfig)
        assert config.day_folder == ""
        assert config.night_folder == ""

    def test_config_property(self, tmp_path):
        """Config property should load and cache config."""
        config_file = tmp_path / "config.json"
        manager = ConfigManager(str(config_file))

        # First access should load
        config1 = manager.config
        assert isinstance(config1, AppConfig)

        # Second access should return cached
        config2 = manager.config
        assert config1 is config2

    def test_config_setter(self, tmp_path):
        """Config setter should update cached config."""
        config_file = tmp_path / "config.json"
        manager = ConfigManager(str(config_file))

        new_config = AppConfig(
            day_folder="/new/path",
            night_folder="/new/night",
            printer_name="New Printer",
        )
        manager.config = new_config

        assert manager.config.day_folder == "/new/path"
        assert manager.config is new_config

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict should silently ignore extra keys."""
        data = {"day_folder": "/x", "unknown_key": 42, "extra": "ignored"}
        config = AppConfig.from_dict(data)
        assert config.day_folder == "/x"
        assert not hasattr(config, "unknown_key")

    def test_save_none_config_logs_warning(self, tmp_path):
        """save(None) when no config cached should log warning and return."""
        config_file = tmp_path / "config.json"
        manager = ConfigManager(str(config_file))
        # _config is None, and we pass None explicitly
        manager.save(None)
        assert not config_file.exists()

    def test_save_creates_parent_directory(self, tmp_path):
        """save() should create parent directories if needed."""
        config_file = tmp_path / "sub" / "dir" / "config.json"
        manager = ConfigManager(str(config_file))
        manager.save(AppConfig(day_folder="/test"))
        assert config_file.exists()

    def test_atomic_write_no_leftover_tmp(self, tmp_path):
        """save() should not leave a .tmp file on success."""
        config_file = tmp_path / "config.json"
        manager = ConfigManager(str(config_file))
        manager.save(AppConfig(day_folder="/test"))
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_legacy_migration(self, tmp_path):
        """Should migrate legacy config.json from working dir to new path."""
        # Create a legacy config in the working directory
        import os

        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            legacy_file = tmp_path / "config.json"
            legacy_file.write_text(
                json.dumps({"day_folder": "/legacy/day", "printer_name": "OldPrinter"})
            )

            new_path = tmp_path / "appdata" / "config.json"
            manager = ConfigManager()
            # Override paths to use our tmp locations
            manager.config_path = new_path
            manager._legacy_config_path = legacy_file
            manager._allow_legacy_migration = True

            config = manager.load()
            assert config.day_folder == "/legacy/day"
            assert config.printer_name == "OldPrinter"
            # New file should be created
            assert new_path.exists()
            # Legacy file should be renamed
            assert not legacy_file.exists()
            migrated = legacy_file.with_suffix(".json.migrated")
            assert migrated.exists()
        finally:
            os.chdir(old_cwd)


class TestPreRenameMigration:
    """Config saved under the old ShiftPrint data directory must survive."""

    def test_migrates_config_from_pre_rename_data_dir(self, tmp_path):
        """An operator returning from ShiftPrint keeps their saved setup."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "config.json").write_text(
            json.dumps({"day_folder": "/old/day", "printer_name": "OldPrinter"})
        )

        manager = ConfigManager()
        manager.config_path = tmp_path / "current" / "config.json"
        manager._legacy_data_config_path = legacy_dir / "config.json"
        manager._legacy_config_path = tmp_path / "nonexistent-cwd" / "config.json"
        manager._allow_legacy_migration = True

        config = manager.load()

        assert config.day_folder == "/old/day"
        assert config.printer_name == "OldPrinter"
        assert manager.config_path.exists()

    def test_pre_rename_config_is_renamed_after_migration(self, tmp_path):
        """The old file must not be re-migrated over a later edit."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        legacy_file = legacy_dir / "config.json"
        legacy_file.write_text(json.dumps({"day_folder": "/old/day"}))

        manager = ConfigManager()
        manager.config_path = tmp_path / "current" / "config.json"
        manager._legacy_data_config_path = legacy_file
        manager._legacy_config_path = tmp_path / "nonexistent-cwd" / "config.json"
        manager._allow_legacy_migration = True

        manager.load()

        assert not legacy_file.exists()
        assert (legacy_dir / "config.json.migrated").exists()

    def test_failed_migration_write_keeps_legacy_config_for_retry(
        self, tmp_path, monkeypatch
    ):
        """A failed destination write must leave the recoverable source intact."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        legacy_file = legacy_dir / "config.json"
        legacy_file.write_text(json.dumps({"day_folder": "/old/day"}))

        manager = ConfigManager()
        manager.config_path = tmp_path / "current" / "config.json"
        manager._legacy_data_config_path = legacy_file
        manager._legacy_config_path = tmp_path / "missing" / "config.json"
        manager._allow_legacy_migration = True

        def fail_save(config):
            raise OSError("disk full")

        monkeypatch.setattr(manager, "save", fail_save)

        config = manager.load()

        assert config.day_folder == "/old/day"
        assert legacy_file.exists()
        assert not legacy_file.with_suffix(".json.migrated").exists()

    def test_existing_config_wins_over_pre_rename_one(self, tmp_path):
        """Migration must never overwrite a config the operator already has."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "config.json").write_text(json.dumps({"day_folder": "/old/day"}))
        new_dir = tmp_path / "current"
        new_dir.mkdir()
        (new_dir / "config.json").write_text(json.dumps({"day_folder": "/current/day"}))

        manager = ConfigManager()
        manager.config_path = new_dir / "config.json"
        manager._legacy_data_config_path = legacy_dir / "config.json"
        manager._allow_legacy_migration = True

        assert manager.load().day_folder == "/current/day"

    def test_unreadable_pre_rename_config_falls_back_to_defaults(self, tmp_path):
        """A corrupt old config must not stop the app from starting."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "config.json").write_text("{ not valid json")

        manager = ConfigManager()
        manager.config_path = tmp_path / "current" / "config.json"
        manager._legacy_data_config_path = legacy_dir / "config.json"
        manager._legacy_config_path = tmp_path / "nonexistent-cwd" / "config.json"
        manager._allow_legacy_migration = True

        config = manager.load()

        assert config.day_folder == ""
        assert config.printer_name == ""
