import importlib.util
import sys
from unittest.mock import MagicMock

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
