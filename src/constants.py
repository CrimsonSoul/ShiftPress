"""
Constants for ShiftPress application.

This module contains all named constants used throughout the application
to avoid magic numbers and strings.
"""

from dataclasses import dataclass
from typing import Final, Union

__all__ = [
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
    "PROTECTION_NONE",
    "PROTECTION_READ_ONLY",
    "PROTECTION_ALLOW_COMMENTS",
    "PROTECTION_ALLOW_REVISIONS",
    "CLOSE_NO_SAVE",
    "CLOSE_SAVE",
    "CLOSE_PROMPT",
    "PRINTER_ENUM_LOCAL",
    "PRINTER_ENUM_CONNECTIONS",
    "DEFAULT_PRINTER_LABEL",
    "DOCX_EXTENSION",
    "CONFIG_FILENAME",
    "LOG_FILENAME",
    "WINDOW_WIDTH",
    "WINDOW_HEIGHT",
    "WINDOW_RESIZABLE",
    "PROGRESS_MAX",
    "MAX_DAYS_RANGE",
    "COM_RETRIES",
    "COM_RETRY_DELAY",
    "WD_PRIMARY_HEADER_STORY",
    "WD_EVEN_PAGES_HEADER_STORY",
    "WD_PRIMARY_FOOTER_STORY",
    "WD_EVEN_PAGES_FOOTER_STORY",
    "WD_FIRST_PAGE_HEADER_STORY",
    "WD_FIRST_PAGE_FOOTER_STORY",
    "WD_FIND_CONTINUE",
    "WD_REPLACE_ALL",
    "PROTECTION_ALLOW_FORM_FIELDS",
    "LARGE_BATCH_THRESHOLD",
    "MAX_PREFLIGHT_MISSING_SHOWN",
    "MAX_FAILURE_SUMMARY_SHOWN",
    "MAX_FILENAME_LENGTH",
    "WINDOW_MIN_HEIGHT",
    "AUTO_RESIZE_MIN_WIDTH",
    "AUTO_RESIZE_MIN_HEIGHT",
    "COLORS",
    "FONTS",
]

# Weekday constants (Python's datetime.weekday() returns 0=Monday, 6=Sunday)
MONDAY: Final = 0
TUESDAY: Final = 1
WEDNESDAY: Final = 2
THURSDAY: Final = 3
FRIDAY: Final = 4
SATURDAY: Final = 5
SUNDAY: Final = 6

# Word document protection types (Word API wdProtectionType)
# https://learn.microsoft.com/en-us/office/vba/api/word.wdprotectiontype
PROTECTION_NONE: Final = -1  # wdNoProtection
PROTECTION_ALLOW_REVISIONS: Final = 0  # wdAllowOnlyRevisions
PROTECTION_ALLOW_COMMENTS: Final = 1  # wdAllowOnlyComments
PROTECTION_ALLOW_FORM_FIELDS: Final = 2  # wdAllowOnlyFormFields
PROTECTION_READ_ONLY: Final = 3  # wdAllowOnlyReading

# Word document close options (Word API wdSaveOptions)
# https://learn.microsoft.com/en-us/office/vba/api/word.wdsaveoptions
CLOSE_NO_SAVE: Final = 0  # wdDoNotSaveChanges
CLOSE_SAVE: Final = -1  # wdSaveChanges
CLOSE_PROMPT: Final = -2  # wdPromptToSaveChanges

# Windows printer enumeration constants (win32print flags)
PRINTER_ENUM_LOCAL: Final = 2  # PRINTER_ENUM_LOCAL
PRINTER_ENUM_CONNECTIONS: Final = (
    4  # PRINTER_ENUM_CONNECTIONS (user-connected printers)
)

# UI default labels
DEFAULT_PRINTER_LABEL: Final = "Choose Printer"

# File extensions
DOCX_EXTENSION: Final = ".docx"

# Configuration
CONFIG_FILENAME: Final = "config.json"
LOG_FILENAME: Final = "shiftpress.log"

# UI Constants
WINDOW_WIDTH: Final = 640
WINDOW_HEIGHT: Final = 820
WINDOW_RESIZABLE: Final = True

# Progress bar
PROGRESS_MAX: Final = 100

# Date validation (366 to accommodate full leap-year ranges)
MAX_DAYS_RANGE: Final = 366

# Batch processing thresholds
LARGE_BATCH_THRESHOLD: Final = 30  # days — prompt user for confirmation
MAX_PREFLIGHT_MISSING_SHOWN: Final = 10  # missing templates shown before truncation
MAX_FAILURE_SUMMARY_SHOWN: Final = 5  # failures shown in the summary dialog

# Path safety
MAX_FILENAME_LENGTH: Final = 255

# UI sizing limits
WINDOW_MIN_HEIGHT: Final = 720
AUTO_RESIZE_MIN_WIDTH: Final = 320
AUTO_RESIZE_MIN_HEIGHT: Final = 400

# Retry settings for COM calls
COM_RETRIES: Final = 5
COM_RETRY_DELAY: Final = 1  # seconds

# Word story types (used to target header/footer-only replacements)
# https://learn.microsoft.com/en-us/office/vba/api/word.wdstorytype
WD_EVEN_PAGES_HEADER_STORY: Final = 6  # wdEvenPagesHeaderStory
WD_PRIMARY_HEADER_STORY: Final = 7  # wdPrimaryHeaderStory
WD_EVEN_PAGES_FOOTER_STORY: Final = 8  # wdEvenPagesFooterStory
WD_PRIMARY_FOOTER_STORY: Final = 9  # wdPrimaryFooterStory
WD_FIRST_PAGE_HEADER_STORY: Final = 10  # wdFirstPageHeaderStory
WD_FIRST_PAGE_FOOTER_STORY: Final = 11  # wdFirstPageFooterStory

# Word Find/Replace constants
# See: https://learn.microsoft.com/en-us/office/vba/api/word.wdfindwrap
WD_FIND_CONTINUE: Final = 1  # wdFindContinue
# See: https://learn.microsoft.com/en-us/office/vba/api/word.wdreplace
WD_REPLACE_ALL: Final = 2  # wdReplaceAll


@dataclass(frozen=True)
class Colors:
    """Color scheme constants for the application UI."""

    background: str = "#18181B"  # Zinc-900 — warm near-black
    surface: str = "#27272A"  # Zinc-800 — warm card surface
    accent: str = "#F59E0B"  # Amber-500 — warm, distinctive
    text_main: str = "#F4F4F5"  # Zinc-100 — warm off-white
    text_dim: str = "#A1A1AA"  # Zinc-400 — readable secondary
    success: str = "#34D399"  # Emerald-400
    error: str = "#FB7185"  # Rose-400 — softer red
    border: str = "#3F3F46"  # Zinc-700 — visible borders
    secondary: str = "#323238"  # Hover states
    accent_hover: str = "#D97706"  # Amber-600 — deeper press state


FontSpec = Union[tuple[str, int], tuple[str, int, str]]


def _font_family() -> str:
    """Return a platform-appropriate font family name.

    Returns:
        Font family name string suitable for the current OS.
    """
    import sys

    if sys.platform == "darwin":
        return "SF Pro Text"
    if sys.platform.startswith("linux"):
        return "Ubuntu"
    # Windows — prefer the variable font (Windows 11+); Tkinter silently
    # falls back to "Segoe UI" (Windows 7+) if the variable font is absent.
    return "Segoe UI Variable Display"


_FONT_FAMILY: Final = _font_family()


@dataclass(frozen=True)
class Fonts:
    """Font configuration for the application UI."""

    main: FontSpec = (_FONT_FAMILY, 10)
    bold: FontSpec = (_FONT_FAMILY, 10, "bold")
    header: FontSpec = (_FONT_FAMILY, 20, "bold")
    card_title: FontSpec = (_FONT_FAMILY, 11, "bold")
    sub: FontSpec = (_FONT_FAMILY, 9)
    button: FontSpec = (_FONT_FAMILY, 11, "bold")


# Global color and font instances
COLORS = Colors()
FONTS = Fonts()
