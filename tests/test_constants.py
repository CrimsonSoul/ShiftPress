"""Tests for platform-specific UI constants."""

from unittest.mock import patch

from src.constants import _font_families


def test_windows_uses_text_and_display_variable_font_roles():
    """Windows body copy and headings should use their intended optical roles."""
    with patch("sys.platform", "win32"):
        body, display = _font_families()

    assert body == "Segoe UI Variable Text"
    assert display == "Segoe UI Variable Display"
