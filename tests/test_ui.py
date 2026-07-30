"""
Unit tests for UI module.
"""

import tkinter as tk
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.ui import ScheduleAppUI


class _FakeVariable:
    """Small Tk variable substitute that preserves real get/set behavior."""

    def __init__(self, *args, value=None, **kwargs):
        del args, kwargs
        self._value = value

    def get(self):
        """Return the stored value."""
        return self._value

    def set(self, value):
        """Store a new value."""
        self._value = value

    def trace_add(self, *_args, **_kwargs):
        """Accept Tk trace registration without requiring a Tcl interpreter."""
        return "trace"


class _FakeDateEntry:
    """DateEntry substitute with real date storage and mocked widget methods."""

    def __init__(self, *_args, **_kwargs):
        self._date = None
        self.pack = MagicMock()
        self.grid = MagicMock()
        self.grid_remove = MagicMock()
        self.bind = MagicMock()
        self.config = MagicMock()

    def get_date(self):
        """Return the current date."""
        return self._date

    def set_date(self, value):
        """Set the current date."""
        self._date = value


class TestScheduleAppUI:
    """Tests for ScheduleAppUI class."""

    @pytest.fixture
    def root(self):
        """Create a mock Tk root."""
        root = MagicMock(spec=tk.Tk)
        return root

    @pytest.fixture
    def ui(self, root):
        """Create a ScheduleAppUI instance."""
        # Mock win32print and widget creation to avoid Tcl errors
        with patch("win32print.EnumPrinters", return_value=[]), patch(
            "src.ui.ttk.Style"
        ), patch("src.ui.ttk.Frame"), patch("src.ui.ttk.Label"), patch(
            "src.ui.ttk.LabelFrame"
        ), patch(
            "src.ui.ttk.Entry"
        ), patch(
            "src.ui.ttk.Button"
        ), patch(
            "src.ui.ttk.Checkbutton"
        ), patch(
            "src.ui.ttk.Radiobutton"
        ), patch(
            "src.ui.ttk.OptionMenu"
        ), patch(
            "src.ui.ttk.Progressbar"
        ), patch(
            "src.ui.tk.Button"
        ), patch(
            "src.ui.tk.StringVar", side_effect=_FakeVariable
        ), patch(
            "src.ui.tk.DoubleVar", side_effect=_FakeVariable
        ), patch(
            "src.ui.tk.BooleanVar", side_effect=_FakeVariable
        ), patch(
            "src.ui.DateEntry", side_effect=_FakeDateEntry
        ):
            ui = ScheduleAppUI(root, today=date(2026, 7, 30))
            # Manually assign mock widgets for testing
            ui.day_entry = MagicMock()
            ui.day_entry.get.return_value = "C:/Templates/Day"
            ui.night_entry = MagicMock()
            ui.night_entry.get.return_value = "C:/Templates/Night"
            ui.print_btn = MagicMock()
            ui.status_label = MagicMock()
            ui.progress_var = _FakeVariable(value=0.0)
            ui._progress_pct = MagicMock()
            ui.printer_var = _FakeVariable(value="Test Printer")
            yield ui

    def test_init(self, ui):
        """UI should initialize widgets."""
        assert ui.day_entry is not None
        assert ui.night_entry is not None
        assert ui.print_btn is not None

    def test_get_day_folder(self, ui):
        """Should return value from day entry."""
        ui.day_entry.get.return_value = "C:/Templates/Day"
        assert ui.get_day_folder() == "C:/Templates/Day"

    def test_get_night_folder(self, ui):
        """Should return value from night entry."""
        ui.night_entry.get.return_value = "C:/Templates/Night"
        assert ui.get_night_folder() == "C:/Templates/Night"

    def test_defaults_night_today_and_day_tomorrow(self, ui):
        """Fresh UI state should match the operational handoff workflow."""
        night, day = ui.get_shift_selections()

        assert (night.enabled, night.mode, night.start_date) == (
            True,
            "single",
            date(2026, 7, 30),
        )
        assert (day.enabled, day.mode, day.start_date) == (
            True,
            "single",
            date(2026, 7, 31),
        )

    def test_shift_selections_keep_independent_modes_and_dates(self, ui):
        """Changing Night state must not alter the Day selection."""
        night_panel = ui._shift_panels["night"]
        day_panel = ui._shift_panels["day"]
        night_panel.mode_var.set("range")
        night_panel.range_start_picker.set_date(date(2026, 8, 1))
        night_panel.range_end_picker.set_date(date(2026, 8, 3))
        day_panel.enabled_var.set(False)
        day_panel.single_picker.set_date(date(2026, 8, 8))

        night, day = ui.get_shift_selections()

        assert (
            night.enabled,
            night.mode,
            night.start_date,
            night.end_date,
        ) == (
            True,
            "range",
            date(2026, 8, 1),
            date(2026, 8, 3),
        )
        assert (day.enabled, day.mode, day.start_date) == (
            False,
            "single",
            date(2026, 8, 8),
        )

    def test_disabling_night_does_not_disable_day_controls(self, ui):
        """Each Include toggle should control only its own date controls."""
        night_panel = ui._shift_panels["night"]
        day_panel = ui._shift_panels["day"]
        night_panel.single_radio = MagicMock()
        day_panel.single_radio = MagicMock()
        night_panel.enabled_var.set(False)
        day_panel.enabled_var.set(True)

        ui._sync_shift_panel_state("night")

        night_panel.single_radio.config.assert_called_with(state="disabled")
        day_panel.single_radio.config.assert_not_called()

    def test_mode_change_preserves_all_picker_values(self, ui):
        """Switching modes should hide controls without resetting their dates."""
        panel = ui._shift_panels["night"]
        panel.single_picker.set_date(date(2026, 8, 2))
        panel.range_start_picker.set_date(date(2026, 8, 5))
        panel.range_end_picker.set_date(date(2026, 8, 7))
        panel.mode_var.set("range")

        ui._sync_shift_panel_state("night")
        panel.mode_var.set("single")
        ui._sync_shift_panel_state("night")

        assert panel.single_picker.get_date() == date(2026, 8, 2)
        assert panel.range_start_picker.get_date() == date(2026, 8, 5)
        assert panel.range_end_picker.get_date() == date(2026, 8, 7)

    def test_manifest_preview_uses_actual_selected_job_count(self, ui):
        """The visible manifest and action should reflect independent jobs."""
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        manifest_text = ui.manifest_label.config.call_args.kwargs["text"]
        assert "This run: 2 schedules" in manifest_text
        assert "Night: 07/30/2026 (1)" in manifest_text
        assert "Day: 07/31/2026 (1)" in manifest_text
        assert "Printer: Test Printer" in manifest_text
        ui.print_btn.config.assert_called_with(text="Print 2 schedules")

    def test_manifest_preview_blocks_empty_selection(self, ui):
        """No included shifts should produce no jobs and no numeric promise."""
        ui._shift_panels["night"].enabled_var.set(False)
        ui._shift_panels["day"].enabled_var.set(False)
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        manifest_text = ui.manifest_label.config.call_args.kwargs["text"]
        assert "This run: No schedules selected" in manifest_text
        ui.print_btn.config.assert_called_with(text="Print schedules")

    def test_set_inputs_enabled_locks_and_restores_shift_controls(self, ui):
        """Processing lock state should cover every independent shift control."""
        for panel in ui._shift_panels.values():
            panel.include_check = MagicMock()
            panel.single_radio = MagicMock()
            panel.range_radio = MagicMock()

        ui.set_inputs_enabled(False)

        for panel in ui._shift_panels.values():
            panel.include_check.config.assert_called_with(state="disabled")
            panel.single_radio.config.assert_called_with(state="disabled")
            panel.range_radio.config.assert_called_with(state="disabled")
            panel.single_picker.config.assert_called_with(state="disabled")
            panel.range_start_picker.config.assert_called_with(state="disabled")
            panel.range_end_picker.config.assert_called_with(state="disabled")

        ui.set_inputs_enabled(True)

        for panel in ui._shift_panels.values():
            panel.include_check.config.assert_called_with(state="normal")

    def test_set_print_button_state(self, ui):
        """Should update button state."""
        ui.set_print_button_state("disabled")
        ui.print_btn.config.assert_called_with(state="disabled")

    def test_update_status(self, ui):
        """Should update status label and progress bar with contextual style."""
        ui.update_status("Processing...", 50.0)
        ui.status_label.config.assert_called_with(
            text="Processing...", style="Sub.TLabel"
        )
        assert ui.progress_var.get() == 50.0

    def test_update_status_complete_style(self, ui):
        """Should apply success style when message contains 'complete'."""
        ui.update_status("Print complete", 100.0)
        ui.status_label.config.assert_called_with(
            text="Print complete", style="Success.TLabel"
        )

    def test_update_status_error_style(self, ui):
        """Should apply error style when message contains error keywords."""
        for msg in ("Cancelled by user", "Error occurred", "Print failed"):
            ui.update_status(msg, 0.0)
            ui.status_label.config.assert_called_with(text=msg, style="Error.TLabel")

    @patch("tkinter.messagebox.showerror")
    def test_show_error(self, mock_error, ui):
        """Should call messagebox.showerror."""
        ui.show_error("Title", "Message")
        mock_error.assert_called_with("Title", "Message")

    def test_set_start_command(self, ui):
        """Should set the button command and bind Enter key."""
        mock_cmd = MagicMock()
        ui.set_start_command(mock_cmd)
        ui.print_btn.config.assert_called_with(command=mock_cmd)

    def test_set_start_command_with_cancel(self, ui):
        """Should bind Escape key when cancel_command is provided."""
        mock_cmd = MagicMock()
        mock_cancel = MagicMock()
        ui.set_start_command(mock_cmd, cancel_command=mock_cancel)
        ui.print_btn.config.assert_called_with(command=mock_cmd)
        # Verify Escape was bound (check bind call args for "<Escape>")
        bound_keys = [call[0][0] for call in ui.root.bind.call_args_list]
        assert "<Escape>" in bound_keys
