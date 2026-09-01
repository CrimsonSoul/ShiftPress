"""
Unit tests for UI module.
"""

import tkinter as tk
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

import src.ui as ui_module
from src.constants import COLORS, FONTS
from src.ui import ScheduleAppUI, _PATH_PLACEHOLDER


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
        self.constructor_kwargs = _kwargs
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
        ), patch("src.ui.ttk.Frame") as MockFrame, patch(
            "src.ui.ttk.Label"
        ) as MockLabel, patch(
            "src.ui.ttk.LabelFrame"
        ) as MockLabelFrame, patch(
            "src.ui.ttk.Entry"
        ), patch(
            "src.ui.ttk.Button"
        ) as MockTtkButton, patch(
            "src.ui.ttk.Scrollbar"
        ) as MockScrollbar, patch(
            "src.ui.ttk.Checkbutton"
        ), patch(
            "src.ui.ttk.Radiobutton"
        ), patch(
            "src.ui.ttk.OptionMenu"
        ), patch(
            "src.ui.ttk.Progressbar"
        ), patch(
            "src.ui.ttk.Separator"
        ), patch(
            "src.ui.tk.Button"
        ) as MockTkButton, patch(
            "src.ui.tk.Canvas"
        ) as MockCanvas, patch(
            "src.ui.tk.Toplevel"
        ) as MockToplevel, patch(
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
            ui._test_ttk_button_class = MockTtkButton
            ui._test_tk_button_class = MockTkButton
            ui._test_canvas_class = MockCanvas
            ui._test_scrollbar_class = MockScrollbar
            ui._test_frame_class = MockFrame
            ui._test_label_class = MockLabel
            ui._test_label_frame_class = MockLabelFrame
            ui._test_toplevel_class = MockToplevel
            yield ui

    def test_init(self, ui):
        """UI should initialize widgets."""
        assert ui.day_entry is not None
        assert ui.night_entry is not None
        assert ui.print_btn is not None
        ui.root.title.assert_called_with("ShiftPress")

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

    def test_date_pickers_keep_the_calendar_dropdown_affordance(self, ui):
        """Date controls should use tkcalendar's arrow-bearing DateEntry style."""
        for panel in ui._shift_panels.values():
            for picker in (
                panel.single_picker,
                panel.range_start_picker,
                panel.range_end_picker,
            ):
                assert picker.constructor_kwargs["style"] == "DateEntry"

    def test_date_fields_are_pick_only(self, ui):
        """Typed dates can be silently wrong, so the field must not be editable."""
        panel = ui._shift_panels["night"]
        panel.enabled_var.set(True)

        ui._sync_shift_panel_state("night")

        for picker in (
            panel.single_picker,
            panel.range_start_picker,
            panel.range_end_picker,
        ):
            picker.config.assert_called_with(state="readonly")
        # Radios stay ordinary controls.
        panel.single_radio.config.assert_called_with(state="normal")

    def test_date_fields_open_the_calendar_on_click_and_key(self, ui):
        """A pick-only field must still be openable by mouse and keyboard."""
        picker = ui._shift_panels["night"].single_picker
        bound = {call.args[0] for call in picker.bind.call_args_list if call.args}

        assert "<Button-1>" in bound
        assert "<Down>" in bound

    def test_calendar_theme_reaches_tkcalendar_inline(self, ui):
        """Colours must be passed inline; calendar_kw is silently ignored."""
        kw = ui._shift_panels["night"].single_picker.constructor_kwargs

        # tkcalendar swallows an unknown calendar_kw= without raising, which
        # would leave the popup in its default light theme.
        assert "calendar_kw" not in kw
        assert kw["normalbackground"] == COLORS.surface
        assert kw["normalforeground"] == COLORS.text_main
        assert kw["headersbackground"] == COLORS.background
        assert kw["showweeknumbers"] is False

    def test_calendar_selection_is_legible_and_shift_coloured(self, ui):
        """The selected day needs dark ink on its shift accent, not near-white."""
        night = ui._shift_panels["night"].single_picker.constructor_kwargs
        day = ui._shift_panels["day"].single_picker.constructor_kwargs

        assert night["selectbackground"] == COLORS.night_accent
        assert day["selectbackground"] == COLORS.day_accent
        for kw in (night, day):
            assert kw["selectforeground"] == COLORS.background

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

    def test_set_day_folder_uses_primary_text_color(self, ui):
        """A real saved path must not render as placeholder gray."""
        ui.set_day_folder("C:/Templates/Day")

        ui.day_entry.config.assert_called_with(foreground=COLORS.text_main)
        ui.day_entry.insert.assert_called_with(0, "C:/Templates/Day")

    def test_set_night_folder_empty_restores_placeholder(self, ui):
        """An empty saved path must fall back to the dim placeholder."""
        ui.set_night_folder("")

        ui.night_entry.config.assert_called_with(foreground=COLORS.text_dim)
        ui.night_entry.insert.assert_called_with(0, _PATH_PLACEHOLDER)

    def test_single_date_row_matches_range_row_structure(self, ui):
        """Both date modes must build the same label-above-entry shape."""
        panel = ui._shift_panels["night"]

        panel.single_picker.pack.assert_any_call(fill="x")
        panel.range_start_picker.pack.assert_any_call(fill="x")
        panel.range_end_picker.pack.assert_any_call(fill="x")
        assert panel.single_picker.grid.call_count == 0

        date_labels = [
            call
            for call in ui._test_label_class.call_args_list
            if call.kwargs.get("text") == "Date"
        ]
        assert len(date_labels) == 2  # one per shift panel
        assert date_labels[0].kwargs["style"] == "CardSub.TLabel"

    def test_window_sizing_derives_from_rendered_content(self, ui, root):
        """minsize and geometry must come from content, not a hardcoded guess."""
        ui._main_content.winfo_reqheight.return_value = 812
        ui._main_content.winfo_reqwidth.return_value = 1000
        root.winfo_screenwidth.return_value = 1920
        root.winfo_screenheight.return_value = 1080
        root.minsize.reset_mock()
        root.geometry.reset_mock()

        with patch("src.ui._get_work_area", return_value=(0, 0, 1920, 1040)):
            ui._apply_content_sizing()

        root.minsize.assert_called_once_with(1040, 400)
        root.geometry.assert_called_once_with("1040x812")

    def test_constrained_display_enables_vertical_overflow_recovery(self, ui, root):
        """Content taller than the usable screen must remain reachable by scrolling."""
        ui._main_content.winfo_reqheight.return_value = 1100
        ui._main_content.winfo_reqwidth.return_value = 1000
        root.winfo_screenwidth.return_value = 1366
        root.winfo_screenheight.return_value = 768
        root.geometry.reset_mock()
        ui._show_main_scrollbar = MagicMock()

        with patch("src.ui._get_work_area", return_value=(0, 0, 1366, 728)):
            ui._apply_content_sizing()

        root.geometry.assert_called_once_with("1040x688")
        ui._show_main_scrollbar.assert_called_once()

    def test_main_overflow_helpers_resize_and_scroll_visible_content(self, ui):
        """The main viewport must expose and operate its scrollbar when constrained."""
        event = MagicMock(width=640, height=480, delta=60)
        ui._main_content.winfo_reqheight.return_value = 900
        ui._main_scrollbar.winfo_ismapped.return_value = True

        ui._sync_main_scroll_region()
        ui._resize_main_content(event)
        ui._scroll_main_content(event)

        ui._main_canvas.configure.assert_any_call(
            scrollregion=ui._main_canvas.bbox.return_value
        )
        ui._main_canvas.itemconfigure.assert_called_with(
            ui._main_content_window, width=640
        )
        ui._main_scrollbar.pack.assert_called_with(side="right", fill="y")
        ui._main_canvas.yview_scroll.assert_called_with(-1, "units")

    def test_windows_work_area_keeps_the_main_window_above_the_taskbar(self, ui, root):
        """Centering must use Windows' work area, not the taskbar-covered screen."""
        root.winfo_width.return_value = 1040
        root.winfo_height.return_value = 828
        root.geometry.reset_mock()

        with patch("src.ui._get_work_area", return_value=(0, 0, 1517, 894)):
            ui._center_window()

        root.geometry.assert_called_once_with("1040x828+230+13")

    def test_windows_work_area_caps_content_without_hiding_the_action(self, ui, root):
        """Very tall content must leave room for native window decorations."""
        ui._main_content.winfo_reqheight.return_value = 1100
        ui._main_content.winfo_reqwidth.return_value = 1000
        root.geometry.reset_mock()
        ui._show_main_scrollbar = MagicMock()

        with patch("src.ui._get_work_area", return_value=(0, 0, 1517, 894)):
            ui._apply_content_sizing()

        root.geometry.assert_called_once_with("1040x854")
        ui._show_main_scrollbar.assert_called_once()

    def test_setup_dialog_caps_height_and_enables_overflow_recovery(self, ui):
        """Required Setup controls must remain reachable on a short display."""
        dialog = ui._setup_dialog
        dialog.winfo_screenwidth.return_value = 1366
        dialog.winfo_screenheight.return_value = 600
        ui.root.winfo_rootx.return_value = 100
        ui.root.winfo_rooty.return_value = 100
        ui.root.winfo_width.return_value = 1040
        ui._setup_content.winfo_reqwidth.return_value = 700
        ui._setup_content.winfo_reqheight.return_value = 760
        ui._show_setup_scrollbar = MagicMock()

        with patch("src.ui._get_work_area", return_value=(0, 0, 1366, 560)):
            ui._show_setup_dialog()

        geometry = dialog.geometry.call_args.args[0]
        assert geometry.startswith("720x520+")
        ui._show_setup_scrollbar.assert_called_once()

    def test_setup_overflow_helpers_resize_and_scroll_visible_content(self, ui):
        """The Setup viewport must expose and operate its scrollbar when constrained."""
        event = MagicMock(width=620, height=400, delta=-60)
        ui._setup_content.winfo_reqheight.return_value = 700
        ui._setup_scrollbar.winfo_ismapped.return_value = True

        ui._sync_setup_scroll_region()
        ui._resize_setup_content(event)
        ui._scroll_setup_content(event)

        ui._setup_canvas.configure.assert_any_call(
            scrollregion=ui._setup_canvas.bbox.return_value
        )
        ui._setup_canvas.itemconfigure.assert_called_with(
            ui._setup_content_window, width=620
        )
        ui._setup_scrollbar.pack.assert_called_with(side="right", fill="y")
        ui._setup_canvas.yview_scroll.assert_called_with(1, "units")

    def test_manifest_preview_uses_actual_selected_job_count(self, ui):
        """The visible manifest and action should reflect independent jobs."""
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        assert (
            ui.manifest_title_label.config.call_args.kwargs["text"]
            == "Print scope: 2 schedules selected"
        )
        manifest_text = ui.manifest_label.config.call_args.kwargs["text"]
        assert "1. Night — 07/30/2026 — 1 document" in manifest_text
        assert "2. Day — 07/31/2026 — 1 document" in manifest_text
        assert "Printer: Test Printer" in manifest_text
        ui.print_btn.config.assert_any_call(text="Print 2 schedules")
        ui.print_btn.config.assert_any_call(state="normal")
        ui._shift_panels["night"].count_label.config.assert_called_with(
            text="Selected · 1 document", style="CountSelected.TLabel"
        )
        ui._shift_panels["day"].count_label.config.assert_called_with(
            text="Selected · 1 document", style="CountSelected.TLabel"
        )

    def test_single_schedule_manifest_reads_as_singular(self, ui):
        """A one-document run must not read 'This run: 1 schedules'."""
        ui._shift_panels["day"].enabled_var.set(False)
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        assert (
            ui.manifest_title_label.config.call_args.kwargs["text"]
            == "Print scope: 1 schedule selected"
        )
        ui.print_btn.config.assert_any_call(text="Print 1 schedule")

    def test_excluded_shift_uses_muted_state_not_success(self, ui):
        """An excluded shift must not render in success green."""
        ui._shift_panels["day"].enabled_var.set(False)
        # ttk.Label is patched with one mock class, so every label shares an
        # instance; give each panel its own to assert on them independently.
        ui._shift_panels["night"].count_label = MagicMock()
        ui._shift_panels["day"].count_label = MagicMock()
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        ui._shift_panels["day"].count_label.config.assert_called_once_with(
            text="Not included", style="CountMuted.TLabel"
        )

    def test_invalid_night_range_does_not_flag_valid_day(self, ui):
        """One shift's bad dates must not accuse the other shift."""
        night = ui._shift_panels["night"]
        night.mode_var.set("range")
        night.range_start_picker.set_date(date(2026, 8, 10))
        night.range_end_picker.set_date(date(2026, 8, 1))
        # ttk.Label is patched with one mock class, so every label shares an
        # instance; give each panel its own to assert on them independently.
        night.count_label = MagicMock()
        ui._shift_panels["day"].count_label = MagicMock()
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        night.count_label.config.assert_called_once_with(
            text="Check Night date selection", style="CountError.TLabel"
        )
        ui._shift_panels["day"].count_label.config.assert_called_once_with(
            text="Selected · 1 document", style="CountSelected.TLabel"
        )
        title = ui.manifest_title_label.config.call_args.kwargs["text"]
        assert title == "Print scope: Check Night date selection"
        body = ui.manifest_label.config.call_args.kwargs["text"]
        assert "Night schedule: End date cannot be before start date" in body
        ui.print_btn.config.assert_any_call(text="Print schedules")
        ui.print_btn.config.assert_any_call(state="disabled")

    def test_manifest_preview_blocks_empty_selection(self, ui):
        """No included shifts should produce no jobs and no numeric promise."""
        ui._shift_panels["night"].enabled_var.set(False)
        ui._shift_panels["day"].enabled_var.set(False)
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        assert (
            ui.manifest_title_label.config.call_args.kwargs["text"]
            == "Print scope: No schedules selected"
        )
        ui.print_btn.config.assert_any_call(text="Print schedules")
        ui.print_btn.config.assert_any_call(state="disabled")

    def test_manifest_preview_blocks_enabled_shift_without_its_folder(self, ui):
        """A locally missing folder should explain the exact Setup action."""
        ui.day_entry.get.return_value = ""
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        body = ui.manifest_label.config.call_args.kwargs["text"]
        assert "Cannot print: Choose Day Templates in Setup" in body
        ui.print_btn.config.assert_any_call(state="disabled")
        ui.status_label.config.assert_called_with(
            text="Choose Day Templates in Setup", style="Error.TLabel"
        )

    def test_manifest_preview_blocks_missing_printer(self, ui):
        """The action should stay disabled until an actual printer is selected."""
        ui.printer_var.set("Choose Printer")
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        body = ui.manifest_label.config.call_args.kwargs["text"]
        assert "Cannot print: Choose a printer in Setup" in body
        ui.print_btn.config.assert_any_call(state="disabled")
        ui.status_label.config.assert_called_with(
            text="Choose a printer in Setup", style="Error.TLabel"
        )

    def test_missing_dateentry_dependency_disables_print_with_recovery(self, ui):
        """A missing date picker dependency must become an actionable state."""
        ui._dependency_error = (
            "Date selection is unavailable. Reinstall ShiftPress to restore tkcalendar."
        )
        ui._shift_panels.clear()
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        assert (
            ui.manifest_title_label.config.call_args.kwargs["text"]
            == "Print scope: Date selection unavailable"
        )
        assert (
            "Reinstall ShiftPress" in ui.manifest_label.config.call_args.kwargs["text"]
        )
        ui.print_btn.config.assert_any_call(state="disabled")

    def test_selected_count_style_is_neutral_before_preflight(self, ui):
        """A local selection must not use success green before preflight."""
        ui.style.configure.assert_any_call(
            "CountSelected.TLabel",
            font=FONTS.bold,
            foreground=COLORS.text_main,
            background=COLORS.surface,
        )

    def test_primary_action_uses_themed_ttk_button(self, ui):
        """The primary action must not use the unreadable macOS classic Tk button."""
        ttk_print_calls = [
            call
            for call in ui._test_ttk_button_class.call_args_list
            if str(call.kwargs.get("text", "")).startswith("Print")
        ]
        tk_print_calls = [
            call
            for call in ui._test_tk_button_class.call_args_list
            if str(call.kwargs.get("text", "")).startswith("Print")
        ]

        assert len(ttk_print_calls) == 1
        assert ttk_print_calls[0].kwargs["style"] == "Primary.TButton"
        assert tk_print_calls == []

    def test_primary_action_uses_action_blue_focus_border(self, ui):
        """The print action should not borrow the Day shift amber border."""
        ui.style.configure.assert_any_call(
            "Primary.TButton",
            background=COLORS.action,
            foreground=COLORS.text_main,
            bordercolor=COLORS.action,
            borderwidth=1,
            font=FONTS.button,
            padding=(26, 16),
        )

    def test_interactive_styles_have_explicit_keyboard_focus(self, ui):
        """Native controls need a visible high-contrast focus treatment."""
        for style_name in ("TButton", "TEntry", "TCombobox", "TMenubutton"):
            ui.style.map.assert_any_call(
                style_name,
                bordercolor=[("focus", COLORS.night_accent)],
                lightcolor=[("focus", COLORS.night_accent)],
                darkcolor=[("focus", COLORS.night_accent)],
            )

    def test_group_titles_use_clean_background_and_custom_card_shells(self, ui):
        """Section titles should sit on the window without LabelFrame patches."""
        for style_name, foreground in (
            ("SetupTitle.TLabel", COLORS.text_main),
            ("NightTitle.TLabel", COLORS.night_accent),
            ("DayTitle.TLabel", COLORS.day_accent),
        ):
            ui.style.configure.assert_any_call(
                style_name,
                background=COLORS.background,
                foreground=foreground,
                font=FONTS.card_title,
            )
        assert ui._test_label_frame_class.call_count == 0
        card_styles = {
            call.kwargs.get("style") for call in ui._test_frame_class.call_args_list
        }
        assert {
            "SetupCard.TFrame",
            "NightCard.TFrame",
            "DayCard.TFrame",
        } <= card_styles

    def test_generic_input_selection_does_not_borrow_day_amber(self, ui):
        """Amber should identify Day, not generic input or menu interaction."""
        ui.style.configure.assert_any_call(
            "TEntry",
            fieldbackground=COLORS.input,
            foreground=COLORS.text_main,
            insertcolor=COLORS.text_main,
            selectbackground=COLORS.action,
            selectforeground=COLORS.text_main,
            bordercolor=COLORS.border,
            borderwidth=1,
            padding=(8, 7),
        )

    def test_manifest_uses_plain_bordered_frame_without_empty_title_strip(self, ui):
        """The manifest should not reserve a blank LabelFrame title channel."""
        manifest_frames = [
            call
            for call in ui._test_frame_class.call_args_list
            if call.kwargs.get("style") == "Manifest.TFrame"
        ]
        assert len(manifest_frames) == 1
        assert ui._manifest_card is not None

    def test_footer_flows_after_manifest_and_logs_action_is_tertiary(self, ui):
        """Footer actions should stay compact instead of pinning to the window floor."""
        ui._footer_frame.pack.assert_any_call(fill="x")
        assert not any(
            call.kwargs.get("side") == "bottom"
            for call in ui._footer_frame.pack.call_args_list
        )
        logs_calls = [
            call
            for call in ui._test_ttk_button_class.call_args_list
            if call.kwargs.get("text") == "Open logs"
        ]
        assert len(logs_calls) == 1
        assert logs_calls[0].kwargs["style"] == "Tertiary.TButton"

        help_calls = [
            call
            for call in ui._test_ttk_button_class.call_args_list
            if call.kwargs.get("text") == "How to use"
        ]
        assert len(help_calls) == 1
        assert help_calls[0].kwargs["style"] == "Tertiary.TButton"

    def test_progress_is_hidden_until_status_work_begins(self, ui):
        """An idle 0% bar should not compete with the primary task."""
        ui._progress_row.grid_remove.assert_called()

        ui.update_status("Checking templates…", 0, level="info")

        ui._progress_row.grid.assert_called()

    def test_long_manifest_and_status_copy_wraps_in_the_window(self, ui):
        """Long operational state should wrap instead of widening or clipping."""
        manifest_call = next(
            call
            for call in ui._test_label_class.call_args_list
            if call.kwargs.get("text") == "Printer: Choose a printer"
        )
        status_call = next(
            call
            for call in ui._test_label_class.call_args_list
            if call.kwargs.get("text") == "Complete Setup to prepare a print scope"
        )

        assert manifest_call.kwargs["wraplength"] == 760
        assert status_call.kwargs["wraplength"] == 620

    def test_processing_mode_uses_danger_style_then_restores_manifest_action(self, ui):
        """Cancel state and normal print state should each use readable ttk styling."""
        ui.print_btn = MagicMock()

        ui.set_processing_mode(True)
        ui.set_processing_mode(False)

        ui.print_btn.config.assert_any_call(text="Cancel", style="Danger.TButton")
        ui.print_btn.config.assert_any_call(style="Primary.TButton")

    def test_leaving_processing_mode_preserves_the_run_outcome_status(self, ui):
        """Re-enabling the action must not replace the final success/error message."""
        ui.refresh_manifest_preview = MagicMock()

        ui.set_processing_mode(False)

        ui.refresh_manifest_preview.assert_called_once_with(update_status=False)

    def test_logs_action_appears_only_for_runtime_errors(self, ui):
        """Troubleshooting chrome should stay out of the everyday workflow."""
        ui._logs_btn.pack.reset_mock()

        ui.update_status("Processing stopped: RuntimeError", 50, level="error")

        ui._logs_btn.pack.assert_called_once_with(side="left", padx=(12, 0))

    def test_setup_summary_identifies_template_folder_tails(self, ui):
        """Collapsed setup should identify active sources without showing long paths."""
        ui.setup_summary_label = MagicMock()

        ui.refresh_setup_summary()

        summary = ui.setup_summary_label.config.call_args.kwargs["text"]
        assert summary == (
            "Night templates: C: › Templates › Night\n"
            "Day templates: C: › Templates › Day\n"
            "Printer: Test Printer"
        )

    def test_setup_fields_follow_night_then_day_workflow_order(self, ui):
        """Setup should preserve the same Night-to-Day sequence as the work surface."""
        labels = [
            call.kwargs.get("text")
            for call in ui._test_label_class.call_args_list
            if call.kwargs.get("text") in {"Night Templates", "Day Templates"}
        ]
        assert labels == ["Night Templates", "Day Templates"]

    def test_folder_summary_distinguishes_same_tail_from_different_sites(self, ui):
        """Compact source labels must retain the drive and site identity."""
        first = ui._folder_tail(r"C:\SiteA\Templates\Night")
        second = ui._folder_tail(r"D:\SiteB\Templates\Night")

        assert first == "C: › SiteA › Night"
        assert second == "D: › SiteB › Night"
        assert first != second

    def test_refresh_printers_updates_visible_availability(self, ui):
        """Printer refresh should update the persistent availability message."""
        ui._printer_status_label = MagicMock()
        ui._enumerate_printers = MagicMock(return_value=["Office Printer"])

        ui.refresh_printers()

        ui._printer_status_label.config.assert_called_with(
            text="1 printer available", style="CardSub.TLabel"
        )

    def test_setup_dialog_uses_close_action(self, ui):
        """Setup should expose explicit commit and rollback actions."""
        apply_calls = [
            call
            for call in ui._test_ttk_button_class.call_args_list
            if call.kwargs.get("text") == "Apply"
        ]
        cancel_calls = [
            call
            for call in ui._test_ttk_button_class.call_args_list
            if call.kwargs.get("text") == "Cancel"
        ]
        assert len(apply_calls) == 1
        assert len(cancel_calls) == 1

    def test_cancel_setup_restores_values_from_when_dialog_opened(self, ui):
        """An accidental Setup edit must be reversible without remembering values."""
        ui._show_setup_dialog()
        ui.day_entry.get.return_value = "C:/Wrong/Day"
        ui.night_entry.get.return_value = "C:/Wrong/Night"
        ui.printer_var.set("Wrong Printer")

        ui._cancel_setup_dialog()

        ui.day_entry.delete.assert_called_with(0, tk.END)
        ui.day_entry.insert.assert_called_with(0, "C:/Templates/Day")
        ui.night_entry.insert.assert_called_with(0, "C:/Templates/Night")
        assert ui.printer_var.get() == "Test Printer"

    @patch("src.ui.filedialog.askdirectory", return_value="C:/New/Day")
    def test_browsing_folder_refreshes_readiness(self, _askdirectory, ui):
        """Choosing a folder should immediately recompute the local blocker state."""
        ui.refresh_manifest_preview = MagicMock()

        ui._browse_folder(ui.day_entry)

        ui.refresh_manifest_preview.assert_called_once()

    def test_setup_dialog_preserves_main_layout_and_configured_values(self, ui):
        """Setup should open separately instead of expanding the main work surface."""
        dialog = ui._setup_dialog
        dialog.reset_mock()
        before = (
            ui.get_day_folder(),
            ui.get_night_folder(),
            ui.get_printer_name(),
        )

        ui._show_setup_dialog()
        ui._hide_setup_dialog()

        dialog.deiconify.assert_called_once()
        dialog.lift.assert_called_once()
        dialog.focus_force.assert_called_once()
        ui.night_entry.focus_set.assert_called_once()
        dialog.withdraw.assert_called_once()
        assert before == (
            ui.get_day_folder(),
            ui.get_night_folder(),
            ui.get_printer_name(),
        )

    def test_setup_dialog_binds_escape_to_close(self, ui):
        """Setup should be fully dismissible from the keyboard."""
        bound_keys = [call.args[0] for call in ui._setup_dialog.bind.call_args_list]
        assert "<Escape>" in bound_keys

    def test_setup_and_help_have_global_keyboard_shortcuts(self, ui):
        """Frequently used secondary actions need documented mnemonics."""
        bound_keys = [call.args[0] for call in ui.root.bind.call_args_list]
        assert "<Alt-s>" in bound_keys
        assert "<Alt-h>" in bound_keys

    def test_setup_button_mnemonic_matches_alt_s_shortcut(self, ui):
        """The visible Setup mnemonic must match the documented Alt+S binding."""
        setup_calls = [
            call
            for call in ui._test_ttk_button_class.call_args_list
            if call.kwargs.get("text") == "Setup…"
        ]
        assert len(setup_calls) == 1
        assert setup_calls[0].kwargs["underline"] == 0

    def test_reset_run_restores_the_common_night_then_day_defaults(self, ui):
        """Repeat operators need one action to undo accidental scope drift."""
        night = ui._shift_panels["night"]
        day = ui._shift_panels["day"]
        night.enabled_var.set(False)
        night.mode_var.set("range")
        day.enabled_var.set(False)
        day.mode_var.set("range")

        ui._reset_run()

        assert night.enabled_var.get() is True
        assert day.enabled_var.get() is True
        assert night.mode_var.get() == "single"
        assert day.mode_var.get() == "single"
        assert night.single_picker.get_date() == date(2026, 7, 30)
        assert day.single_picker.get_date() == date(2026, 7, 31)

    def test_show_help_explains_the_operator_flow(self, ui):
        """Help copy should make selection, setup, and preflight understandable."""
        ui.show_info = MagicMock()

        ui.show_help()

        title, message = ui.show_info.call_args.args
        assert title == "How to use ShiftPress"
        assert "Night" in message
        assert "Day" in message
        assert "preflight" in message.lower()

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

    def test_status_style_helper_preserves_explicit_and_inferred_states(self):
        """The extracted status decision must preserve every public style rule."""
        style_for = getattr(ui_module, "_status_style", None)
        assert callable(style_for)
        assert style_for("Anything", "success") == "Success.TLabel"
        assert style_for("Anything", "error") == "Error.TLabel"
        assert style_for("Anything", "info") == "Sub.TLabel"
        assert style_for("Print complete", None) == "Success.TLabel"
        assert style_for("Print failed", None) == "Error.TLabel"
        assert style_for("Processing", None) == "Sub.TLabel"

    def test_manifest_blocker_helper_keeps_missing_printer_actionable(self, ui):
        """The extracted blocker decision must keep Print disabled without a printer."""
        blocker_for = getattr(ui_module, "_manifest_blocker", None)
        assert callable(blocker_for)
        selections = ui.get_shift_selections()
        assert (
            blocker_for(selections, (), (MagicMock(),), "Choose a printer")
            == "Choose a printer in Setup"
        )

    @patch("tkinter.messagebox.showerror")
    def test_show_error(self, mock_error, ui):
        """Should call messagebox.showerror."""
        ui.show_error("Title", "Message")
        mock_error.assert_called_with("Title", "Message")

    def test_set_start_command(self, ui):
        """Should set the button command and bind keyboard actions."""
        mock_cmd = MagicMock()
        ui.set_start_command(mock_cmd)
        ui.print_btn.config.assert_called_with(command=mock_cmd)
        bound_keys = [call.args[0] for call in ui.root.bind.call_args_list]
        assert "<Alt-p>" in bound_keys

    def test_set_start_command_with_cancel(self, ui):
        """Should bind Escape key when cancel_command is provided."""
        mock_cmd = MagicMock()
        mock_cancel = MagicMock()
        ui.set_start_command(mock_cmd, cancel_command=mock_cancel)
        ui.print_btn.config.assert_called_with(command=mock_cmd)
        # Verify Escape was bound (check bind call args for "<Escape>")
        bound_keys = [call[0][0] for call in ui.root.bind.call_args_list]
        assert "<Escape>" in bound_keys
