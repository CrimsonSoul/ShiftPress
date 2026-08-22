"""
ShiftPrint - Main Application Entry Point

Batch print shift schedules via Word COM automation.
"""

import threading
import csv
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Optional, Callable, TypedDict

import tkinter as tk

from .config import ConfigManager, AppConfig
from .scheduler import get_english_day_name
from .constants import (
    PROGRESS_MAX,
    DEFAULT_PRINTER_LABEL,
    LOG_FILENAME,
    LARGE_BATCH_THRESHOLD,
    MAX_PREFLIGHT_MISSING_SHOWN,
    MAX_FAILURE_SUMMARY_SHOWN,
)

from .logger import setup_logging, get_logger
from .path_validation import validate_folder_path
from .print_manifest import PrintJob, ShiftSelection, build_print_manifest
from .ui import ScheduleAppUI
from .word_processor import (
    WordProcessor,
    TemplateLookupError,
    get_word_automation_status,
)
from .app_paths import get_data_dir

logger = get_logger(__name__)

_DISPLAY_DATE_FORMAT = "%m/%d/%Y"


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


class ShiftPrintApp:
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

        # Wire the print button. Enter starts a run only while the button has
        # focus; Escape cancels from anywhere in the window.
        self.ui.set_start_command(
            self.start_processing, cancel_command=self._cancel_if_running
        )

        # Handle window close gracefully
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        logger.info("ShiftPrint application initialized")

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
            self.ui.set_day_folder(config.day_folder)
            self.ui.set_night_folder(config.night_folder)
            if config.printer_name and self.ui.printer_var:
                self.ui.printer_var.set(config.printer_name)
            self.ui.refresh_setup_summary()
            logger.info("Configuration loaded successfully")
        except Exception as e:
            logger.exception("Error loading configuration")
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
            except Exception:
                logger.exception("Error saving configuration")

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
            selection_error = selection.validate()
            if selection_error:
                return None, selection_error

        printer_name, printer_error = self._validate_printer_selection()
        if printer_error:
            return None, printer_error

        ok, word_err = get_word_automation_status()
        if not ok:
            return None, word_err

        folder_error = self._validate_selection_folders(enabled_selections)
        if folder_error:
            return None, folder_error

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

    def _validate_printer_selection(self) -> tuple[str, Optional[str]]:
        """Return the selected printer and any operator-facing validation error."""
        printer_name = (self.ui.get_printer_name() or "").strip()
        if not printer_name or printer_name == DEFAULT_PRINTER_LABEL:
            return printer_name, "Please select a target printer"

        try:
            available_printers = self.ui.get_available_printers()
        except Exception as e:
            logger.debug(f"Could not enumerate printers for validation: {e}")
            available_printers = []

        if available_printers and printer_name not in available_printers:
            return printer_name, (
                "Selected printer is not available. Click Refresh and select a valid printer."
            )
        return printer_name, None

    @staticmethod
    def _validate_selection_folders(
        selections: tuple[ShiftSelection, ...],
    ) -> Optional[str]:
        """Return the first enabled shift-folder validation error, if any."""
        for selection in selections:
            label = selection.shift_type.title()
            if not selection.folder:
                return f"Please select a {label} Templates folder"

        for selection in selections:
            label = selection.shift_type.title()
            is_valid, error_msg = validate_folder_path(selection.folder)
            if not is_valid:
                return f"Invalid {label} Templates folder: {error_msg}"
        return None

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
        if self._request_cancel():
            return

        # Validate inputs
        request, error_msg = self._validate_inputs()
        if request is None:
            self.ui.show_warning("Validation Error", error_msg or "Unknown error")
            return

        if not self._confirm_large_batch(request.manifest):
            self.ui.update_status("Cancelled by user", 0)
            return

        # Reset cancel flag
        self._cancel_event.clear()

        # Update button text to STOP and disable inputs during processing
        self.ui.set_inputs_enabled(False)
        self.ui.set_processing_mode(True)

        # Start processing thread with pre-collected values.
        # Non-daemon so that __exit__/finally COM cleanup runs even if the
        # main thread exits.  _on_close joins with a timeout to avoid hanging.
        self._processing_thread = threading.Thread(
            target=self._process_batch, args=(request,), daemon=False
        )
        self._processing_thread.start()

    def _request_cancel(self) -> bool:
        """Request cancellation when a batch is active and report whether handled."""
        if not (self._processing_thread and self._processing_thread.is_alive()):
            return False
        self._cancel_event.set()
        current_progress = self.ui.progress_var.get() if self.ui.progress_var else 0.0
        self.ui.update_status("Stopping after current document...", current_progress)
        self.ui.set_print_button_state("disabled")
        return True

    @staticmethod
    def _format_manifest_scopes(manifest: tuple[PrintJob, ...]) -> str:
        """Format Night and Day date scopes in their stable operator order."""
        scope_lines: list[str] = []
        for shift_type in ("night", "day"):
            dates = sorted(
                {job.date for job in manifest if job.shift_type == shift_type}
            )
            if not dates:
                continue
            if dates[0] == dates[-1]:
                scope = dates[0].strftime(_DISPLAY_DATE_FORMAT)
            else:
                scope = (
                    f"{dates[0].strftime(_DISPLAY_DATE_FORMAT)} – "
                    f"{dates[-1].strftime(_DISPLAY_DATE_FORMAT)}"
                )
            scope_lines.append(f"{shift_type.title()}: {scope}")
        return "\n".join(scope_lines)

    def _confirm_large_batch(self, manifest: tuple[PrintJob, ...]) -> bool:
        """Confirm large manifests; accept smaller runs without prompting."""
        total_jobs = len(manifest)
        if total_jobs < LARGE_BATCH_THRESHOLD:
            return True
        scopes = self._format_manifest_scopes(manifest)
        return self.ui.ask_yes_no(
            "Large Batch Confirm",
            f"This will print {total_jobs} selected schedules.\n\n"
            f"{scopes}\n\nContinue?",
        )

    def _cancel_if_running(self) -> None:
        """Cancel the current batch if one is active (Escape key handler)."""
        self._request_cancel()

    def _cancel_ui_update(self) -> None:
        """Schedule a 'Cancelled' status update on the UI thread."""
        self._safe_after(lambda: self.ui.update_status("Cancelled", 0))

    def _reset_ui(self) -> None:
        """Re-enable all inputs and reset the print button to its default state."""
        if self._closing:
            return
        self.ui.set_inputs_enabled(True)
        self.ui.set_processing_mode(False)
        self.ui.set_print_button_state("normal")

    def _print_job(
        self,
        word_proc: WordProcessor,
        job: PrintJob,
        printer_name: str,
        job_index: int,
        total_jobs: int,
        failed_operations: list[FailedOperation],
    ) -> None:
        """Print one concrete manifest job and record failures.

        Args:
            word_proc: Active WordProcessor instance.
            job: Concrete immutable print job.
            printer_name: Target printer.
            job_index: Current 0-based job index (for progress display).
            total_jobs: Total number of jobs in the batch.
            failed_operations: Mutable list to append failure records to.
        """
        shift_label = job.shift_type.title()
        day_name = get_english_day_name(job.date)
        display_date = job.date.strftime(_DISPLAY_DATE_FORMAT)
        progress = ((job_index + 1) / max(total_jobs, 1)) * 100
        msg = (
            f"Printing {shift_label} Shift: {day_name} {display_date} "
            f"({job_index + 1}/{total_jobs})..."
        )

        def _update(m: str = msg, p: float = progress) -> None:
            self.ui.update_status(m, p)

        self._safe_after(_update)

        success, error = word_proc.print_document(
            job.folder,
            job.template_name,
            job.date,
            printer_name,
        )
        if not success:
            failed_operations.append(
                {
                    "date": job.date,
                    "shift": job.shift_type,
                    "template": job.template_name,
                    "error": error,
                }
            )
            logger.error(
                f"Failed to print {job.shift_type} shift for {job.date}: {error}"
            )

    def _process_batch(self, request: _BatchRequest) -> None:
        """Process exactly the concrete jobs in a validated request.

        Args:
            request: Immutable validated manifest and persisted setup values.
        """
        total_jobs = len(request.manifest)
        if total_jobs == 0:
            logger.error("Attempted to process an empty print manifest")
            self._safe_after(self._reset_ui)
            return

        config = AppConfig(
            day_folder=request.day_folder,
            night_folder=request.night_folder,
            printer_name=request.printer_name,
        )
        self._save_config(config)

        logger.info(f"Processing {total_jobs} selected schedules")
        failed_operations: list[FailedOperation] = []

        try:
            wp = self._preflight_wp or WordProcessor()
            self._preflight_wp = None

            self._safe_after(lambda: self.ui.update_status("Initializing Word...", 0))

            with wp as word_proc:
                for job_index, job in enumerate(request.manifest):
                    if self._cancel_event.is_set():
                        logger.info("Batch processing cancelled by user")
                        self._cancel_ui_update()
                        return

                    self._print_job(
                        word_proc,
                        job,
                        request.printer_name,
                        job_index,
                        total_jobs,
                        failed_operations,
                    )

                self._safe_after(
                    lambda: self.ui.update_status("Complete!", PROGRESS_MAX)
                )

                if failed_operations:
                    report_path = self._write_failure_report(failed_operations)
                    snapshot = list(failed_operations)
                    self._safe_after(
                        lambda: self._show_failure_summary(snapshot, report_path)
                    )
                else:
                    self._safe_after(
                        lambda: self.ui.show_info(
                            "Success",
                            f"All {total_jobs} selected schedules have been "
                            "processed and sent to the printer.",
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
            date_str = op["date"].strftime(_DISPLAY_DATE_FORMAT)
            message += f"{i}. {date_str} {op['shift'].title()} Shift ({op['template']}): {op['error']}\n"

        if total > MAX_FAILURE_SUMMARY_SHOWN:
            message += f"\n... and {total - MAX_FAILURE_SUMMARY_SHOWN} more failures"

        data_dir = get_data_dir()
        log_path = data_dir / LOG_FILENAME

        if report_path:
            message += f"\n\nFailure report saved to:\n{report_path}"
        message += f"\n\nLog file:\n{log_path}"
        message += "\n\nTip: Click 'Open logs' in the app footer."

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
                            op["date"].strftime(_DISPLAY_DATE_FORMAT),
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
    logger.info("Starting ShiftPrint")

    try:
        root = tk.Tk()
        app = ShiftPrintApp(root)
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
        logger.info("ShiftPrint shutting down")


if __name__ == "__main__":
    main()
