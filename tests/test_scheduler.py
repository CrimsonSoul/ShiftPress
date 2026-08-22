"""
Unit tests for scheduler module.
"""

import pytest
from datetime import date

from src.scheduler import (
    is_third_thursday,
    get_shift_template_name,
    get_english_day_name,
    get_english_month_name,
    validate_date_range,
    get_date_range,
)


class TestIsThirdThursday:
    """Tests for is_third_thursday function."""

    def test_third_thursday_january_2026(self):
        """January 15, 2026 is the third Thursday."""
        assert is_third_thursday(date(2026, 1, 15)) is True

    def test_second_thursday_january_2026(self):
        """January 8, 2026 is the second Thursday."""
        assert is_third_thursday(date(2026, 1, 8)) is False

    def test_fourth_thursday_january_2026(self):
        """January 22, 2026 is the fourth Thursday."""
        assert is_third_thursday(date(2026, 1, 22)) is False

    def test_not_thursday(self):
        """January 15, 2026 is a Thursday, but January 14 is Wednesday."""
        assert is_third_thursday(date(2026, 1, 14)) is False

    def test_third_thursday_february_2026(self):
        """February 19, 2026 is the third Thursday."""
        assert is_third_thursday(date(2026, 2, 19)) is True

    def test_third_thursday_march_2026(self):
        """March 19, 2026 is the third Thursday."""
        assert is_third_thursday(date(2026, 3, 19)) is True

    def test_third_thursday_may_2026(self):
        """May 21, 2026 is the third Thursday."""
        assert is_third_thursday(date(2026, 5, 21)) is True

    def test_second_thursday_may_2026(self):
        """May 14, 2026 is the second Thursday."""
        assert is_third_thursday(date(2026, 5, 14)) is False


class TestGetShiftTemplateName:
    """Tests for get_shift_template_name function."""

    def test_day_shift_regular_day(self):
        """Regular day shift should use day name."""
        result = get_shift_template_name(date(2026, 1, 14), "day")
        assert result == "Wednesday"

    def test_day_shift_third_thursday(self):
        """Third Thursday day shift should use 'THIRD Thursday'."""
        result = get_shift_template_name(date(2026, 1, 15), "day")
        assert result == "THIRD Thursday"

    def test_night_shift_regular_day(self):
        """Night shift should use 'DayName Night' format."""
        result = get_shift_template_name(date(2026, 1, 14), "night")
        assert result == "Wednesday Night"

    def test_night_shift_third_thursday(self):
        """Night shift on third Thursday should still use 'DayName Night'."""
        result = get_shift_template_name(date(2026, 1, 15), "night")
        assert result == "Thursday Night"

    def test_invalid_shift_type(self):
        """Invalid shift type should raise ValueError."""
        target_date = date(2026, 1, 14)

        with pytest.raises(ValueError, match="shift_type must be 'day' or 'night'"):
            get_shift_template_name(target_date, "invalid")


class TestValidateDateRange:
    """Tests for validate_date_range function."""

    def test_valid_range(self):
        """Valid date range should return True."""
        start = date(2026, 1, 1)
        end = date(2026, 1, 31)
        is_valid, error = validate_date_range(start, end)
        assert is_valid is True
        assert error is None

    def test_same_day(self):
        """Same start and end date should be valid."""
        start = date(2026, 1, 15)
        end = date(2026, 1, 15)
        is_valid, error = validate_date_range(start, end)
        assert is_valid is True
        assert error is None

    def test_end_before_start(self):
        """End date before start date should be invalid."""
        start = date(2026, 1, 31)
        end = date(2026, 1, 1)
        is_valid, error = validate_date_range(start, end)
        assert is_valid is False
        assert error == "End date cannot be before start date"

    def test_range_too_large(self):
        """Range exceeding MAX_DAYS_RANGE should be invalid."""
        start = date(2026, 1, 1)
        end = date(2027, 1, 2)  # 367 days
        is_valid, error = validate_date_range(start, end)
        assert is_valid is False
        assert "exceeds maximum" in error


class TestGetDateRange:
    """Tests for get_date_range function."""

    def test_single_day(self):
        """Single day range should return list with one date."""
        start = date(2026, 1, 15)
        end = date(2026, 1, 15)
        result = get_date_range(start, end)
        assert result == [date(2026, 1, 15)]

    def test_multiple_days(self):
        """Multiple day range should return all dates."""
        start = date(2026, 1, 1)
        end = date(2026, 1, 3)
        result = get_date_range(start, end)
        assert result == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]

    def test_week_range(self):
        """Week range should return 7 dates."""
        start = date(2026, 1, 4)  # Monday
        end = date(2026, 1, 10)  # Sunday
        result = get_date_range(start, end)
        assert len(result) == 7
        assert result[0] == date(2026, 1, 4)
        assert result[-1] == date(2026, 1, 10)

    def test_invalid_range_raises_error(self):
        """Invalid range should raise ValueError."""
        start = date(2026, 1, 31)
        end = date(2026, 1, 1)
        with pytest.raises(ValueError, match="End date cannot be before start date"):
            get_date_range(start, end)

    def test_range_too_large_raises_error(self):
        """Range exceeding MAX_DAYS_RANGE should raise ValueError."""
        start = date(2026, 1, 1)
        end = date(2027, 1, 2)  # 367 days
        with pytest.raises(ValueError, match="Date range exceeds maximum allowed"):
            get_date_range(start, end)


class TestGetEnglishDayName:
    """Tests for get_english_day_name function."""

    @pytest.mark.parametrize(
        "dt, expected",
        [
            (date(2026, 1, 12), "Monday"),
            (date(2026, 1, 13), "Tuesday"),
            (date(2026, 1, 14), "Wednesday"),
            (date(2026, 1, 15), "Thursday"),
            (date(2026, 1, 16), "Friday"),
            (date(2026, 1, 17), "Saturday"),
            (date(2026, 1, 18), "Sunday"),
        ],
    )
    def test_all_day_names(self, dt, expected):
        """get_english_day_name should return the correct English name for each weekday."""
        assert get_english_day_name(dt) == expected

    def test_returns_string(self):
        """get_english_day_name should always return a string."""
        result = get_english_day_name(date(2026, 6, 15))
        assert isinstance(result, str)
        assert len(result) > 0


class TestGetEnglishMonthName:
    """Tests for get_english_month_name function."""

    @pytest.mark.parametrize(
        "dt, expected",
        [
            (date(2026, 1, 1), "January"),
            (date(2026, 2, 1), "February"),
            (date(2026, 3, 1), "March"),
            (date(2026, 4, 1), "April"),
            (date(2026, 5, 1), "May"),
            (date(2026, 6, 1), "June"),
            (date(2026, 7, 1), "July"),
            (date(2026, 8, 1), "August"),
            (date(2026, 9, 1), "September"),
            (date(2026, 10, 1), "October"),
            (date(2026, 11, 1), "November"),
            (date(2026, 12, 1), "December"),
        ],
    )
    def test_all_month_names(self, dt, expected):
        """get_english_month_name should return the correct English name for each month."""
        assert get_english_month_name(dt) == expected

    def test_returns_string(self):
        """get_english_month_name should always return a string."""
        result = get_english_month_name(date(2026, 6, 15))
        assert isinstance(result, str)
        assert len(result) > 0
