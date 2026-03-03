"""App-specific filesystem paths.

The app writes user-specific state (config/logs) to an OS-appropriate per-user
directory by default, rather than the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path


APP_DIRNAME = "ShiftPress"


def get_data_dir() -> Path:
    """Return the per-user data directory for the app.

    The directory is *not* created by this function; callers are responsible
    for calling ``mkdir()`` if needed.

    Windows: %APPDATA%\\ShiftPress (fallback to %LOCALAPPDATA%)
    Other OSes (dev/test): ~/.shiftpress

    Returns:
        Path to the per-user data directory.
    """

    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_DIRNAME
        return Path.home() / APP_DIRNAME

    # Non-Windows environments are primarily for development/tests.
    return Path.home() / ".shiftpress"
