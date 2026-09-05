"""Tests for platform-specific UI constants."""

from unittest.mock import patch

from src.constants import _font_families


def test_windows_uses_distinct_installed_display_and_form_fonts():
    """Expressive headings should pair with a familiar, available form face."""
    with patch("sys.platform", "win32"):
        body, display = _font_families()

    assert body == "Segoe UI"
    assert display == "Bahnschrift"
