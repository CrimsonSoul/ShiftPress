"""
Integration tests for main application module.
"""

import csv
import sys
from dataclasses import replace
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

# Import the class directly, then grab the actual module from sys.modules
# (src.main as a name is shadowed by the main() function exported in src.__init__.py)
from src.main import ShiftPressApp, _BatchRequest
from src.print_manifest import PrintJob, ShiftSelection

main_module = sys.modules["src.main"]


def _request(*jobs: PrintJob) -> _BatchRequest:
    """Build a validated worker request with fixed configuration values."""
    return _BatchRequest(
        manifest=tuple(jobs),
        printer_name="Test Printer",
        day_folder="/tmp/day",
        night_folder="/tmp/night",
    )


def _run_scheduled_callbacks(app: ShiftPressApp) -> None:
    """Execute callbacks captured by the mocked Tk root."""
    for call in app.root.after.call_args_list:
        callback = call.args[1]
        callback()


class TestShiftPressApp:
    """Tests for ShiftPressApp class."""

    @pytest.fixture
    def app(self):
        """Create a ShiftPressApp with mocked UI and dependencies."""
        with patch.object(main_module, "ScheduleAppUI") as MockUI, patch.object(
            main_module, "ConfigManager"
        ) as MockConfig:
            mock_root = MagicMock()
            mock_ui = MockUI.return_value
            mock_ui.get_day_folder.return_value = "/tmp/day"
            mock_ui.get_night_folder.return_value = "/tmp/night"
            mock_ui.get_printer_name.return_value = "Test Printer"
            mock_ui.get_available_printers.return_value = ["Test Printer"]
            mock_ui.get_shift_selections.return_value = (
                ShiftSelection(
                    shift_type="night",
                    enabled=True,
                    mode="single",
                    start_date=date(2026, 1, 14),
                    end_date=date(2026, 1, 14),
                    folder="/tmp/night",
                ),
                ShiftSelection(
                    shift_type="day",
                    enabled=True,
                    mode="single",
                    start_date=date(2026, 1, 15),
                    end_date=date(2026, 1, 15),
                    folder="/tmp/day",
                ),
            )
            mock_ui.progress_var = MagicMock()
            mock_ui.progress_var.get.return_value = 0.0
            mock_ui.print_btn = MagicMock()

            mock_config = MockConfig.return_value
            mock_config.load.return_value = MagicMock(
                day_folder="", night_folder="", printer_name=""
            )

            app = ShiftPressApp(mock_root)
            yield app

    def test_validate_inputs_missing_day_folder(self, app):
        """An included Day shift should require its own folder."""
        night, day = app.ui.get_shift_selections.return_value
        app.ui.get_shift_selections.return_value = (
            night,
            replace(day, folder=""),
        )

        request, error = app._validate_inputs()

        assert request is None
        assert "Day Templates" in error

    def test_validate_inputs_missing_night_folder(self, app):
        """An included Night shift should require its own folder."""
        night, day = app.ui.get_shift_selections.return_value
        app.ui.get_shift_selections.return_value = (
            replace(night, folder=""),
            day,
        )

        request, error = app._validate_inputs()

        assert request is None
        assert "Night Templates" in error

    def test_validate_inputs_ignores_disabled_shift_folder(self, app):
        """A disabled shift must not validate or block on its folder."""
        night, day = app.ui.get_shift_selections.return_value
        app.ui.get_shift_selections.return_value = (
            night,
            replace(day, enabled=False, folder=""),
        )

        with patch.object(
            main_module, "validate_folder_path", return_value=(True, None)
        ) as mock_validate, patch.object(main_module, "WordProcessor") as MockWP:
            MockWP.return_value.find_template_file.return_value = "/tmp/template.docx"
            request, error = app._validate_inputs()

        assert request is not None
        assert error is None
        mock_validate.assert_called_once_with("/tmp/night")
        assert [job.shift_type for job in request.manifest] == ["night"]

    def test_validate_inputs_requires_at_least_one_shift(self, app):
        """Printing without Night or Day intent must stop before environment checks."""
        night, day = app.ui.get_shift_selections.return_value
        app.ui.get_shift_selections.return_value = (
            replace(night, enabled=False),
            replace(day, enabled=False),
        )

        request, error = app._validate_inputs()

        assert request is None
        assert error == "Select at least one Night or Day schedule"

    def test_validate_inputs_missing_printer(self, app):
        """Should fail validation when no printer selected."""
        app.ui.get_printer_name.return_value = "Choose Printer"
        request, error = app._validate_inputs()
        assert request is None
        assert "printer" in error.lower()

    def test_validate_inputs_printer_not_available(self, app):
        """Should fail validation when printer is not in enumerated list."""
        app.ui.get_printer_name.return_value = "Some Printer"
        app.ui.get_available_printers.return_value = ["Other Printer"]
        with patch.object(
            main_module, "validate_folder_path", return_value=(True, None)
        ):
            request, error = app._validate_inputs()
        assert request is None
        assert "not available" in (error or "").lower()

    def test_validate_inputs_missing_dates(self, app):
        """Each included shift should require its active date."""
        night, day = app.ui.get_shift_selections.return_value
        app.ui.get_shift_selections.return_value = (
            replace(night, start_date=None),
            day,
        )

        request, error = app._validate_inputs()

        assert request is None
        assert error == "Select a Night date"

    def test_validate_inputs_labels_invalid_independent_range(self, app):
        """A reversed range should identify the affected shift."""
        night, day = app.ui.get_shift_selections.return_value
        app.ui.get_shift_selections.return_value = (
            night,
            replace(
                day,
                mode="range",
                start_date=date(2026, 1, 18),
                end_date=date(2026, 1, 16),
            ),
        )

        request, error = app._validate_inputs()

        assert request is None
        assert (
            error == "Invalid Day date selection: End date cannot be before start date"
        )

    def test_validate_inputs_success(self, app):
        """Successful validation should return the exact independent manifest."""

        with patch.object(
            main_module, "validate_folder_path", return_value=(True, None)
        ), patch.object(main_module, "WordProcessor") as MockWP:
            mock_wp = MockWP.return_value
            mock_wp.find_template_file.return_value = "/tmp/template.docx"
            request, error = app._validate_inputs()

        assert request is not None
        assert error is None
        assert [(job.date, job.shift_type) for job in request.manifest] == [
            (date(2026, 1, 14), "night"),
            (date(2026, 1, 15), "day"),
        ]

    @patch.object(main_module, "WordProcessor")
    def test_process_batch_uses_exact_manifest_order(self, mock_wp_class, app):
        """The worker should print Night today followed by Day tomorrow."""
        mock_wp = MagicMock()
        mock_wp.print_document.return_value = (True, None)
        mock_wp.__enter__ = MagicMock(return_value=mock_wp)
        mock_wp.__exit__ = MagicMock(return_value=False)
        mock_wp_class.return_value = mock_wp
        request = _request(
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/tmp/night",
            ),
            PrintJob(
                date=date(2026, 1, 15),
                shift_type="day",
                template_name="THIRD Thursday",
                folder="/tmp/day",
            ),
        )

        app._process_batch(request)
        _run_scheduled_callbacks(app)

        assert [call.args for call in mock_wp.print_document.call_args_list] == [
            (
                "/tmp/night",
                "Wednesday Night",
                date(2026, 1, 14),
                "Test Printer",
            ),
            (
                "/tmp/day",
                "THIRD Thursday",
                date(2026, 1, 15),
                "Test Printer",
            ),
        ]
        app.ui.show_info.assert_called_once_with(
            "Success",
            "All 2 selected schedules have been processed and sent to the printer.",
        )
        status_messages = [call.args[0] for call in app.ui.update_status.call_args_list]
        assert any("(1/2)" in message for message in status_messages)
        assert any("(2/2)" in message for message in status_messages)

    @patch.object(main_module, "WordProcessor")
    def test_process_batch_cancel_before_first_job(self, mock_wp_class, app):
        """Should stop processing when cancel event is set."""
        mock_wp = MagicMock()
        mock_wp.print_document.return_value = (True, None)
        mock_wp.__enter__ = MagicMock(return_value=mock_wp)
        mock_wp.__exit__ = MagicMock(return_value=False)
        mock_wp_class.return_value = mock_wp

        # Set cancel before processing starts
        app._cancel_event.set()
        request = _request(
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/tmp/night",
            )
        )

        app._process_batch(request)

        # Should not have printed anything (cancelled immediately)
        assert mock_wp.print_document.call_count == 0

    @patch.object(main_module, "WordProcessor")
    def test_process_batch_cancel_between_selected_jobs(self, mock_wp_class, app):
        """Cancellation after one document must prevent the next manifest job."""
        mock_wp = MagicMock()
        mock_wp.__enter__ = MagicMock(return_value=mock_wp)
        mock_wp.__exit__ = MagicMock(return_value=False)

        def print_once(*_args):
            app._cancel_event.set()
            return True, None

        mock_wp.print_document.side_effect = print_once
        mock_wp_class.return_value = mock_wp
        request = _request(
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/tmp/night",
            ),
            PrintJob(
                date=date(2026, 1, 15),
                shift_type="day",
                template_name="THIRD Thursday",
                folder="/tmp/day",
            ),
        )

        app._process_batch(request)

        assert mock_wp.print_document.call_count == 1

    def test_on_close_without_active_thread(self, app):
        """Should destroy window immediately if no thread is running."""
        app._processing_thread = None
        app._on_close()
        app.root.destroy.assert_called_once()

    def test_on_close_with_active_thread(self, app):
        """Should cancel and join thread before destroying window."""
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        app._processing_thread = mock_thread

        app._on_close()

        assert app._cancel_event.is_set()
        mock_thread.join.assert_called_once_with(timeout=10)
        app.root.destroy.assert_called_once()

    def test_cancel_if_running_sets_event(self, app):
        """_cancel_if_running should set cancel event when thread is alive."""
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        app._processing_thread = mock_thread

        app._cancel_if_running()

        assert app._cancel_event.is_set()
        app.ui.set_print_button_state.assert_called_with("disabled")

    def test_cancel_if_running_noop_when_idle(self, app):
        """_cancel_if_running should do nothing when no thread is running."""
        app._processing_thread = None
        app._cancel_if_running()
        assert not app._cancel_event.is_set()

    def test_safe_after_skips_when_closing(self, app):
        """_safe_after should not schedule if _closing is True."""
        app._closing = True
        callback = MagicMock()
        app._safe_after(callback)
        app.root.after.assert_not_called()

    def test_safe_after_schedules_callback(self, app):
        """_safe_after should call root.after(0, callback)."""
        callback = MagicMock()
        app._safe_after(callback)
        app.root.after.assert_called_with(0, callback)

    @patch.object(main_module, "WordProcessor")
    @patch.object(main_module, "validate_folder_path", return_value=(True, None))
    def test_start_processing_stop_button(self, mock_validate, mock_wp_class, app):
        """start_processing should cancel when a thread is already running."""
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        app._processing_thread = mock_thread

        app.start_processing()

        assert app._cancel_event.is_set()
        app.ui.set_print_button_state.assert_called_with("disabled")

    @patch.object(main_module, "WordProcessor")
    def test_process_batch_tracks_failures_with_summary(self, mock_wp_class, app):
        """Should call _show_failure_summary with the correct failures."""
        mock_wp = MagicMock()
        # Night fails, then Day succeeds.
        mock_wp.print_document.side_effect = [
            (False, "Template not found"),
            (True, None),
        ]
        mock_wp.__enter__ = MagicMock(return_value=mock_wp)
        mock_wp.__exit__ = MagicMock(return_value=False)
        mock_wp_class.return_value = mock_wp
        request = _request(
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/tmp/night",
            ),
            PrintJob(
                date=date(2026, 1, 15),
                shift_type="day",
                template_name="THIRD Thursday",
                folder="/tmp/day",
            ),
        )

        with patch.object(app, "_show_failure_summary") as mock_summary:
            app._process_batch(request)
            _run_scheduled_callbacks(app)

            mock_summary.assert_called_once()
            failures = mock_summary.call_args[0][0]
            assert len(failures) == 1
            assert failures[0]["shift"] == "night"
            assert "Template not found" in failures[0]["error"]
            assert mock_wp.print_document.call_count == 2

    def test_write_failure_report_creates_csv(self, app, tmp_path):
        """_write_failure_report should create a CSV with correct headers."""
        with patch("src.main.get_data_dir", return_value=tmp_path):
            failures = [
                {
                    "date": date(2026, 1, 14),
                    "shift": "day",
                    "template": "Wednesday",
                    "error": "Not found",
                },
                {
                    "date": date(2026, 1, 14),
                    "shift": "night",
                    "template": "Wednesday Night",
                    "error": "Printer offline",
                },
            ]
            result = app._write_failure_report(failures)

        assert result is not None
        # Read back and verify
        with open(result, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
            assert headers == ["date", "shift", "template", "error"]
            rows = list(reader)
            assert len(rows) == 2
            assert rows[0][1] == "day"
            assert rows[1][3] == "Printer offline"

    def test_safe_after_tcl_error_is_swallowed(self, app):
        """_safe_after should swallow TclError when window is already destroyed."""
        import tkinter as tk_mod

        app.root.after.side_effect = tk_mod.TclError("application has been destroyed")
        callback = MagicMock()
        # Should not raise
        app._safe_after(callback)
        app.root.after.assert_called_once_with(0, callback)

    def test_preflight_templates_all_present(self, app, tmp_path):
        """_preflight_templates should succeed when all templates exist."""
        day_dir = tmp_path / "day"
        night_dir = tmp_path / "night"
        day_dir.mkdir()
        night_dir.mkdir()

        # Create templates for a single day (Wednesday 2026-01-14)
        (day_dir / "Wednesday.docx").write_text("dummy")
        (night_dir / "Wednesday Night.docx").write_text("dummy")

        manifest = (
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder=str(night_dir),
            ),
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="day",
                template_name="Wednesday",
                folder=str(day_dir),
            ),
        )
        ok, err = app._preflight_templates(manifest)
        assert ok is True
        assert err is None
        # Should stash the WordProcessor for reuse
        assert app._preflight_wp is not None

    def test_preflight_templates_missing_template(self, app, tmp_path):
        """_preflight_templates should fail when a template is missing."""
        day_dir = tmp_path / "day"
        night_dir = tmp_path / "night"
        day_dir.mkdir()
        night_dir.mkdir()

        # Only create night template, day is missing
        (night_dir / "Wednesday.docx").write_text("dummy")

        manifest = (
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder=str(night_dir),
            ),
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="day",
                template_name="Wednesday",
                folder=str(day_dir),
            ),
        )
        ok, err = app._preflight_templates(manifest)
        assert ok is False
        assert "Missing required templates" in err

    def test_preflight_templates_ambiguous_lookup(self, app, tmp_path):
        """_preflight_templates should fail on TemplateLookupError."""
        day_dir = tmp_path / "day"
        night_dir = tmp_path / "night"
        day_dir.mkdir()
        night_dir.mkdir()

        (night_dir / "Wednesday.docx").write_text("dummy")

        with patch.object(main_module, "WordProcessor") as MockWP:
            mock_wp = MockWP.return_value
            mock_wp.find_template_file.side_effect = main_module.TemplateLookupError(
                "Ambiguous match"
            )
            manifest = (
                PrintJob(
                    date=date(2026, 1, 14),
                    shift_type="night",
                    template_name="Wednesday Night",
                    folder=str(night_dir),
                ),
            )
            ok, err = app._preflight_templates(manifest)

        assert ok is False
        assert "lookup error" in err.lower()

    def test_preflight_checks_only_selected_templates(self, app):
        """Preflight must not inspect templates absent from the manifest."""
        manifest = (
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/night",
            ),
        )

        with patch.object(main_module, "WordProcessor") as MockWP:
            mock_wp = MockWP.return_value
            mock_wp.find_template_file.return_value = "/night/Wednesday Night.docx"
            ok, err = app._preflight_templates(manifest)

        assert ok is True
        assert err is None
        mock_wp.find_template_file.assert_called_once_with("/night", "Wednesday Night")

    def test_load_config_populates_entries(self, app):
        """_load_config should populate UI entries from saved config."""
        mock_config = MagicMock(
            day_folder="/saved/day",
            night_folder="/saved/night",
            printer_name="Saved Printer",
        )
        app.config_manager.load.return_value = mock_config

        # Reset entries to mock clean state
        app.ui.day_entry = MagicMock()
        app.ui.night_entry = MagicMock()
        app.ui.printer_var = MagicMock()
        app.ui.refresh_setup_summary.reset_mock()

        app._load_config()

        app.ui.day_entry.insert.assert_called_with(0, "/saved/day")
        app.ui.night_entry.insert.assert_called_with(0, "/saved/night")
        app.ui.printer_var.set.assert_called_with("Saved Printer")
        app.ui.refresh_setup_summary.assert_called_once()

    def test_load_config_exception_shows_warning(self, app):
        """_load_config should show warning on load failure."""
        app.config_manager.load.side_effect = IOError("Corrupted")
        app._load_config()
        app.ui.show_warning.assert_called_once()
        assert "Corrupted" in app.ui.show_warning.call_args[0][1]

    def test_show_failure_summary_message_format(self, app, tmp_path):
        """_show_failure_summary should format failures and truncate at MAX_FAILURE_SUMMARY_SHOWN."""
        failures = [
            {
                "date": date(2026, 1, d),
                "shift": "day",
                "template": f"Template{d}",
                "error": f"Error {d}",
            }
            for d in range(14, 22)  # 8 failures
        ]

        with patch("src.main.get_data_dir", return_value=tmp_path):
            app._show_failure_summary(failures, report_path="/fake/report.csv")

        app.ui.show_warning.assert_called_once()
        msg = app.ui.show_warning.call_args[0][1]
        assert "8 operation(s) failed" in msg
        # Should show first 5 then "... and 3 more"
        assert "... and 3 more" in msg
        assert "Error 14" in msg  # first failure visible
        assert "Failure report saved to" in msg

    @patch.object(main_module, "WordProcessor")
    def test_process_batch_exception_resets_ui(self, mock_wp_class, app):
        """_process_batch should reset UI to normal state even when an exception occurs."""
        mock_wp = MagicMock()
        mock_wp.__enter__ = MagicMock(return_value=mock_wp)
        mock_wp.__exit__ = MagicMock(return_value=False)
        # Blow up during print
        mock_wp.print_document.side_effect = RuntimeError("COM catastrophe")
        mock_wp_class.return_value = mock_wp
        request = _request(
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/tmp/night",
            )
        )

        app._process_batch(request)

        # The finally block schedules reset_ui via _safe_after.
        # Execute all scheduled callbacks.
        for call in app.root.after.call_args_list:
            cb = call[0][1] if len(call[0]) > 1 else None
            if cb is not None:
                try:
                    cb()
                except Exception:
                    pass

        # show_error should have been called for the exception
        app.ui.show_error.assert_called()
        # Inputs should be re-enabled
        app.ui.set_inputs_enabled.assert_called_with(True)
        # Print button should be re-enabled
        app.ui.set_print_button_state.assert_called_with("normal")
        app.ui.set_processing_mode.assert_called_with(False)

    @patch.object(main_module, "WordProcessor")
    def test_process_batch_saves_configuration_and_consumes_preflight_cache(
        self, mock_wp_class, app
    ):
        """The worker should persist setup values and consume the warm preflight object."""
        warm_wp = MagicMock()
        warm_wp.__enter__ = MagicMock(return_value=warm_wp)
        warm_wp.__exit__ = MagicMock(return_value=False)
        warm_wp.print_document.return_value = (True, None)
        app._preflight_wp = warm_wp
        request = _request(
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/tmp/night",
            )
        )

        app._process_batch(request)

        saved = app.config_manager.save.call_args.args[0]
        assert (
            saved.day_folder,
            saved.night_folder,
            saved.printer_name,
        ) == ("/tmp/day", "/tmp/night", "Test Printer")
        assert app._preflight_wp is None
        mock_wp_class.assert_not_called()

    def test_write_failure_report_exception_returns_none(self, app, tmp_path):
        """_write_failure_report should return None when writing fails."""
        failures = [
            {
                "date": date(2026, 1, 14),
                "shift": "day",
                "template": "Wednesday",
                "error": "Broke",
            }
        ]

        with patch("src.main.get_data_dir", side_effect=OSError("Permission denied")):
            result = app._write_failure_report(failures)

        assert result is None

    def test_validate_inputs_normalizes_folder_quotes_once(self, app):
        """Validated request and jobs should share the same normalized paths."""
        night, day = app.ui.get_shift_selections.return_value
        app.ui.get_shift_selections.return_value = (
            replace(night, folder="'C:\\Users\\night'"),
            replace(day, folder='"C:\\Users\\day"'),
        )
        with patch.object(
            main_module, "validate_folder_path", return_value=(True, None)
        ), patch.object(main_module, "WordProcessor") as MockWP:
            mock_wp = MockWP.return_value
            mock_wp.find_template_file.return_value = "/tmp/template.docx"
            request, error = app._validate_inputs()

        assert request is not None
        assert error is None
        assert request.day_folder == "C:\\Users\\day"
        assert request.night_folder == "C:\\Users\\night"
        assert {job.folder for job in request.manifest} == {
            "C:\\Users\\day",
            "C:\\Users\\night",
        }

    def test_large_batch_confirmation_uses_manifest_document_count(self, app):
        """Large-batch confirmation should describe concrete selected jobs."""
        request = MagicMock()
        request.manifest = tuple(
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/night",
            )
            for _index in range(30)
        )
        app.ui.ask_yes_no.return_value = False

        with patch.object(
            app, "_validate_inputs", return_value=(request, None)
        ), patch.object(main_module.threading, "Thread") as MockThread:
            app.start_processing()

        title, message = app.ui.ask_yes_no.call_args.args
        assert title == "Large Batch Confirm"
        assert "30 selected schedules" in message
        MockThread.assert_not_called()

    def test_show_failure_summary_with_none_report_path(self, app, tmp_path):
        """_show_failure_summary should handle report_path=None gracefully."""
        failures = [
            {
                "date": date(2026, 1, 14),
                "shift": "day",
                "template": "Wednesday",
                "error": "Template not found",
            }
        ]

        with patch("src.main.get_data_dir", return_value=tmp_path):
            app._show_failure_summary(failures, report_path=None)

        app.ui.show_warning.assert_called_once()
        msg = app.ui.show_warning.call_args[0][1]
        assert "1 operation(s) failed" in msg
        # Should NOT contain "Failure report saved to" when report_path is None
        assert "Failure report saved to" not in msg
        # Should still show the log file path
        assert "Log file" in msg
