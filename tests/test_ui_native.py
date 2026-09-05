"""Real Windows Tk widgets: mocks cannot establish calendar/theme behavior."""

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from datetime import date
from unittest.mock import patch

import pytest

from src.constants import THEMES
from src.ui import ScheduleAppUI, configure_windows_dpi

configure_windows_dpi()


@pytest.fixture(scope="module")
def tk_runtime():
    """Use one Tcl interpreter, with an isolated window for each UI test."""
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_dark_themes_restyle_real_calendars_without_unlocking_inputs(tk_runtime):
    """Both palettes reach tkcalendar while independent dates and locks survive."""
    root = tk.Toplevel(tk_runtime)
    root.withdraw()
    try:
        ui = ScheduleAppUI(root, today=date(2026, 9, 5))
        night = ui._shift_panels["night"]
        night.mode_var.set("range")
        night.range_end_picker.set_date(date(2026, 9, 8))
        ui._sync_shift_panel_state("night")
        ui._shift_panels["day"].enabled_var.set(False)
        ui._sync_shift_panel_state("day")
        selections = ui.get_shift_selections()
        ui.set_inputs_enabled(False)
        for theme in ("rose", "midnight", "rose"):
            ui.set_theme(theme)
            root.update_idletasks()
            assert ui.get_shift_selections() == selections
            assert root.cget("background") == THEMES[theme].background
            assert str(night.range_start_picker.cget("state")) == "disabled"
            assert (
                night.range_start_picker.cget("background") == THEMES[theme].background
            )
            assert (
                ui.style.lookup("DateEntry", "fieldbackground", ("readonly",))
                == THEMES[theme].input
            )
            assert ui._theme_menu.entrycget(0, "value") == "Midnight"
            assert ui._theme_menu.entrycget(1, "value") == "Rose"
            assert ui.style.lookup("DateEntry", "arrowcolor") == THEMES[theme].action
            assert (
                str(ui.printer_dropdown["menu"].cget("background"))
                == THEMES[theme].surface
            )
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_reset_is_disabled_during_a_batch_and_restored_afterward(tk_runtime):
    """The real Reset button must preserve active scope and a usable Cancel."""
    root = tk.Toplevel(tk_runtime)
    try:
        ui = ScheduleAppUI(root, today=date(2026, 9, 5))
        ui.set_night_folder("C:/review/night")
        ui.set_day_folder("C:/review/day")
        ui.printer_var.set("Review fake printer")
        ui._shift_panels["day"].enabled_var.set(False)
        ui._sync_shift_panel_state("day")
        before = ui.get_shift_selections()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        reset = next(
            widget
            for widget in descendants(root)
            if widget.winfo_class() == "TButton" and widget.cget("text") == "Reset run"
        )
        ui.set_inputs_enabled(False)
        ui.set_processing_mode(True)
        root.update()
        assert "disabled" in reset.state()
        reset.invoke()
        assert ui.get_shift_selections() == before
        assert ui.print_btn.cget("text") == "Cancel"
        assert "disabled" not in ui.print_btn.state()

        ui.set_inputs_enabled(True)
        ui.set_processing_mode(False)
        root.update()
        assert "disabled" not in reset.state()
        reset.invoke()
        assert all(selection.enabled for selection in ui.get_shift_selections())
        assert ui.print_btn.cget("text") == "Print 2 schedules"
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_help_uses_dark_readable_content_and_closes_with_escape(tk_runtime):
    """Help must not escape the palette into an OS-light message box."""
    root = tk.Toplevel(tk_runtime)
    try:
        ui = ScheduleAppUI(root)
        ui.show_info = lambda *_args: None
        ui.set_theme("rose")
        ui.show_help()
        root.update()
        dialog = getattr(ui, "_help_dialog", None)
        assert dialog is not None
        assert dialog.winfo_viewable()
        assert dialog.cget("background") == THEMES["rose"].background
        content = ui._help_text.get("1.0", "end")
        for term in ("Night", "Day", "Apply", "Cancel", "preflight", "Alt+S"):
            assert term in content
        assert str(ui._help_text.cget("state")) == "disabled"
        assert root.grab_current() is None  # Reference help is non-modal.
        ui.set_theme("midnight")
        assert ui._help_text.cget("background") == THEMES["midnight"].background
        ui.show_help()
        assert ui._help_dialog is dialog  # Reuse, do not multiply windows.
        dialog.event_generate("<Escape>")
        root.update()
        assert not dialog.winfo_viewable()
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_help_opens_without_overflow_when_the_work_area_has_room(tk_runtime):
    """The preferred help size must fit the actual wrapped text, not 610px."""
    root = tk.Toplevel(tk_runtime)
    try:
        ui = ScheduleAppUI(root)
        root.update()
        for theme in ("rose", "midnight"):
            ui.set_theme(theme)
            ui.show_help()
            root.update()
            assert ui._help_text.yview() == (0.0, 1.0)
            assert not any(
                child.winfo_ismapped()
                for child in ui._help_text.master.winfo_children()
                if child.winfo_class() == "TScrollbar"
            )
            ui._hide_help_dialog()
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_help_retains_scrolling_and_close_on_short_work_areas(tk_runtime):
    """Content fitting must not put the close action below a small display."""
    root = tk.Toplevel(tk_runtime)
    try:
        ui = ScheduleAppUI(root)
        root.update()
        # Constrain design-space height, not raw pixels: 700px can fit all
        # content at 100% scaling even though it overflows at 200%.
        work_height = ui._px(360)
        with patch("src.ui._get_work_area", return_value=(0, 0, 1400, work_height)):
            ui.show_help()
        root.update()
        dialog = ui._help_dialog
        assert dialog.winfo_height() <= work_height - ui._px(64)
        assert ui._help_text.yview()[1] < 1
        ui._help_text.yview_moveto(1)
        root.update()
        assert ui._help_text.yview()[1] == 1
        close = next(
            child
            for frame in dialog.winfo_children()
            for child in frame.winfo_children()
            if child.winfo_class() == "TButton"
        )
        assert close.winfo_viewable()
        assert close.winfo_rooty() + close.winfo_height() <= (
            dialog.winfo_rooty() + dialog.winfo_height()
        )
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_theme_menu_switches_palette_without_changing_scope(tk_runtime):
    """The button/menu pair has no editable text-selection artifact."""
    root = tk.Toplevel(tk_runtime)
    try:
        ui = ScheduleAppUI(root)
        assert ui._theme_picker.winfo_class() == "TMenubutton"
        selections = ui.get_shift_selections()
        for index, theme in ((1, "rose"), (0, "midnight"), (1, "rose")):
            ui._theme_menu.invoke(index)
            root.update_idletasks()
            assert ui.get_theme() == theme
            assert ui.get_shift_selections() == selections
            assert str(ui._theme_menu.cget("background")) == THEMES[theme].surface
            assert str(ui._theme_menu.cget("activebackground")) == THEMES[theme].action
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_short_window_keeps_print_visible_and_allows_narrower_resize(tk_runtime):
    """The action must remain on-screen while only the form scrolls."""
    root = tk.Toplevel(tk_runtime)
    try:
        with patch("src.ui._get_work_area", return_value=(0, 0, 2000, 1000)):
            ui = ScheduleAppUI(root)
        root.update()
        initial_width = root.winfo_width()
        assert root.minsize()[0] < initial_width
        root.geometry(f"{initial_width}x600")
        root.update()
        assert ui.print_btn.winfo_viewable()
        assert (
            ui.print_btn.winfo_rooty() + ui.print_btn.winfo_height()
            <= root.winfo_rooty() + root.winfo_height()
        )
        assert ui._main_scrollbar.winfo_ismapped()
        assert ui._main_content.winfo_reqheight() > ui._main_canvas.winfo_height()
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_owned_titlebars_stay_dark_after_opening_and_reopening(tk_runtime):
    """Tk must not discard dark chrome when Setup becomes an owned window."""
    root = tk.Toplevel(tk_runtime)
    get_parent = ctypes.windll.user32.GetParent
    get_parent.argtypes = [wintypes.HWND]
    get_parent.restype = wintypes.HWND
    get_attribute = ctypes.windll.dwmapi.DwmGetWindowAttribute
    get_attribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    try:
        ui = ScheduleAppUI(root)
        root.update()  # The operator opens Setup after the main window is mapped.
        for theme in ("rose", "midnight", "rose"):
            ui.set_theme(theme)
            ui._show_setup_dialog()
            root.update()
            for window in (root, ui._setup_dialog):
                dark = wintypes.BOOL()
                assert (
                    get_attribute(
                        get_parent(window.winfo_id()),
                        20,
                        ctypes.byref(dark),
                        ctypes.sizeof(dark),
                    )
                    == 0
                )
                assert dark.value == 1, window.title()
            ui._cancel_setup_dialog()
            ui.show_help()
            root.update()
            dark = wintypes.BOOL()
            assert (
                get_attribute(
                    get_parent(ui._help_dialog.winfo_id()),
                    20,
                    ctypes.byref(dark),
                    ctypes.sizeof(dark),
                )
                == 0
            )
            assert dark.value == 1
            ui._hide_help_dialog()
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_owned_windows_share_the_shiftpress_titlebar_icon(tk_runtime):
    """Owned windows must inherit ShiftPress, not Tk's feather icon."""
    root = tk.Toplevel(tk_runtime)
    get_parent = ctypes.windll.user32.GetParent
    get_parent.argtypes = [wintypes.HWND]
    get_parent.restype = wintypes.HWND
    send_message = ctypes.windll.user32.SendMessageW
    send_message.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    send_message.restype = wintypes.HANDLE
    get_class_icon = ctypes.windll.user32.GetClassLongPtrW
    get_class_icon.argtypes = [wintypes.HWND, ctypes.c_int]
    get_class_icon.restype = wintypes.HANDLE
    try:
        ui = ScheduleAppUI(root)
        ui._show_setup_dialog()
        ui._cancel_setup_dialog()
        ui.show_help()
        root.update()
        for size, class_index in ((0, -34), (1, -14)):
            # Windows uses the class icon when WM_GETICON has no override.
            icons = [
                send_message(get_parent(window.winfo_id()), 0x007F, size, 0)
                or get_class_icon(get_parent(window.winfo_id()), class_index)
                for window in (root, ui._setup_dialog, ui._help_dialog)
            ]
            assert all(icons)
            assert len(set(icons)) == 1
    finally:
        root.destroy()


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native Windows Tk")
def test_dropdowns_share_field_and_arrow_geometry(tk_runtime):
    """Date pickers must not retain the narrow split-button combobox chrome."""
    root = tk.Toplevel(tk_runtime)
    try:
        ui = ScheduleAppUI(root)
        root.update()
        for theme in ("rose", "midnight"):
            ui.set_theme(theme)
            ui._show_setup_dialog()
            root.update()
            pickers = [
                ui._theme_picker,
                ui.printer_dropdown,
                ui._shift_panels["night"].single_picker,
                ui._shift_panels["day"].single_picker,
            ]
            assert len({picker.winfo_reqheight() for picker in pickers}) == 1
            arrow_widths = []
            for picker in pickers:
                width, height = picker.winfo_width(), picker.winfo_height()
                arrow_widths.append(
                    sum(
                        picker.identify(x, height // 2) == "Menubutton.indicator"
                        for x in range(width)
                    )
                )
            assert all(arrow_widths)
            assert len(set(arrow_widths)) == 1
            ui._cancel_setup_dialog()
        # Reskinning must preserve tkcalendar's actual arrow-click hit target.
        root.focus_force()
        root.update()  # Finish Setup's focus restoration before the next click.
        for panel in ui._shift_panels.values():
            picker = panel.single_picker
            picker.event_generate(
                "<ButtonPress-1>",
                x=picker.winfo_width() - 10,
                y=picker.winfo_height() // 2,
            )
            root.update()
            assert picker._top_cal.winfo_viewable()
            picker.drop_down()
    finally:
        root.destroy()
