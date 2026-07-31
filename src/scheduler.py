"""
Date and scheduling logic for ShiftPrint application.

This module handles date calculations, including special scheduling rules
like third Thursday detection.
"""

from datetime import date, timedelta

from typing import Optional

from .constants import THURSDAY, MAX_DAYS_RANGE
from .logger import get_logger

__all__ = [
    "is_third_thursday",
    "get_shift_template_name",
    "get_english_day_name",
    "get_english_month_name",
    "validate_date_range",
    "get_date_range",
]

logger = get_logger(__name__)

# Locale-independent English day and month names.
# Hard-coded because both strftime("%A"/"%B") and calendar.day_name/month_name
# are locale-dependent and return non-English strings on non-English Windows.
_EN_DAY_NAMES: list[str] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
_EN_MONTH_NAMES: list[str] = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def get_english_day_name(dt: date) -> str:
    """Return the English day name for *dt*, independent of system locale.

    Args:
        dt: The date to get the day name for.

    Returns:
        Full English day name (e.g. ``"Thursday"``).
    """
    return _EN_DAY_NAMES[dt.weekday()]


def get_english_month_name(dt: date) -> str:
    """Return the English month name for *dt*, independent of system locale.

    Args:
        dt: The date to get the month name for.

    Returns:
        Full English month name (e.g. ``"January"``).
    """
    return _EN_MONTH_NAMES[dt.month]


def is_third_thursday(dt: date) -> bool:
    """
    Check if a given date is the third Thursday of its month.

    Args:
        dt: The date to check

    Returns:
        True if the date is the third Thursday, False otherwise

    Examples:
        >>> is_third_thursday(date(2026, 1, 15))  # Third Thursday of January 2026
        True
        >>> is_third_thursday(date(2026, 1, 8))   # Second Thursday
        False
    """
    if dt.weekday() != THURSDAY:
        return False

    # The third occurrence of any weekday always falls between the 15th and 21st
    is_third = 15 <= dt.day <= 21
    logger.debug(f"Date {dt} is third Thursday: {is_third}")
    return is_third


def get_shift_template_name(dt: date, shift_type: str = "day") -> str:
    """
    Get the template name for a given date and shift type.

    Args:
        dt: The date to get the template for
        shift_type: Either "day" or "night"

    Returns:
        The template name (e.g., "Thursday", "Thursday Night", "THIRD Thursday")

    Raises:
        ValueError: If shift_type is not "day" or "night"
    """
    if shift_type not in ("day", "night"):
        raise ValueError(f"shift_type must be 'day' or 'night', got '{shift_type}'")

    day_name = get_english_day_name(dt)

    if shift_type == "day":
        # Day shift uses "THIRD Thursday" for third Thursdays
        template_name = "THIRD Thursday" if is_third_thursday(dt) else day_name
    else:
        # Night shift always uses "DayName Night"
        template_name = f"{day_name} Night"

    logger.debug(f"{shift_type.title()} shift for {dt}: {template_name}")
    return template_name


def validate_date_range(start_date: date, end_date: date) -> tuple[bool, Optional[str]]:
    """
    Validate that a date range is valid.

    Args:
        start_date: The start date
        end_date: The end date

    Returns:
        Tuple of (is_valid, error_message)
    """
    if end_date < start_date:
        return False, "End date cannot be before start date"

    total_days = (end_date - start_date).days + 1
    if total_days > MAX_DAYS_RANGE:
        return False, f"Date range exceeds maximum allowed ({MAX_DAYS_RANGE} days)"

    return True, None


def get_date_range(start_date: date, end_date: date) -> list[date]:
    """
    Get a list of dates in the given range (inclusive).

    Args:
        start_date: The start date
        end_date: The end date

    Returns:
        List of dates from start_date to end_date (inclusive)

    Raises:
        ValueError: If end_date is before start_date
    """
    is_valid, error_msg = validate_date_range(start_date, end_date)
    if not is_valid:
        raise ValueError(error_msg)

    delta = (end_date - start_date).days
    return [start_date + timedelta(days=i) for i in range(delta + 1)]
