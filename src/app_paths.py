"""App-specific filesystem paths.

The app writes user-specific state (config/logs) to an OS-appropriate per-user
directory by default, rather than the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIRNAME = "ShiftPrint"
APP_DOTNAME = ".shiftprint"

# The app was named ShiftPress before 2026-07-31. Existing installs still keep
# their config there, so the old location stays reachable for migration.
LEGACY_APP_DIRNAME = "ShiftPress"
LEGACY_APP_DOTNAME = ".shiftpress"


def _data_dir_for(app_dirname: str, dotname: str) -> Path:
    """Return the per-user directory for one app identity.

    Args:
        app_dirname: Windows directory name under %APPDATA%.
        dotname: Dot-directory name used on other platforms.

    Returns:
        Path to the per-user data directory. Not created.
    """

    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / app_dirname
        return Path.home() / app_dirname

    # Non-Windows environments are primarily for development/tests.
    return Path.home() / dotname


def get_data_dir() -> Path:
    """Return the per-user data directory for the app.

    The directory is *not* created by this function; callers are responsible
    for calling ``mkdir()`` if needed.

    Windows: %APPDATA%\\ShiftPrint (fallback to %LOCALAPPDATA%)
    Other OSes (dev/test): ~/.shiftprint

    Returns:
        Path to the per-user data directory.
    """

    return _data_dir_for(APP_DIRNAME, APP_DOTNAME)


def get_legacy_data_dir() -> Path:
    """Return the per-user data directory used before the ShiftPrint rename.

    Returns:
        Path to the pre-rename data directory. Not created.
    """

    return _data_dir_for(LEGACY_APP_DIRNAME, LEGACY_APP_DOTNAME)
