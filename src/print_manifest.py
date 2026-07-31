"""Pure print-selection and manifest construction for ShiftPress."""

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional, Sequence

from .scheduler import get_date_range, get_shift_template_name, validate_date_range

ShiftType = Literal["night", "day"]
DateMode = Literal["single", "range"]

__all__ = [
    "DateMode",
    "PrintJob",
    "ShiftSelection",
    "ShiftType",
    "build_print_manifest",
]


@dataclass(frozen=True)
class ShiftSelection:
    """One shift's independent include, mode, dates, and template source."""

    shift_type: ShiftType
    enabled: bool
    mode: DateMode
    start_date: Optional[date]
    end_date: Optional[date]
    folder: str

    def active_range(self) -> tuple[date, date]:
        """Return the inclusive dates that contribute jobs for this selection."""
        label = self.shift_type.title()
        if self.start_date is None:
            raise ValueError(f"Select a {label} date")
        if self.mode == "single":
            return self.start_date, self.start_date
        if self.mode != "range":
            raise ValueError(f"Invalid {label} date mode")
        if self.end_date is None:
            raise ValueError(f"Select a {label} range end date")
        return self.start_date, self.end_date

    def validate(self) -> Optional[str]:
        """Return a shift-labelled error for this selection, or None if valid.

        A disabled selection is always valid: an excluded shift contributes
        no jobs, so its date values cannot block a run.

        Returns:
            ``None`` when this selection can contribute jobs, otherwise a
            human-readable message naming the shift at fault.
        """
        if not self.enabled:
            return None
        label = self.shift_type.title()
        try:
            start_date, end_date = self.active_range()
        except ValueError as e:
            return str(e)
        is_valid, error_msg = validate_date_range(start_date, end_date)
        if not is_valid:
            return f"{label} schedule: {error_msg}"
        return None


@dataclass(frozen=True)
class PrintJob:
    """One concrete document to print."""

    date: date
    shift_type: ShiftType
    template_name: str
    folder: str


def build_print_manifest(
    selections: Sequence[ShiftSelection],
) -> tuple[PrintJob, ...]:
    """Expand enabled selections into one deterministic immutable job list."""
    jobs: list[PrintJob] = []
    for selection in selections:
        if not selection.enabled:
            continue
        start_date, end_date = selection.active_range()
        for scheduled_date in get_date_range(start_date, end_date):
            jobs.append(
                PrintJob(
                    date=scheduled_date,
                    shift_type=selection.shift_type,
                    template_name=get_shift_template_name(
                        scheduled_date, selection.shift_type
                    ),
                    folder=selection.folder,
                )
            )

    return tuple(
        sorted(
            jobs,
            key=lambda job: (
                job.date,
                0 if job.shift_type == "night" else 1,
            ),
        )
    )
