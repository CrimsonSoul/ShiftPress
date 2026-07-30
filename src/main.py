"""
ShiftPress - Main Application Entry Point

Batch print shift schedules via Word COM automation.
"""

import threading
import csv
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Optional, Callable, TypedDict

import tkinter as tk

from .config import ConfigManager, AppConfig
from .scheduler import get_english_day_name
from .constants import (
    PROGRESS_MAX,
    COLORS,
    DEFAULT_PRINTER_LABEL,
    LOG_FILENAME,
    LARGE_BATCH_THRESHOLD,
    MAX_PREFLIGHT_MISSING_SHOWN,
    MAX_FAILURE_SUMMARY_SHOWN,
)

from .logger import setup_logging, get_logger
from .path_validation import validate_folder_path
from .scheduler import get_shift_template_name, validate_date_range, get_date_range
from .print_manifest import PrintJob, ShiftSelection, build_print_manifest
from .ui import ScheduleAppUI
from .word_processor import (
    WordProcessor,
    TemplateLookupError,
    get_word_automation_status,
)
from .app_paths import get_data_dir

logger = get_logger(__name__)


class FailedOperation(TypedDict):
    """Typed structure for tracking failed print operations.

    Attributes:
        date: The date that was being processed.
        shift: Shift type (``"day"`` or ``"night"``).
        template: Template name that was looked up.
        error: Human-readable error message, or ``None``.
    """

    date: date
    shift: str
    template: str
    error: Optional[str]


@dataclass(frozen=True)
class _BatchRequest:
    """Validated UI snapshot passed unchanged to the worker thread."""

    manifest: tuple[PrintJob, ...]
    printer_name: str
    day_folder: str
    night_folder: str


def _compute_batch_size(start_date: date, end_date: date) -> tuple[int, int]:
    """Compute total days and total jobs for a date range.

    Args:
        start_date: Inclusive start date.
        end_date: Inclusive end date.

    Returns:
        Tuple of (total_days, total_jobs) where total_jobs = total_days * 2
        (one day shift + one night shift per day).
    """
    total_days = (end_date - start_date).days + 1
    total_jobs = total_days * 2
    return total_days, total_jobs


class ShiftPressApp:
    """Main application controller.

    Coordinates configuration management, input validation, preflight
    template checks, and background batch processing of shift schedule
    documents.
    """

    def __init__(self, root: tk.Tk):
        """
        Initialize the application.

        Args:
            root: The Tkinter root window
        """
        self.root = root
        self.ui = ScheduleAppUI(root)
        self.config_manager = ConfigManager()
        self.word_processor: Optional[WordProcessor] = None
        self._preflight_wp: Optional[WordProcessor] = None
        self._processing_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._closing = False
        self._save_lock = threading.Lock()

        # Load and apply saved configuration
        self._load_config()

        # Set up button command and keyboard shortcuts (Enter = start, Escape = cancel)
        self.ui.set_start_command(
            self.start_processing, cancel_command=self._cancel_if_running
        )

        # Handle window close gracefully
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        logger.info("ShiftPress application initialized")

    def _safe_after(self, callback: Callable[[], None]) -> None:
        """Schedule a UI callback if the window is still alive.

        Tkinter isn't thread-safe; all UI updates must be scheduled onto the
        UI thread.  During shutdown the root window can be destroyed while the
        worker thread is still running; ``after()`` raises ``TclError`` in
        that case, which this method swallows.

        Args:
            callback: Zero-argument callable to schedule on the UI thread.
        """

        if self._closing:
            return

        try:
            self.root.after(0, callback)
        except tk.TclError:
            # Window already destroyed; ignore late UI updates.
            logger.debug("UI update skipped (window closed)")

    def _load_config(self) -> None:
        """Load configuration and apply to UI."""
        try:
            config = self.config_manager.load()
            if config.day_folder and self.ui.day_entry:
                self.ui.day_entry.delete(0, tk.END)
                self.ui.day_entry.insert(0, config.day_folder)
            if config.night_folder and self.ui.night_entry:
                self.ui.night_entry.delete(0, tk.END)
                self.ui.night_entry.insert(0, config.night_folder)
            if config.printer_name and self.ui.printer_var:
                self.ui.printer_var.set(config.printer_name)
            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            self.ui.show_warning(
                "Configuration Error", f"Could not load saved configuration: {e}"
            )

    def _save_config(self, config: AppConfig) -> None:
        """
        Save configuration (thread-safe).

        Args:
            config: Configuration to save
        """
        with self._save_lock:
            try:
                self.config_manager.save(config)
                logger.info("Configuration saved successfully")
            except Exception as e:
                logger.error(f"Error saving configuration: {e}")

    @staticmethod
    def _normalize_folder(folder: str) -> str:
        """Normalize user-pasted folder paths consistently."""
        return (folder or "").strip().strip('"').strip("'")

    def _validate_inputs(
        self,
    ) -> tuple[Optional[_BatchRequest], Optional[str]]:
        """Validate UI selections and return one immutable worker request."""
        raw_selections = self.ui.get_shift_selections()
        selections: tuple[ShiftSelection, ...] = tuple(
            replace(
                selection,
                folder=self._normalize_folder(selection.folder),
            )
            for selection in raw_selections
        )
        enabled_selections = tuple(
            selection for selection in selections if selection.enabled
        )
        if not enabled_selections:
            return None, "Select at least one Night or Day schedule"

        for selection in enabled_selections:
            label = selection.shift_type.title()
            try:
                start_date, end_date = selection.active_range()
            except ValueError as e:
                return None, str(e)
            is_valid, error_msg = validate_date_range(start_date, end_date)
            if not is_valid:
                return None, f"Invalid {label} date selection: {error_msg}"

        printer_name = (self.ui.get_printer_name() or "").strip()
        if not printer_name or printer_name == DEFAULT_PRINTER_LABEL:
            return None, "Please select a target printer"

        available_printers: list[str] = []
        try:
            available_printers = self.ui.get_available_printers()
        except Exception as e:
            logger.debug(f"Could not enumerate printers for validation: {e}")

        if available_printers and printer_name not in available_printers:
            return None, (
                "Selected printer is not available. Click Refresh and select a valid printer."
            )

        ok, word_err = get_word_automation_status()
        if not ok:
            return None, word_err

        for selection in enabled_selections:
            label = selection.shift_type.title()
            if not selection.folder:
                return None, f"Please select a {label} Templates folder"

        for selection in enabled_selections:
            label = selection.shift_type.title()
            is_valid, error_msg = validate_folder_path(selection.folder)
            if not is_valid:
                return None, f"Invalid {label} Templates folder: {error_msg}"

        try:
            manifest = build_print_manifest(selections)
        except ValueError as e:
            return None, str(e)

        ok, preflight_err = self._preflight_templates(manifest)
        if not ok:
            return None, preflight_err

        folders = {selection.shift_type: selection.folder for selection in selections}
        return (
            _BatchRequest(
                manifest=manifest,
                printer_name=printer_name,
                day_folder=folders.get("day", ""),
                night_folder=folders.get("night", ""),
            ),
            None,
        )

    def _preflight_templates(
        self,
        manifest: tuple[PrintJob, ...],
    ) -> tuple[bool, Optional[str]]:
        """Validate that all required templates exist and resolve unambiguously.

        On success the WordProcessor instance (with a warm template cache) is
        stored on ``self._preflight_wp`` so that ``_process_batch`` can reuse it
        instead of re-scanning the filesystem.

        Args:
            manifest: Exact concrete jobs selected for this batch.

        Returns:
            Tuple of ``(ok, error_message)``.  On success *error_message*
            is ``None``.
        """

        wp = WordProcessor()
        missing: list[str] = []
        requirements = sorted(
            {(job.shift_type, job.folder, job.template_name) for job in manifest},
            key=lambda item: (item[0], item[2], item[1]),
        )

        for shift_type, folder, template_name in requirements:
            label = shift_type.title()
            try:
                found = wp.find_template_file(folder, template_name)
            except TemplateLookupError as e:
                return (
                    False,
                    f"{label} template lookup error for '{template_name}': {e}",
                )
            if not found:
                missing.append(f"{label}: {template_name}")

        if missing:
            shown = "\n".join(missing[:MAX_PREFLIGHT_MISSING_SHOWN])
            more = ""
            if len(missing) > MAX_PREFLIGHT_MISSING_SHOWN:
                more = f"\n...and {len(missing) - MAX_PREFLIGHT_MISSING_SHOWN} more"
            return (
                False,
                "Missing required templates:\n\n"
                f"{shown}{more}\n\n"
                "Verify your template folders and naming conventions.",
            )

        # Stash the WordProcessor so _process_batch can reuse its template cache.
        self._preflight_wp = wp
        return True, None

    def start_processing(self) -> None:
        """Start batch processing in a background thread, or cancel if already running.

        If a batch is already in progress, sets the cancel flag and disables the
        button instead of starting a new batch.
        """
        # Check if already processing (can be used as stop button)
        if self._processing_thread and self._processing_thread.is_alive():
            self._cancel_event.set()
            current_progress = (
                self.ui.progress_var.get() if self.ui.progress_var else 0.0
            )
            self.ui.update_status(
                "Stopping after current document...", current_progress
            )
            self.ui.set_print_button_state("disabled")
            return

        # Validate inputs
        request, error_msg = self._validate_inputs()
        if request is None:
            self.ui.show_warning("Validation Error", error_msg or "Unknown error")
            return

        total_jobs = len(request.manifest)
        if total_jobs >= LARGE_BATCH_THRESHOLD:
            scope_lines: list[str] = []
            for shift_type in ("night", "day"):
                dates = sorted(
                    {
                        job.date
                        for job in request.manifest
                        if job.shift_type == shift_type
                    }
                )
                if not dates:
                    continue
                if dates[0] == dates[-1]:
                    scope = dates[0].strftime("%m/%d/%Y")
                else:
                    scope = (
                        f"{dates[0].strftime('%m/%d/%Y')} – "
                        f"{dates[-1].strftime('%m/%d/%Y')}"
                    )
                scope_lines.append(f"{shift_type.title()}: {scope}")
            scopes = "\n".join(scope_lines)
            ok = self.ui.ask_yes_no(
                "Large Batch Confirm",
                f"This will print {total_jobs} selected schedules.\n\n"
                f"{scopes}\n\nContinue?",
            )
            if not ok:
                self.ui.update_status("Cancelled by user", 0)
                return

        # Reset cancel flag
        self._cancel_event.clear()

        # Update button text to STOP and disable inputs during processing
        self.ui.set_inputs_enabled(False)
        if self.ui.print_btn:
            self.ui.print_btn.config(text="Cancel", bg=COLORS.error)

        # Start processing thread with pre-collected values.
        # Non-daemon so that __exit__/finally COM cleanup runs even if the
        # main thread exits.  _on_close joins with a timeout to avoid hanging.
        self._processing_thread = threading.Thread(
            target=self._process_batch, args=(request,), daemon=False
        )
        self._processing_thread.start()

    def _cancel_if_running(self) -> None:
        """Cancel the current batch if one is active (Escape key handler)."""
        if self._processing_thread and self._processing_thread.is_alive():
            self._cancel_event.set()
            current_progress = (
                self.ui.progress_var.get() if self.ui.progress_var else 0.0
            )
            self.ui.update_status(
                "Stopping after current document...", current_progress
            )
            self.ui.set_print_button_state("disabled")

    def _cancel_ui_update(self) -> None:
        """Schedule a 'Cancelled' status update on the UI thread."""
        self._safe_after(lambda: self.ui.update_status("Cancelled", 0))

    def _reset_ui(self) -> None:
        """Re-enable all inputs and reset the print button to its default state."""
        if self._closing:
            return
        self.ui.set_inputs_enabled(True)
        if self.ui.print_btn:
            self.ui.print_btn.config(text="Print Schedules", bg=COLORS.accent)
        self.ui.set_print_button_state("normal")

    def _print_shift(
        self,
        word_proc: WordProcessor,
        folder: str,
        template: str,
        current_date: date,
        printer_name: str,
        shift_label: str,
        job_index: int,
        total_jobs: int,
        failed_operations: list[FailedOperation],
    ) -> None:
        """Print a single shift document and record failures.

        Args:
            word_proc: Active WordProcessor instance.
            folder: Template folder path.
            template: Template name for the shift.
            current_date: Date being processed.
            printer_name: Target printer.
            shift_label: Human-readable shift label (e.g. "Day" or "Night").
            job_index: Current 0-based job index (for progress display).
            total_jobs: Total number of jobs in the batch.
            failed_operations: Mutable list to append failure records to.
        """
        day_name = get_english_day_name(current_date)
        display_date = current_date.strftime("%m/%d/%Y")
        progress = ((job_index + 1) / max(total_jobs, 1)) * 100
        msg = (
            f"Printing {shift_label} Shift: {day_name} {display_date} "
            f"({job_index + 1}/{total_jobs})..."
        )

        def _update(m: str = msg, p: float = progress) -> None:
            self.ui.update_status(m, p)

        self._safe_after(_update)

        success, error = word_proc.print_document(
            folder,
            template,
            current_date,
            printer_name,
        )
        if not success:
            failed_operations.append(
                {
                    "date": current_date,
                    "shift": shift_label.lower(),
                    "template": template,
                    "error": error,
                }
            )
            logger.error(
                f"Failed to print {shift_label.lower()} shift for {current_date}: {error}"
            )

    def _process_batch(self, params: dict[str, Any]) -> None:
        """
        Process the batch of schedules.

        Args:
            params: Pre-collected UI values with keys: start_date, end_date,
                    day_folder, night_folder, printer_name
        """
        start_date = params["start_date"]
        end_date = params["end_date"]

        if not start_date or not end_date:
            logger.error("Attempted to process batch with missing dates")
            self._safe_after(self._reset_ui)
            return

        day_folder = params["day_folder"]
        night_folder = params["night_folder"]
        printer_name = params["printer_name"]

        # Save configuration
        config = AppConfig(
            day_folder=day_folder,
            night_folder=night_folder,
            printer_name=printer_name,
        )
        self._save_config(config)

        # Calculate total days (MAX_DAYS_RANGE already validated by _validate_inputs)
        total_days, total_jobs = _compute_batch_size(start_date, end_date)

        logger.info(f"Processing {total_days} days from {start_date} to {end_date}")

        # Track failed operations
        failed_operations: list[FailedOperation] = []

        try:
            # Reuse the WordProcessor from preflight (warm template cache) if available.
            wp = self._preflight_wp or WordProcessor()
            self._preflight_wp = None  # release reference

            self._safe_after(lambda: self.ui.update_status("Initializing Word...", 0))

            with wp as word_proc:
                job_index = 0
                for current_date in get_date_range(start_date, end_date):
                    if self._cancel_event.is_set():
                        logger.info("Batch processing cancelled by user")
                        self._cancel_ui_update()
                        return

                    # Day Shift
                    day_template = get_shift_template_name(current_date, "day")
                    if self._cancel_event.is_set():
                        self._cancel_ui_update()
                        return
                    self._print_shift(
                        word_proc,
                        day_folder,
                        day_template,
                        current_date,
                        printer_name,
                        "Day",
                        job_index,
                        total_jobs,
                        failed_operations,
                    )
                    job_index += 1

                    # Night Shift
                    night_template = get_shift_template_name(current_date, "night")
                    if self._cancel_event.is_set():
                        self._cancel_ui_update()
                        return
                    self._print_shift(
                        word_proc,
                        night_folder,
                        night_template,
                        current_date,
                        printer_name,
                        "Night",
                        job_index,
                        total_jobs,
                        failed_operations,
                    )
                    job_index += 1

                # Complete
                self._safe_after(
                    lambda: self.ui.update_status("Complete!", PROGRESS_MAX)
                )

                # Show results
                if failed_operations:
                    # Write the CSV report on the worker thread to keep the
                    # UI thread free of blocking I/O.
                    report_path = self._write_failure_report(failed_operations)
                    snapshot = list(failed_operations)
                    self._safe_after(
                        lambda: self._show_failure_summary(snapshot, report_path)
                    )
                else:
                    self._safe_after(
                        lambda: self.ui.show_info(
                            "Success",
                            f"All {total_days} days have been processed and sent to the printer.",
                        )
                    )

        except Exception as e:
            logger.exception("Error during batch processing")
            err_msg = f"An error occurred during processing: {type(e).__name__}: {e}"
            self._safe_after(lambda: self.ui.show_error("Processing Error", err_msg))
        finally:
            self._safe_after(self._reset_ui)

    def _on_close(self) -> None:
        """Handle window close: persist config, cancel any running batch, and shut down."""
        self._closing = True

        # Cancel any active batch first so the worker thread stops ASAP.
        if self._processing_thread and self._processing_thread.is_alive():
            logger.info("Window close requested during processing, cancelling...")
            self._cancel_event.set()
            # Wait generously for the current COM call to complete.
            self._processing_thread.join(timeout=10)
            if self._processing_thread.is_alive():
                logger.warning(
                    "Worker thread did not exit within timeout; "
                    "window will close but a print job may still complete."
                )

        # Persist current UI values so template paths, printer, and options
        # survive across sessions even if the user never ran a batch.
        try:
            printer = (self.ui.get_printer_name() or "").strip()
            # Don't persist the placeholder label — it's not a real printer.
            if printer == DEFAULT_PRINTER_LABEL:
                printer = ""
            config = AppConfig(
                day_folder=(self.ui.get_day_folder() or "").strip(),
                night_folder=(self.ui.get_night_folder() or "").strip(),
                printer_name=printer,
            )
            self._save_config(config)
        except Exception as e:
            logger.warning(f"Could not save config on close: {e}")

        self.root.destroy()

    def _show_failure_summary(
        self,
        failed_operations: list[FailedOperation],
        report_path: Optional[str] = None,
    ) -> None:
        """
        Show a summary of failed operations.

        Args:
            failed_operations: List of failed operation details
            report_path: Pre-computed path to the CSV failure report, or
                ``None`` if it was not written (or write failed).
        """
        total = len(failed_operations)
        message = f"{total} operation(s) failed:\n\n"

        # Show first N failures
        for i, op in enumerate(failed_operations[:MAX_FAILURE_SUMMARY_SHOWN], 1):
            date_str = op["date"].strftime("%m/%d/%Y")
            message += f"{i}. {date_str} {op['shift'].title()} Shift ({op['template']}): {op['error']}\n"

        if total > MAX_FAILURE_SUMMARY_SHOWN:
            message += f"\n... and {total - MAX_FAILURE_SUMMARY_SHOWN} more failures"

        data_dir = get_data_dir()
        log_path = data_dir / LOG_FILENAME

        if report_path:
            message += f"\n\nFailure report saved to:\n{report_path}"
        message += f"\n\nLog file:\n{log_path}"
        message += "\n\nTip: Click 'Open Logs' in the app footer."

        self.ui.show_warning("Processing Completed with Errors", message)

    def _write_failure_report(
        self, failed_operations: list[FailedOperation]
    ) -> Optional[str]:
        """Write a CSV failure report to the data directory.

        Args:
            failed_operations: List of failed operation records to write.

        Returns:
            Absolute path to the written CSV file, or ``None`` if writing
            failed.
        """

        try:
            data_dir = get_data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = data_dir / f"failure_report_{ts}.csv"

            with open(report_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "shift", "template", "error"])
                for op in failed_operations:
                    writer.writerow(
                        [
                            op["date"].strftime("%m/%d/%Y"),
                            op["shift"],
                            op["template"],
                            op.get("error") or "",
                        ]
                    )
            logger.info(f"Failure report written: {report_file}")
            return str(report_file)
        except Exception as e:
            logger.warning(f"Could not write failure report: {e}")
            return None


def main() -> None:
    """Main entry point for the application."""
    setup_logging()
    logger.info("Starting ShiftPress")

    try:
        root = tk.Tk()
        app = ShiftPressApp(root)
        app.ui.run()
    except Exception as e:
        logger.exception("Fatal error in main")
        try:
            import tkinter.messagebox as mb

            data_dir = get_data_dir()
            log_path = data_dir / LOG_FILENAME
            mb.showerror(
                "Fatal Error",
                "The application encountered a fatal error:\n\n"
                f"{str(e)}\n\n"
                f"Logs are saved to:\n{log_path}",
            )
        except Exception:
            print(f"Fatal error: {e}")
    finally:
        logger.info("ShiftPress shutting down")


if __name__ == "__main__":
    main()
