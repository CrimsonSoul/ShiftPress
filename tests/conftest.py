import importlib.util
import sys
from unittest.mock import MagicMock

import pytest

# Windows-only and GUI packages are substituted ONLY when the real package is
# absent. Mocking them unconditionally meant the suite agreed with whatever it
# was handed, so a Windows CI job now exercises the genuine pywin32 and
# tkcalendar APIs while Linux and macOS keep the mocks they need.
# Named mocks provide clearer error messages when unexpected attributes
# are accessed (vs. bare MagicMock which silently returns new mocks).
_OPTIONAL_MODULES = (
    "win32print",
    "pythoncom",
    "win32com",
    "win32com.client",
    "tkcalendar",
)

for _name in _OPTIONAL_MODULES:
    try:
        _available = importlib.util.find_spec(_name) is not None
    except (ImportError, ValueError):
        _available = False
    if not _available:
        sys.modules[_name] = MagicMock(name=_name)


# Modules that resolve the per-user data directory at call time.
_DATA_DIR_CONSUMERS = ("src.main", "src.ui", "src.logger", "src.config")


@pytest.fixture(autouse=True)
def isolate_user_data_dir(tmp_path, monkeypatch):
    """Keep the suite out of the operator's real data directory.

    ``_process_batch`` writes failure-report CSVs through ``get_data_dir()``,
    so a plain ``pytest`` run used to litter the developer's home directory
    with junk reports. Redirect every consumer at once rather than relying on
    each test to remember, and redirect the legacy accessor too so migration
    tests can never read a real config that happens to exist on the machine.

    Returns:
        The temporary directory standing in for the per-user data directory.
    """
    data_dir = tmp_path / "appdata"
    data_dir.mkdir()
    legacy_dir = tmp_path / "appdata-legacy"

    for module in _DATA_DIR_CONSUMERS:
        monkeypatch.setattr(f"{module}.get_data_dir", lambda: data_dir, raising=False)
    monkeypatch.setattr(
        "src.config.get_legacy_data_dir", lambda: legacy_dir, raising=False
    )
    return data_dir
