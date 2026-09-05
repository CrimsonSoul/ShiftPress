"""
Constants for ShiftPress application.

This module contains all named constants used throughout the application
to avoid magic numbers and strings.
"""

from dataclasses import dataclass, replace
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
    "WINDOW_RESIZABLE",
    "PROGRESS_MAX",
    "MAX_DAYS_RANGE",
    "COM_RETRIES",
    "COM_RETRY_DELAY",
    "WD_FIND_CONTINUE",
    "WD_REPLACE_ALL",
    "PROTECTION_ALLOW_FORM_FIELDS",
    "LARGE_BATCH_THRESHOLD",
    "MAX_PREFLIGHT_MISSING_SHOWN",
    "MAX_FAILURE_SUMMARY_SHOWN",
    "MAX_FILENAME_LENGTH",
    "AUTO_RESIZE_MIN_WIDTH",
    "AUTO_RESIZE_MIN_HEIGHT",
    "COLORS",
    "FONTS",
    "THEMES",
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
WINDOW_WIDTH: Final = 1120
WINDOW_RESIZABLE: Final = True

# Progress bar
PROGRESS_MAX: Final = 100

# Date validation (366 to accommodate full leap-year ranges)
MAX_DAYS_RANGE: Final = 366

# Batch processing thresholds
LARGE_BATCH_THRESHOLD: Final = 30  # documents — prompt user for confirmation
MAX_PREFLIGHT_MISSING_SHOWN: Final = 10  # missing templates shown before truncation
MAX_FAILURE_SUMMARY_SHOWN: Final = 5  # failures shown in the summary dialog

# Path safety
MAX_FILENAME_LENGTH: Final = 255

# UI sizing limits (height is derived from rendered content at launch)
AUTO_RESIZE_MIN_WIDTH: Final = 320
AUTO_RESIZE_MIN_HEIGHT: Final = 400

# Retry settings for COM calls
COM_RETRIES: Final = 5
COM_RETRY_DELAY: Final = 1  # seconds

# Word Find/Replace constants
# See: https://learn.microsoft.com/en-us/office/vba/api/word.wdfindwrap
WD_FIND_CONTINUE: Final = 1  # wdFindContinue
# See: https://learn.microsoft.com/en-us/office/vba/api/word.wdreplace
WD_REPLACE_ALL: Final = 2  # wdReplaceAll


@dataclass(frozen=True)
class Colors:
    """Color scheme constants for the application UI."""

    background: str = "#091422"
    surface: str = "#0C1826"
    input: str = "#131C27"
    accent: str = "#F2B340"  # Press amber — Setup title and selection chrome
    night_accent: str = "#8BCFF5"
    day_accent: str = "#ECC17E"
    action: str = "#8EBBFF"
    action_hover: str = "#B0CFFF"
    action_text: str = "#102038"
    text_main: str = "#F2F6FC"
    text_dim: str = "#B4C2D4"
    success: str = "#4ADE80"  # Emerald-400
    error: str = "#FB7185"  # Rose-400 — softer red
    border: str = "#44556B"
    secondary: str = "#29374A"
    accent_hover: str = "#D99A25"  # Deeper amber press state
    header: str = "#081221"
    night_surface: str = "#203248"
    day_surface: str = "#332D24"


FontSpec = Union[tuple[str, int], tuple[str, int, str]]


def _font_families() -> tuple[str, str]:
    """Return platform-appropriate body and display font families.

    Returns:
        Tuple containing body-copy and heading font family names.
    """
    import sys

    if sys.platform == "darwin":
        return "Avenir Next", "Avenir Next"
    if sys.platform.startswith("linux"):
        return "Ubuntu", "Ubuntu"
    # Both ship with supported Windows 10/11 installations. Bahnschrift lends
    # the schedule headings a precise, industrial voice; Segoe keeps forms familiar.
    return "Segoe UI", "Bahnschrift"


_BODY_FONT_FAMILY, _DISPLAY_FONT_FAMILY = _font_families()


@dataclass(frozen=True)
class Fonts:
    """Font configuration for the application UI."""

    main: FontSpec = (_BODY_FONT_FAMILY, 11)
    bold: FontSpec = (_BODY_FONT_FAMILY, 11, "bold")
    header: FontSpec = (_DISPLAY_FONT_FAMILY, 24, "bold")
    brand: FontSpec = (_DISPLAY_FONT_FAMILY, 29, "bold")
    section: FontSpec = (_DISPLAY_FONT_FAMILY, 18, "bold")
    card_title: FontSpec = (_DISPLAY_FONT_FAMILY, 13, "bold")
    sub: FontSpec = (_BODY_FONT_FAMILY, 10)
    button: FontSpec = (_BODY_FONT_FAMILY, 14, "bold")


# Global color and font instances
COLORS = Colors()
THEMES = {
    "midnight": COLORS,
    "rose": replace(
        COLORS,
        background="#15131B",
        surface="#171620",
        input="#191620",
        header="#160F1E",
        border="#514558",
        text_main="#F8F3F8",
        text_dim="#C0ADC3",
        action="#E59AC8",
        action_hover="#F0B9DC",
        action_text="#251522",
        secondary="#352C3D",
        night_accent="#B7B5ED",
        day_accent="#E9B77E",
        night_surface="#252339",
        day_surface="#35272B",
    ),
}
FONTS = Fonts()
