"""Tests for independent shift selection and print manifest construction."""

from datetime import date

import pytest

from src.print_manifest import PrintJob, ShiftSelection, build_print_manifest


def _selection(
    shift_type: str,
    *,
    enabled: bool = True,
    mode: str = "single",
    start_date: date = date(2026, 7, 30),
    end_date: date = date(2026, 7, 30),
    folder: str = "/templates",
) -> ShiftSelection:
    """Build a concise selection fixture with explicit caller-controlled values."""
    return ShiftSelection(
        shift_type=shift_type,
        enabled=enabled,
        mode=mode,
        start_date=start_date,
        end_date=end_date,
        folder=folder,
    )


def test_builds_night_only_single_date() -> None:
    """A Night-only selection should produce exactly one Night job."""
    manifest = build_print_manifest((_selection("night"),))

    assert manifest == (
        PrintJob(
            date=date(2026, 7, 30),
            shift_type="night",
            template_name="Thursday Night",
            folder="/templates",
        ),
    )


def test_builds_day_only_single_date() -> None:
    """A Day-only selection should produce exactly one Day job."""
    manifest = build_print_manifest(
        (
            _selection(
                "day",
                start_date=date(2026, 7, 31),
                end_date=date(2026, 7, 31),
                folder="/day",
            ),
        )
    )

    assert manifest == (
        PrintJob(
            date=date(2026, 7, 31),
            shift_type="day",
            template_name="Friday",
            folder="/day",
        ),
    )


def test_ignores_disabled_shift_with_missing_values() -> None:
    """Disabled shifts must not contribute jobs or require dates."""
    disabled_day = ShiftSelection(
        shift_type="day",
        enabled=False,
        mode="range",
        start_date=None,
        end_date=None,
        folder="",
    )

    manifest = build_print_manifest((_selection("night"), disabled_day))

    assert [(job.date, job.shift_type) for job in manifest] == [
        (date(2026, 7, 30), "night")
    ]


def test_single_mode_ignores_preserved_range_end() -> None:
    """Single mode must produce one job even if a prior range end is preserved."""
    manifest = build_print_manifest(
        (
            _selection(
                "day",
                mode="single",
                start_date=date(2026, 7, 31),
                end_date=date(2026, 8, 8),
            ),
        )
    )

    assert [job.date for job in manifest] == [date(2026, 7, 31)]


def test_expands_independent_ranges_and_sorts_chronologically() -> None:
    """Differing ranges should merge by date without coupling their bounds."""
    manifest = build_print_manifest(
        (
            _selection(
                "night",
                mode="range",
                start_date=date(2026, 7, 31),
                end_date=date(2026, 8, 1),
                folder="/night",
            ),
            _selection(
                "day",
                mode="range",
                start_date=date(2026, 7, 30),
                end_date=date(2026, 7, 31),
                folder="/day",
            ),
        )
    )

    assert [(job.date, job.shift_type) for job in manifest] == [
        (date(2026, 7, 30), "day"),
        (date(2026, 7, 31), "night"),
        (date(2026, 7, 31), "day"),
        (date(2026, 8, 1), "night"),
    ]


def test_sorts_night_before_day_on_the_same_date() -> None:
    """Same-date jobs should put Night before Day regardless of input order."""
    manifest = build_print_manifest(
        (
            _selection("day", folder="/day"),
            _selection("night", folder="/night"),
        )
    )

    assert [job.shift_type for job in manifest] == ["night", "day"]


def test_preserves_existing_third_thursday_template_rule() -> None:
    """Manifest construction must retain the special Day template name."""
    manifest = build_print_manifest(
        (
            _selection(
                "day",
                start_date=date(2026, 1, 15),
                end_date=date(2026, 1, 15),
            ),
        )
    )

    assert manifest[0].template_name == "THIRD Thursday"


@pytest.mark.parametrize("mode", ["weekly", ""])
def test_rejects_unknown_mode(mode: str) -> None:
    """Unknown modes must fail instead of silently choosing date semantics."""
    selection = _selection("night", mode=mode)

    with pytest.raises(ValueError, match="mode"):
        build_print_manifest((selection,))


def test_rejects_missing_active_date() -> None:
    """An enabled selection without its active date must fail clearly."""
    selection = ShiftSelection(
        shift_type="day",
        enabled=True,
        mode="single",
        start_date=None,
        end_date=None,
        folder="/day",
    )

    with pytest.raises(ValueError, match="Day date"):
        build_print_manifest((selection,))


def test_rejects_missing_range_end() -> None:
    """Range mode must require its own end date."""
    selection = ShiftSelection(
        shift_type="night",
        enabled=True,
        mode="range",
        start_date=date(2026, 7, 30),
        end_date=None,
        folder="/night",
    )

    with pytest.raises(ValueError, match="Night range end"):
        build_print_manifest((selection,))


def test_validate_accepts_a_valid_single_date() -> None:
    """A well-formed single-date selection has no error."""
    assert _selection("night").validate() is None


def test_validate_ignores_a_disabled_selection() -> None:
    """A shift that is not included cannot be invalid."""
    selection = _selection(
        "day",
        enabled=False,
        mode="range",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 1),
    )

    assert selection.validate() is None


def test_validate_labels_a_reversed_range_with_its_shift() -> None:
    """A reversed range must name the shift it belongs to."""
    selection = _selection(
        "night",
        mode="range",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 1),
    )

    error = selection.validate()

    assert error is not None
    assert error.startswith("Night schedule:")
    assert "End date cannot be before start date" in error


def test_validate_labels_a_missing_date_with_its_shift() -> None:
    """A missing date must name the shift it belongs to."""
    selection = _selection("day", start_date=None, end_date=None)

    assert selection.validate() == "Select a Day date"
