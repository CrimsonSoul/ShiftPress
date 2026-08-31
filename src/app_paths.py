"""App-specific filesystem paths.

The app writes user-specific state (config/logs) to an OS-appropriate per-user
directory by default, rather than the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIRNAME = "ShiftPress"
APP_DOTNAME = ".shiftpress"

# The app was named ShiftPrint from 2026-07-31 until this rename. Existing
# installs may still keep their config there, so that location stays reachable.
LEGACY_APP_DIRNAME = "ShiftPrint"
LEGACY_APP_DOTNAME = ".shiftprint"


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

    Windows: %APPDATA%\\ShiftPress (fallback to %LOCALAPPDATA%)
    Other OSes (dev/test): ~/.shiftpress

    Returns:
        Path to the per-user data directory.
    """

    return _data_dir_for(APP_DIRNAME, APP_DOTNAME)


def get_legacy_data_dir() -> Path:
    """Return the per-user data directory used by ShiftPrint releases.

    Returns:
        Path to the pre-rename data directory. Not created.
    """

    return _data_dir_for(LEGACY_APP_DIRNAME, LEGACY_APP_DOTNAME)
