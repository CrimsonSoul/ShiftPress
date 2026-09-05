"""
UI components for ShiftPress application.

This module contains all Tkinter UI components and styling.
"""

import os
import re
import sys
import ctypes
import subprocess
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass
from tkinter import messagebox, filedialog, ttk
from datetime import date, timedelta
from pathlib import Path

try:
    from tkcalendar import DateEntry  # type: ignore
except Exception:  # pragma: no cover
    DateEntry = None

from typing import Optional, Callable, Literal, Any, cast, overload

try:
    import win32print  # type: ignore
except Exception:  # pragma: no cover
    win32print = None

from .constants import (
    COLORS,
    THEMES,
    FONTS,
    WINDOW_WIDTH,
    WINDOW_RESIZABLE,
    PROGRESS_MAX,
    PRINTER_ENUM_LOCAL,
    PRINTER_ENUM_CONNECTIONS,
    DEFAULT_PRINTER_LABEL,
    AUTO_RESIZE_MIN_WIDTH,
    AUTO_RESIZE_MIN_HEIGHT,
)
from .logger import get_logger
from .app_paths import get_data_dir
from .print_manifest import (
    DateMode,
    PrintJob,
    ShiftSelection,
    ShiftType,
    build_print_manifest,
)

logger = get_logger(__name__)

_SPI_GETWORKAREA = 0x0030
_FALLBACK_SYSTEM_UI_RESERVE = 40
_WINDOW_FRAME_WIDTH_RESERVE = 16
_WINDOW_FRAME_HEIGHT_RESERVE = 40

# Imported lazily to avoid circular dependency; only used for version display.
_APP_VERSION: Optional[str] = None

# Placeholder text shown in empty path entries.
_PATH_PLACEHOLDER = "Click Browse to select folder\u2026"

# Reused Tk style and tkcalendar tokens. Keeping these names centralized avoids
# accidental drift between style definitions and widget construction.
_STYLE_CARD_FRAME = "Card.TFrame"
_STYLE_CARD_SUB_LABEL = "CardSub.TLabel"
_STYLE_TERTIARY_BUTTON = "Tertiary.TButton"
_STYLE_PRIMARY_BUTTON = "Primary.TButton"
_STYLE_DANGER_BUTTON = "Danger.TButton"
_STYLE_HEADER_LABEL = "Header.TLabel"
_STYLE_SUB_LABEL = "Sub.TLabel"
_STYLE_COUNT_SELECTED_LABEL = "CountSelected.TLabel"
_STYLE_SUCCESS_LABEL = "Success.TLabel"
_STYLE_ERROR_LABEL = "Error.TLabel"
_STYLE_CARD_CHECKBUTTON = "Card.TCheckbutton"
_STYLE_CARD_RADIOBUTTON = "Card.TRadiobutton"
_DATE_ENTRY_SELECTED_EVENT = "<<DateEntrySelected>>"
_DATE_PATTERN = "mm/dd/yyyy"
_FOCUS_IN_EVENT = "<FocusIn>"
_CONFIGURE_EVENT = "<Configure>"
_PRINT_BUTTON_LABEL = "Print schedules"


def _status_style(
    message: str,
    level: Optional[Literal["info", "success", "error"]],
) -> str:
    """Return the visual style for an explicit or inferred status level."""
    if level == "success":
        return _STYLE_SUCCESS_LABEL
    if level == "error":
        return _STYLE_ERROR_LABEL
    if level is not None:
        return _STYLE_SUB_LABEL

    message_lower = message.lower()
    if "complete" in message_lower:
        return _STYLE_SUCCESS_LABEL
    if any(token in message_lower for token in ("cancel", "error", "fail")):
        return _STYLE_ERROR_LABEL
    return _STYLE_SUB_LABEL


def _manifest_blocker(
    selections: tuple[ShiftSelection, ShiftSelection],
    invalid: tuple[ShiftSelection, ...],
    manifest: tuple[Any, ...],
    printer_label: str,
) -> Optional[str]:
    """Return the first local condition that must block the Print action."""
    if invalid:
        names = " and ".join(selection.shift_type.title() for selection in invalid)
        return f"Fix {names} date selection"
    if not manifest:
        return "Select at least one Night or Day schedule"

    missing_folder = next(
        (
            selection
            for selection in selections
            if selection.enabled and not selection.folder.strip()
        ),
        None,
    )
    if missing_folder is not None:
        return f"Choose {missing_folder.shift_type.title()} Templates in Setup"
    if printer_label == "Choose a printer":
        return "Choose a printer in Setup"
    return None


def configure_windows_dpi() -> None:
    """Use sharp system-DPI rendering; call before constructing the Tk root."""
    if sys.platform != "win32":
        return
    try:
        # System-aware (-2) suits Tk's fixed point scaling. A packaged manifest
        # may already set awareness, in which case Windows keeps that setting.
        getattr(ctypes, "windll").user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-2)
        )
    except (AttributeError, OSError):
        logger.debug("Windows DPI configuration unavailable", exc_info=True)


def _get_work_area(window: tk.Misc) -> tuple[int, int, int, int]:
    """Return usable screen bounds, excluding the Windows taskbar when possible."""
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()

    if sys.platform == "win32":
        try:
            rect = wintypes.RECT()
            user32 = getattr(ctypes, "windll").user32
            if user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                if rect.right > rect.left and rect.bottom > rect.top:
                    return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            logger.debug("Could not query the Windows work area", exc_info=True)

    # Tk exposes the full display rather than platform-reserved areas on some
    # systems. Preserve a small taskbar/dock allowance in that fallback path.
    return (
        0,
        0,
        screen_width,
        max(AUTO_RESIZE_MIN_HEIGHT, screen_height - _FALLBACK_SYSTEM_UI_RESERVE),
    )


@dataclass
class _ShiftPanelWidgets:
    """Widget and variable references for one independent shift panel."""

    enabled_var: tk.BooleanVar
    mode_var: tk.StringVar
    include_check: ttk.Checkbutton
    single_radio: ttk.Radiobutton
    range_radio: ttk.Radiobutton
    single_picker: Any
    range_start_picker: Any
    range_end_picker: Any
    single_wrap: ttk.Frame
    range_wrap: ttk.Frame
    count_label: ttk.Label


def _get_version() -> str:
    """Return the package version string.

    Returns:
        Version string (e.g. ``"3.0.0"``), or ``""`` if unavailable.
    """
    global _APP_VERSION
    if _APP_VERSION is None:
        try:
            from . import __version__

            _APP_VERSION = __version__
        except Exception as e:
            logger.debug(f"Could not determine app version: {e}")
            _APP_VERSION = ""
    return _APP_VERSION


def _setup_placeholder(entry: ttk.Entry, placeholder: str) -> None:
    """Attach placeholder text behaviour to a ttk.Entry.

    Shows *placeholder* in dim text when the entry is empty and unfocused.
    Clears the placeholder on focus and restores it on blur if still empty.
    """

    def _show(_event: Any = None) -> None:
        if not entry.get():
            entry.config(foreground=COLORS.text_dim)
            entry.insert(0, placeholder)

    def _hide(_event: Any = None) -> None:
        if entry.get() == placeholder:
            entry.delete(0, tk.END)
            entry.config(foreground=COLORS.text_main)

    entry.bind(_FOCUS_IN_EVENT, _hide, add="+")
    entry.bind("<FocusOut>", _show, add="+")
    # Show placeholder initially if entry is empty.
    _show()


class ScheduleAppUI:
    """Main UI class for the ShiftPress application."""

    def __init__(self, root: tk.Tk, today: Optional[date] = None):
        """
        Initialize the UI.

        Args:
            root: The Tkinter root window.
            today: Optional deterministic date used for launch defaults.
        """
        self.root = root
        self._scale = (
            max(1.0, float(root.winfo_fpixels("1i")) / 96)
            if sys.platform == "win32"
            else 1.0
        )
        _, work_top, _, work_bottom = _get_work_area(root)
        self._compact_layout = work_bottom - work_top < self._px(960)
        self.colors = COLORS
        self.theme_var = tk.StringVar(value="Midnight")
        self.root.title("ShiftPress")
        self.root.resizable(WINDOW_RESIZABLE, WINDOW_RESIZABLE)
        self.root.configure(bg=self.colors.background)
        self._today = today or date.today()
        self._inputs_enabled = True
        self._dependency_error: Optional[str] = None

        # Apply window icon if available.
        self._apply_icon()

        # Configure styles
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._configure_styles()

        # UI components
        self.day_entry: Optional[ttk.Entry] = None
        self.night_entry: Optional[ttk.Entry] = None
        self.printer_var: Optional[tk.StringVar] = None
        self._setup_values: dict[str, ttk.Label] = {}
        self._theme_picker: Optional[ttk.Menubutton] = None
        self._theme_menu: Optional[tk.Menu] = None
        self._help_dialog: Optional[tk.Toplevel] = None
        self._help_text: Optional[tk.Text] = None
        self._help_button: Optional[ttk.Button] = None
        self._manifest_printer_label: Optional[ttk.Label] = None
        self._setup_details: Optional[ttk.Frame] = None
        self._setup_dialog: Optional[tk.Toplevel] = None
        self._setup_canvas: Optional[tk.Canvas] = None
        self._setup_content: Optional[ttk.Frame] = None
        self._setup_content_window: Optional[int] = None
        self._setup_scrollbar: Optional[ttk.Scrollbar] = None
        self._setup_snapshot: Optional[tuple[str, str, str]] = None
        self._setup_toggle_btn: Optional[ttk.Button] = None
        self._reset_btn: Optional[ttk.Button] = None
        self._manifest_card: Optional[ttk.Frame] = None
        self._footer_frame: Optional[ttk.Frame] = None
        self._logs_btn: Optional[ttk.Button] = None
        self._main_canvas: Optional[tk.Canvas] = None
        self._main_content: Optional[ttk.Frame] = None
        self._main_content_window: Optional[int] = None
        self._main_scrollbar: Optional[ttk.Scrollbar] = None
        self.manifest_title_label: Optional[ttk.Label] = None
        self.manifest_label: Optional[ttk.Label] = None
        self.status_label: Optional[ttk.Label] = None
        self.progress_var: Optional[tk.DoubleVar] = None
        self.progress: Optional[ttk.Progressbar] = None
        self._progress_row: Optional[ttk.Frame] = None
        self._progress_pct: Optional[ttk.Label] = None
        self.printer_dropdown: Optional[ttk.OptionMenu] = None
        self._refresh_btn: Optional[ttk.Button] = None
        self._printer_status_label: Optional[ttk.Label] = None
        self.print_btn: Optional[ttk.Button] = None
        self._browse_buttons: list[ttk.Button] = []
        self._shift_panels: dict[ShiftType, _ShiftPanelWidgets] = {}

        # Cached enumerations
        self._cached_printers: list[str] = []

        # Create widgets
        self._create_widgets()

        # Derive geometry and minimum size from the rendered content.
        self._apply_content_sizing()

        # Center the window on screen after final sizing.
        self._center_window()
        self._style_titlebar(self.root)

        logger.info("UI initialized")

    def get_theme(self) -> str:
        """Return the persisted identifier of the selected dark palette."""
        return self.theme_var.get().lower()

    def _px(self, value: int) -> int:
        """Scale layout pixels alongside Windows' native point-sized text."""
        return round(value * self._scale)

    def _gap(self, value: int) -> int:
        """Use less vertical whitespace on short work areas, never smaller text."""
        return self._px(round(value * 0.65) if self._compact_layout else value)

    @overload
    def _spacing(self, first: int, second: int, /) -> tuple[int, int]: ...

    @overload
    def _spacing(
        self, first: int, second: int, third: int, fourth: int, /
    ) -> tuple[int, int, int, int]: ...

    def _spacing(self, *values: int) -> tuple[int, ...]:
        """Scale native pack/grid/style spacing using the same design units."""
        return tuple(self._px(value) for value in values)

    def set_theme(self, theme: str) -> None:
        """Restyle existing controls without changing dates, focus, or run state."""
        selected = theme if theme in THEMES else "midnight"
        self.theme_var.set(selected.title())
        self.colors = THEMES[selected]
        self._configure_styles()
        self.root.configure(bg=self.colors.background)
        for canvas in (self._main_canvas, self._setup_canvas):
            if canvas is not None:
                canvas.configure(background=self.colors.background)
        if self._setup_dialog is not None:
            self._setup_dialog.configure(bg=self.colors.background)
        for shift, panel in self._shift_panels.items():
            accent = (
                self.colors.night_accent if shift == "night" else self.colors.day_accent
            )
            for picker in (
                panel.single_picker,
                panel.range_start_picker,
                panel.range_end_picker,
            ):
                picker.configure(**self._calendar_kwargs(accent))
        for entry in (self.day_entry, self.night_entry):
            if entry is not None:
                color = (
                    self.colors.text_dim
                    if entry.get() == _PATH_PLACEHOLDER
                    else self.colors.text_main
                )
                entry.configure(foreground=color)
        self._style_printer_menu()
        self._style_theme_menu()
        self._style_help_dialog()
        self._style_titlebar(self.root)
        if self._setup_dialog is not None:
            self._style_titlebar(self._setup_dialog)

    def _style_titlebar(self, window: tk.Tk | tk.Toplevel) -> None:
        """Keep Windows captions dark independently of the system color theme."""
        if sys.platform != "win32":
            return
        try:
            window.update_idletasks()
            dlls = getattr(ctypes, "windll")
            get_parent = dlls.user32.GetParent
            get_parent.argtypes = [wintypes.HWND]
            get_parent.restype = wintypes.HWND
            handle = get_parent(window.winfo_id())
            setter = dlls.dwmapi.DwmSetWindowAttribute
            setter.argtypes = [
                wintypes.HWND,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            dark = wintypes.BOOL(1)
            setter(handle, 20, ctypes.byref(dark), ctypes.sizeof(dark))
            # Explicit caption/text colors cover Windows 11 even in OS light
            # mode. Older versions ignore unsupported attributes safely.
            for attribute, color in (
                (35, self.colors.header),
                (36, self.colors.text_main),
            ):
                rgb = color[1:]
                value = wintypes.DWORD(int(rgb[4:6] + rgb[2:4] + rgb[0:2], 16))
                setter(handle, attribute, ctypes.byref(value), ctypes.sizeof(value))
        except (AttributeError, OSError):
            logger.debug("Native dark caption unavailable", exc_info=True)

    def _configure_styles(self) -> None:
        """Configure ttk styles for the application."""
        # Base frame
        self.style.configure("TFrame", background=self.colors.background)
        self.style.configure(
            "TLabel",
            background=self.colors.background,
            foreground=self.colors.text_main,
            font=FONTS.main,
        )
        self.style.configure(_STYLE_CARD_FRAME, background=self.colors.surface)
        self.style.configure("Header.TFrame", background=self.colors.header)
        self.style.configure(
            "Brand.TLabel",
            background=self.colors.header,
            foreground=self.colors.text_main,
            font=FONTS.brand,
        )
        self.style.configure(
            "HeaderSub.TLabel",
            background=self.colors.header,
            foreground=self.colors.action,
            font=FONTS.main,
        )
        self.style.configure(
            "Section.TLabel",
            background=self.colors.background,
            foreground=self.colors.text_main,
            font=FONTS.section,
        )
        self.style.configure(
            "SetupValue.TLabel",
            background=self.colors.surface,
            foreground=self.colors.action,
            font=FONTS.main,
        )
        self.style.configure(
            "Card.TLabel",
            background=self.colors.surface,
            foreground=self.colors.text_main,
            font=FONTS.main,
        )
        self.style.configure(
            _STYLE_CARD_SUB_LABEL,
            background=self.colors.surface,
            foreground=self.colors.text_dim,
            font=FONTS.sub,
        )

        # Native card shells avoid LabelFrame's platform-specific title patches.
        for style_name, border_color in (
            ("SetupCard.TFrame", self.colors.border),
            ("NightCard.TFrame", self.colors.night_accent),
            ("DayCard.TFrame", self.colors.day_accent),
            ("Manifest.TFrame", self.colors.border),
            ("DialogCard.TFrame", self.colors.border),
        ):
            self.style.configure(
                style_name,
                background=self.colors.surface,
                bordercolor=border_color,
                borderwidth=1,
                relief="solid",
            )
        self.style.configure(
            "SetupTitle.TLabel",
            background=self.colors.surface,
            foreground=self.colors.text_main,
            font=FONTS.card_title,
        )
        self.style.configure(
            "NightTitle.TLabel",
            background=self.colors.night_surface,
            foreground=self.colors.night_accent,
            font=FONTS.card_title,
        )
        self.style.configure(
            "DayTitle.TLabel",
            background=self.colors.day_surface,
            foreground=self.colors.day_accent,
            font=FONTS.card_title,
        )
        self.style.configure("SetupHeader.TSeparator", background=self.colors.border)
        self.style.configure(
            "NightHeader.TSeparator", background=self.colors.night_accent
        )
        self.style.configure("DayHeader.TSeparator", background=self.colors.day_accent)
        self.style.configure("NightHeader.TFrame", background=self.colors.night_surface)
        self.style.configure("DayHeader.TFrame", background=self.colors.day_surface)

        # Inputs
        self.style.configure(
            "TEntry",
            fieldbackground=self.colors.input,
            foreground=self.colors.text_main,
            insertcolor=self.colors.text_main,
            selectbackground=self.colors.action,
            selectforeground=self.colors.action_text,
            bordercolor=self.colors.border,
            lightcolor=self.colors.border,
            darkcolor=self.colors.border,
            borderwidth=1,
            padding=self._spacing(8, 7),
        )
        self.style.map(
            "TEntry",
            fieldbackground=[("disabled", self.colors.border)],
            foreground=[("disabled", self.colors.text_dim)],
        )
        # One native field/arrow layout for theme, printer, and date choices.
        # DateEntry copies TCombobox, including this integrated arrow layout.
        for style_name, content in (
            ("TCombobox", "Combobox.textarea"),
            ("TMenubutton", "Menubutton.label"),
        ):
            self.style.layout(
                style_name,
                [
                    (
                        "Entry.field",
                        {
                            "sticky": "nswe",
                            "children": [
                                (
                                    "Menubutton.indicator",
                                    {"side": "right", "sticky": "ns"},
                                ),
                                (
                                    "Combobox.padding",
                                    {
                                        "sticky": "nswe",
                                        "children": [
                                            (content, {"sticky": "nswe"}),
                                        ],
                                    },
                                ),
                            ],
                        },
                    )
                ],
            )
            self.style.configure(
                style_name,
                fieldbackground=self.colors.input,
                background=self.colors.input,
                foreground=self.colors.text_main,
                font=FONTS.main,
                arrowcolor=self.colors.action,
                arrowsize=self._px(5),
                arrowpadding=self._px(10),
                selectbackground=self.colors.input,
                selectforeground=self.colors.text_main,
                bordercolor=self.colors.border,
                lightcolor=self.colors.input,
                darkcolor=self.colors.input,
                padding=self._spacing(12, 8),
            )
            self.style.map(
                style_name,
                fieldbackground=[
                    ("disabled", self.colors.surface),
                    ("active", self.colors.secondary),
                    ("readonly", self.colors.input),
                ],
                foreground=[("disabled", self.colors.text_dim)],
                arrowcolor=[("disabled", self.colors.text_dim)],
                background=[("active", self.colors.secondary)],
                selectbackground=[("readonly", self.colors.input)],
                selectforeground=[("readonly", self.colors.text_main)],
            )

        # Buttons
        self.style.configure(
            "TButton",
            background=self.colors.secondary,
            foreground=self.colors.text_main,
            bordercolor=self.colors.border,
            lightcolor=self.colors.secondary,
            darkcolor=self.colors.secondary,
            borderwidth=1,
            font=FONTS.bold,
            padding=self._spacing(14, 8),
        )
        self.style.map(
            "TButton",
            background=[
                ("disabled", self.colors.border),
                ("pressed", self.colors.background),
                ("active", self.colors.secondary),
            ],
            foreground=[("disabled", self.colors.text_dim)],
        )
        self.style.configure(
            _STYLE_TERTIARY_BUTTON,
            background=self.colors.background,
            foreground=self.colors.action,
            borderwidth=0,
            font=FONTS.sub,
            padding=self._spacing(6, 2),
        )
        self.style.map(
            _STYLE_TERTIARY_BUTTON,
            background=[
                ("pressed", self.colors.background),
                ("active", self.colors.background),
            ],
            foreground=[
                ("pressed", self.colors.text_main),
                ("active", self.colors.text_main),
            ],
        )
        self.style.configure(
            _STYLE_PRIMARY_BUTTON,
            background=self.colors.action,
            foreground=self.colors.action_text,
            bordercolor=self.colors.action,
            lightcolor=self.colors.action,
            darkcolor=self.colors.action,
            borderwidth=1,
            font=FONTS.button,
            padding=self._spacing(26, 16),
        )
        self.style.map(
            _STYLE_PRIMARY_BUTTON,
            background=[
                ("disabled", self.colors.border),
                ("pressed", self.colors.action_hover),
                ("active", self.colors.action_hover),
            ],
            foreground=[
                ("disabled", self.colors.text_dim),
                ("pressed", self.colors.action_text),
                ("active", self.colors.action_text),
            ],
        )
        self.style.configure(
            _STYLE_DANGER_BUTTON,
            background=self.colors.error,
            foreground=self.colors.background,
            bordercolor=self.colors.error,
            borderwidth=1,
            font=FONTS.button,
            padding=self._spacing(26, 16),
        )
        self.style.map(
            _STYLE_DANGER_BUTTON,
            background=[
                ("disabled", self.colors.border),
                ("pressed", "#E25D72"),
                ("active", "#E25D72"),
            ],
            foreground=[("disabled", self.colors.text_dim)],
        )
        for button_style, background in (
            ("Header.TButton", self.colors.header),
            ("Setup.TButton", self.colors.surface),
        ):
            self.style.configure(
                button_style,
                background=background,
                foreground=self.colors.action,
                bordercolor=self.colors.action,
                lightcolor=background,
                darkcolor=background,
                padding=self._spacing(18, 10),
            )
            self.style.map(
                button_style,
                background=[("active", self.colors.secondary)],
                foreground=[("disabled", self.colors.text_dim)],
            )
        self.style.configure(
            "TScrollbar",
            arrowsize=self._px(16),
            width=self._px(16),
            background=self.colors.secondary,
            troughcolor=self.colors.background,
            bordercolor=self.colors.background,
            arrowcolor=self.colors.text_dim,
            lightcolor=self.colors.secondary,
            darkcolor=self.colors.secondary,
        )
        self.style.map(
            "TScrollbar",
            background=[
                ("disabled", self.colors.secondary),
                ("active", self.colors.border),
            ],
            arrowcolor=[("disabled", self.colors.text_dim)],
        )
        for control in (_STYLE_CARD_CHECKBUTTON, _STYLE_CARD_RADIOBUTTON):
            self.style.configure(
                control,
                indicatorsize=self._px(18),
                indicatormargin=self._spacing(0, 2, 10, 2),
                upperbordercolor=self.colors.text_dim,
                lowerbordercolor=self.colors.text_dim,
            )
            self.style.map(
                control,
                indicatorbackground=[
                    (
                        "selected",
                        (
                            self.colors.input
                            if control == _STYLE_CARD_RADIOBUTTON
                            else self.colors.action
                        ),
                    ),
                    ("!selected", self.colors.input),
                ],
                indicatorforeground=[
                    (
                        "selected",
                        (
                            self.colors.action
                            if control == _STYLE_CARD_RADIOBUTTON
                            else self.colors.action_text
                        ),
                    )
                ],
                indicatorcolor=[("selected", self.colors.action)],
            )
        self.root.option_add("*TCombobox*Listbox.background", self.colors.input)
        self.root.option_add("*TCombobox*Listbox.foreground", self.colors.text_main)
        self.root.option_add("*TCombobox*Listbox.selectBackground", self.colors.action)
        self.root.option_add(
            "*TCombobox*Listbox.selectForeground", self.colors.action_text
        )

        # Progress bar
        self.style.configure(
            "Horizontal.TProgressbar",
            thickness=12,
            troughcolor=self.colors.input,
            background=self.colors.success,
            bordercolor=self.colors.border,
        )

        # Specialized Labels
        self.style.configure(
            _STYLE_HEADER_LABEL,
            font=FONTS.header,
            foreground=self.colors.text_main,
            background=self.colors.background,
        )
        self.style.configure(
            _STYLE_SUB_LABEL,
            font=FONTS.sub,
            foreground=self.colors.text_dim,
            background=self.colors.background,
        )
        self.style.configure(
            "ManifestTitle.TLabel",
            font=FONTS.card_title,
            foreground=self.colors.text_main,
            background=self.colors.surface,
        )
        # Semantic readiness states.  Colour reinforces the label text; it is
        # never the only signal, per the DESIGN.md validation-state rule.
        for count_style, count_color in (
            (_STYLE_COUNT_SELECTED_LABEL, self.colors.text_main),
            ("CountMuted.TLabel", self.colors.text_dim),
            ("CountError.TLabel", self.colors.error),
        ):
            self.style.configure(
                count_style,
                font=FONTS.bold,
                foreground=count_color,
                background=self.colors.surface,
            )

        # Status labels (success / error variants)
        self.style.configure(
            _STYLE_SUCCESS_LABEL,
            font=FONTS.sub,
            foreground=self.colors.success,
            background=self.colors.background,
        )
        self.style.configure(
            _STYLE_ERROR_LABEL,
            font=FONTS.sub,
            foreground=self.colors.error,
            background=self.colors.background,
        )

        # Checkbuttons
        self.style.configure(
            "TCheckbutton",
            background=self.colors.background,
            foreground=self.colors.text_main,
            font=FONTS.sub,
        )
        self.style.map(
            "TCheckbutton",
            background=[("active", self.colors.background)],
            foreground=[("disabled", self.colors.text_dim)],
        )
        self.style.configure(
            "TRadiobutton",
            background=self.colors.background,
            foreground=self.colors.text_main,
            font=FONTS.sub,
        )
        self.style.map(
            "TRadiobutton",
            background=[("active", self.colors.background)],
            foreground=[("disabled", self.colors.text_dim)],
        )
        self.style.configure(
            _STYLE_CARD_CHECKBUTTON,
            background=self.colors.surface,
            foreground=self.colors.text_main,
            font=FONTS.bold,
        )
        self.style.map(
            _STYLE_CARD_CHECKBUTTON,
            background=[("active", self.colors.surface)],
            foreground=[("disabled", self.colors.text_dim)],
        )
        self.style.configure(
            _STYLE_CARD_RADIOBUTTON,
            background=self.colors.surface,
            foreground=self.colors.text_main,
            font=FONTS.main,
        )
        self.style.map(
            _STYLE_CARD_RADIOBUTTON,
            background=[("active", self.colors.surface)],
            foreground=[("disabled", self.colors.text_dim)],
        )
        self.style.configure(
            "Card.TSeparator",
            background=self.colors.border,
        )

        # Clam otherwise relies on subtle platform defaults for keyboard focus.
        for style_name in (
            "TButton",
            "TEntry",
            "TCombobox",
            "TMenubutton",
            "TCheckbutton",
            "TRadiobutton",
            _STYLE_CARD_CHECKBUTTON,
            _STYLE_CARD_RADIOBUTTON,
        ):
            self.style.configure(
                style_name,
                focuscolor=self.colors.night_accent,
                focusthickness=2,
            )
            self.style.map(
                style_name,
                bordercolor=[("focus", self.colors.night_accent)],
                lightcolor=[("focus", self.colors.night_accent)],
                darkcolor=[("focus", self.colors.night_accent)],
            )

        # tkcalendar copies, rather than inherits, TCombobox at construction.
        # Refresh that copy as well when only our palette changes within clam.
        self.style.configure(
            "DateEntry", **cast(dict[str, Any], self.style.configure("TCombobox"))
        )
        self.style.map("DateEntry", **cast(dict[str, Any], self.style.map("TCombobox")))

    def _style_theme_menu(self) -> None:
        """Restyle the native choice menu, including already-created popups."""
        if self._theme_menu is not None:
            self._theme_menu.configure(
                background=self.colors.surface,
                foreground=self.colors.text_main,
                activebackground=self.colors.action,
                activeforeground=self.colors.action_text,
                selectcolor=self.colors.action,
                font=FONTS.main,
                borderwidth=1,
                activeborderwidth=self._px(6),
                relief="solid",
            )

    def _apply_icon(self) -> None:
        """Set the window icon from the bundled icon file, if present."""
        try:
            # PyInstaller bundles set sys._MEIPASS; otherwise use the repo root.
            base = getattr(sys, "_MEIPASS", None)
            if base is None:
                base = str(Path(__file__).resolve().parent.parent)
            ico_path = Path(base) / "icon.ico"
            png_path = Path(base) / "icon.png"
            if ico_path.exists():
                if sys.platform == "win32":
                    # The default also reaches owned windows and new Tk frames.
                    self.root.iconbitmap(default=str(ico_path))
                else:
                    self.root.iconbitmap(str(ico_path))
            elif png_path.exists():
                img = tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, img)
                # Keep a reference so the image isn't garbage-collected.
                self._icon_image = img
        except Exception as e:
            logger.debug(f"Could not set window icon: {e}")

    def _center_window(self) -> None:
        """Center the window inside the taskbar-safe primary work area."""
        try:
            self.root.update_idletasks()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            left, top, right, bottom = _get_work_area(self.root)
            x = left + max(
                0, (right - left - w - self._px(_WINDOW_FRAME_WIDTH_RESERVE)) // 2
            )
            y = top + max(
                0, (bottom - top - h - self._px(_WINDOW_FRAME_HEIGHT_RESERVE)) // 2
            )
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        except Exception as e:
            logger.debug(f"Could not center window: {e}")

    def _enumerate_printers(self) -> list[str]:
        """Return a sorted list of available printer names."""

        if win32print is None:
            return []

        try:
            local_printers = [p[2] for p in win32print.EnumPrinters(PRINTER_ENUM_LOCAL)]
            network_printers = [
                p[2] for p in win32print.EnumPrinters(PRINTER_ENUM_CONNECTIONS)
            ]
            return sorted(set(local_printers + network_printers))
        except Exception:
            logger.exception("Error enumerating printers")
            return []

    def refresh_printers(self) -> None:
        """Re-enumerate printers and update the dropdown."""

        if not self.printer_dropdown or not self.printer_var:
            return

        printers = self._enumerate_printers()
        self._cached_printers = printers
        try:
            menu = self.printer_dropdown["menu"]
            menu.delete(0, "end")
            for name in printers:
                menu.add_radiobutton(label=name, value=name, variable=self.printer_var)

            current = self.printer_var.get()
            if current and current in printers:
                self.printer_var.set(current)
            else:
                self.printer_var.set(DEFAULT_PRINTER_LABEL)
        except Exception:
            logger.exception("Could not update printer dropdown")
        self._update_printer_status(printers)
        self.refresh_setup_summary()
        self.refresh_manifest_preview()

    def _update_printer_status(self, printers: list[str]) -> None:
        """Show the result of the latest printer enumeration."""
        if self._printer_status_label is None:
            return
        count = len(printers)
        if count:
            noun = "printer" if count == 1 else "printers"
            self._printer_status_label.config(
                text=f"{count} {noun} available", style=_STYLE_CARD_SUB_LABEL
            )
            return
        message = "No printers found. Check connections, then Refresh."
        if win32print is None:
            message = "Printing requires Windows with pywin32 installed."
        self._printer_status_label.config(text=message, style=_STYLE_ERROR_LABEL)

    # ------------------------------------------------------------------
    # Widget creation
    # ------------------------------------------------------------------

    def _create_widgets(self) -> None:
        """Create all UI widgets."""
        # Reserve the action area before the scrolling form takes remaining space.
        self._create_footer(self.root)
        viewport = ttk.Frame(self.root)
        viewport.pack(fill="both", expand=True)
        self._main_canvas = tk.Canvas(
            viewport,
            background=self.colors.background,
            borderwidth=0,
            highlightthickness=0,
        )
        self._main_scrollbar = ttk.Scrollbar(
            viewport,
            orient="vertical",
            command=self._main_canvas.yview,
        )
        self._main_canvas.configure(yscrollcommand=self._main_scrollbar.set)
        self._main_canvas.pack(side="left", fill="both", expand=True)

        bg_canvas = ttk.Frame(self._main_canvas)
        self._main_content = bg_canvas
        self._main_content_window = self._main_canvas.create_window(
            (0, 0), window=bg_canvas, anchor="nw"
        )
        bg_canvas.bind(_CONFIGURE_EVENT, self._sync_main_scroll_region)
        self._main_canvas.bind(_CONFIGURE_EVENT, self._resize_main_content)
        self.root.bind("<MouseWheel>", self._scroll_main_content, add="+")
        self.root.bind(_FOCUS_IN_EVENT, self._ensure_focus_visible, add="+")

        self._create_header(bg_canvas)
        workspace = ttk.Frame(
            bg_canvas,
            padding=(self._px(24), self._gap(18), self._px(24), self._gap(8)),
        )
        workspace.pack(fill="both", expand=True)
        self._create_setup_card(workspace)
        self._create_run_heading(workspace)
        self._create_shift_selection_row(workspace)
        self._create_manifest_card(workspace)
        self.root.bind("<Alt-s>", lambda _event: self._show_setup_dialog())
        self.root.bind("<Alt-h>", lambda _event: self.show_help())
        self.refresh_manifest_preview()

    def _sync_main_scroll_region(self, _event: Any = None) -> None:
        """Keep the scroll range aligned with the rendered work surface."""
        if self._main_canvas is not None:
            self._main_canvas.configure(scrollregion=self._main_canvas.bbox("all"))

    def _resize_main_content(self, event: Any) -> None:
        """Match the work surface width to its viewport without clipping height."""
        if self._main_canvas is None or self._main_content_window is None:
            return
        self._main_canvas.itemconfigure(self._main_content_window, width=event.width)
        if (
            self._main_content is not None
            and self._main_content.winfo_reqheight() > event.height
        ):
            self._show_main_scrollbar()
        else:
            self._hide_main_scrollbar()

    def _show_main_scrollbar(self) -> None:
        """Expose native overflow navigation on constrained displays."""
        if self._main_scrollbar is not None:
            self._main_scrollbar.pack(side="right", fill="y")

    def _hide_main_scrollbar(self) -> None:
        """Keep the normal work surface free of unnecessary scroll chrome."""
        if self._main_scrollbar is not None:
            self._main_scrollbar.pack_forget()
        if self._main_canvas is not None:
            self._main_canvas.yview_moveto(0.0)

    def _scroll_main_content(self, event: Any) -> None:
        """Scroll overflowing content with the standard Windows mouse wheel."""
        if self._main_canvas is None or self._main_scrollbar is None:
            return
        if not self._main_scrollbar.winfo_ismapped():
            return
        delta = getattr(event, "delta", 0)
        if delta:
            units = int(-delta / 120)
            if units == 0:
                units = -1 if delta > 0 else 1
            self._main_canvas.yview_scroll(units, "units")

    def _ensure_focus_visible(self, event: Any) -> None:
        """Reveal a focused descendant when keyboard navigation reaches overflow."""
        if (
            self._main_canvas is None
            or self._main_content is None
            or self._main_scrollbar is None
            or not self._main_scrollbar.winfo_ismapped()
        ):
            return
        self._ensure_widget_visible(event, self._main_canvas, self._main_content)

    @staticmethod
    def _ensure_widget_visible(
        event: Any, canvas: tk.Canvas, content: ttk.Frame
    ) -> None:
        """Scroll one canvas just enough to reveal its focused descendant."""
        widget = getattr(event, "widget", None)
        try:
            if widget is None or not str(widget).startswith(str(content)):
                return
            content_height = content.winfo_reqheight()
            viewport_height = canvas.winfo_height()
            top = widget.winfo_rooty() - content.winfo_rooty()
            bottom = top + widget.winfo_height()
            visible_top = canvas.canvasy(0)
            visible_bottom = visible_top + viewport_height
            if top < visible_top:
                canvas.yview_moveto(max(0.0, top / content_height))
            elif bottom > visible_bottom:
                target = max(0, bottom - viewport_height)
                canvas.yview_moveto(min(1.0, target / content_height))
        except Exception as e:
            logger.debug(f"Could not reveal focused control: {e}")

    def _create_header(self, parent: ttk.Frame) -> None:
        """Give the workspace its identity, dark palette selection, and help."""
        header_row = ttk.Frame(
            parent, style="Header.TFrame", padding=(self._px(28), self._gap(18))
        )
        header_row.pack(fill="x")
        brand = ttk.Frame(header_row, style="Header.TFrame")
        brand.pack(side="left")
        ttk.Label(brand, text="ShiftPress", style="Brand.TLabel").pack(anchor="w")
        ttk.Label(
            brand, text="Schedules, ready for the next shift.", style="HeaderSub.TLabel"
        ).pack(anchor="w", pady=self._spacing(2, 0))
        version = _get_version()
        if version:
            ttk.Label(header_row, text=f"v{version}", style="HeaderSub.TLabel").pack(
                side="right", padx=self._spacing(24, 0)
            )
        self._help_button = ttk.Button(
            header_row,
            text="How to use",
            underline=0,
            style="Header.TButton",
            command=self.show_help,
        )
        self._help_button.pack(side="right", padx=self._spacing(16, 0))
        self._theme_picker = ttk.Menubutton(
            header_row,
            textvariable=self.theme_var,
            style="TMenubutton",
            width=9,
            direction="below",
            takefocus=True,
        )
        self._theme_menu = tk.Menu(self._theme_picker, tearoff=False)
        for theme in ("Midnight", "Rose"):
            self._theme_menu.add_radiobutton(
                label=theme,
                value=theme,
                variable=self.theme_var,
                command=lambda: self.set_theme(self.get_theme()),
            )
        self._theme_picker.configure(menu=self._theme_menu)
        self._style_theme_menu()
        self._theme_picker.pack(side="right")
        ttk.Label(header_row, text="Theme", style="HeaderSub.TLabel").pack(
            side="right", padx=self._spacing(16, 10)
        )

    def _create_run_heading(self, parent: ttk.Frame) -> None:
        """Place the task title next to the action that restores its defaults."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(self._gap(24), self._gap(14)))
        self._reset_btn = ttk.Button(
            row, text="Reset run", style=_STYLE_TERTIARY_BUTTON, command=self._reset_run
        )
        self._reset_btn.pack(side="right", anchor="s")
        ttk.Label(row, text="Prepare print run", style="Section.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            row,
            text="Choose exactly which schedules go to print.",
            style=_STYLE_SUB_LABEL,
        ).pack(anchor="w", pady=self._spacing(5, 0))

    def _create_titled_card(
        self,
        parent: ttk.Frame,
        title: str,
        style_prefix: str,
        padding: int,
    ) -> tuple[ttk.Frame, ttk.Frame]:
        """Create a native panel with a tinted, full-width title band."""
        shell = ttk.Frame(parent, style=f"{style_prefix}Card.TFrame", padding=1)
        title_row = ttk.Frame(
            shell,
            style=f"{style_prefix}Header.TFrame",
            padding=(self._px(18), self._gap(11)),
        )
        title_row.pack(fill="x")
        ttk.Label(
            title_row,
            text=title,
            style=f"{style_prefix}Title.TLabel",
        ).pack(side="left")
        card = ttk.Frame(
            shell,
            style=_STYLE_CARD_FRAME,
            padding=(self._px(padding), self._gap(padding)),
        )
        card.pack(fill="both", expand=True)
        return shell, card

    def _create_setup_card(self, parent: ttk.Frame) -> None:
        """Create a setup summary whose details open in a separate dialog."""
        card = ttk.Frame(
            parent,
            style="SetupCard.TFrame",
            padding=(self._px(18), self._gap(12), self._px(18), self._gap(18)),
        )
        card.pack(fill="x")
        ttk.Label(card, text="Print setup", style="SetupTitle.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=self._spacing(0, 12)
        )
        for column, (key, title) in enumerate(
            (
                ("night", "Night templates"),
                ("day", "Day templates"),
                ("printer", "Printer"),
            )
        ):
            card.grid_columnconfigure(column, weight=1, uniform="setup")
            group = ttk.Frame(card, style=_STYLE_CARD_FRAME)
            group.grid(row=1, column=column, sticky="nsew", padx=self._spacing(0, 18))
            ttk.Label(group, text=title, style="Card.TLabel").pack(
                anchor="w", pady=self._spacing(0, 6)
            )
            value = ttk.Label(
                group,
                text="Not configured",
                style="SetupValue.TLabel",
                wraplength=self._px(240),
                justify="left",
            )
            value.pack(anchor="w", fill="x")
            self._setup_values[key] = value
        self._setup_toggle_btn = ttk.Button(
            card,
            text="Setup…",
            style="Setup.TButton",
            underline=0,
            command=self._show_setup_dialog,
            width=12,
        )
        self._setup_toggle_btn.grid(row=1, column=3, padx=self._spacing(12, 0))

        self._create_setup_dialog()
        self.refresh_setup_summary()

    def _create_setup_dialog(self) -> None:
        """Build the withdrawn setup dialog without changing the main layout."""
        dialog = tk.Toplevel(self.root)
        self._setup_dialog = dialog
        dialog.withdraw()
        dialog.title("ShiftPress Setup")
        dialog.transient(self.root)
        dialog.configure(bg=self.colors.background)
        dialog.resizable(True, True)
        dialog.protocol("WM_DELETE_WINDOW", self._cancel_setup_dialog)
        dialog.bind("<Escape>", lambda _event: self._cancel_setup_dialog())

        viewport = ttk.Frame(dialog)
        viewport.pack(fill="both", expand=True)
        self._setup_canvas = tk.Canvas(
            viewport,
            background=self.colors.background,
            borderwidth=0,
            highlightthickness=0,
        )
        self._setup_scrollbar = ttk.Scrollbar(
            viewport,
            orient="vertical",
            command=self._setup_canvas.yview,
        )
        self._setup_canvas.configure(yscrollcommand=self._setup_scrollbar.set)
        self._setup_canvas.pack(side="left", fill="both", expand=True)
        canvas = ttk.Frame(self._setup_canvas, padding=self._px(24))
        self._setup_content = canvas
        self._setup_content_window = self._setup_canvas.create_window(
            (0, 0), window=canvas, anchor="nw"
        )
        canvas.bind(_CONFIGURE_EVENT, self._sync_setup_scroll_region)
        self._setup_canvas.bind(_CONFIGURE_EVENT, self._resize_setup_content)
        dialog.bind("<MouseWheel>", self._scroll_setup_content, add="+")
        dialog.bind(_FOCUS_IN_EVENT, self._ensure_setup_focus_visible, add="+")
        ttk.Label(canvas, text="Setup", style=_STYLE_HEADER_LABEL).pack(anchor="w")
        ttk.Label(
            canvas,
            text="Choose the template folders and printer used for print runs.",
            style=_STYLE_SUB_LABEL,
        ).pack(anchor="w", pady=self._spacing(4, 18))

        self._setup_details = ttk.Frame(
            canvas,
            style="DialogCard.TFrame",
            padding=self._px(18),
        )
        self._setup_details.pack(fill="both", expand=True)

        self.night_entry = self._create_path_row(
            self._setup_details, "Night Templates", ""
        )
        self.day_entry = self._create_path_row(self._setup_details, "Day Templates", "")

        _setup_placeholder(self.day_entry, _PATH_PLACEHOLDER)
        _setup_placeholder(self.night_entry, _PATH_PLACEHOLDER)
        self._create_printer_row(self._setup_details)
        action_row = ttk.Frame(canvas)
        action_row.pack(anchor="e", pady=self._spacing(18, 0))
        ttk.Button(
            action_row,
            text="Cancel",
            command=self._cancel_setup_dialog,
            width=14,
        ).pack(side="left", padx=self._spacing(0, 10))
        ttk.Button(
            action_row,
            text="Apply",
            command=self._apply_setup_dialog,
            width=14,
        ).pack(side="left")

    def _sync_setup_scroll_region(self, _event: Any = None) -> None:
        """Keep Setup's scroll range aligned with its rendered content."""
        if self._setup_canvas is not None:
            self._setup_canvas.configure(scrollregion=self._setup_canvas.bbox("all"))

    def _resize_setup_content(self, event: Any) -> None:
        """Fit Setup content to its viewport and reveal overflow only when needed."""
        if self._setup_canvas is None or self._setup_content_window is None:
            return
        self._setup_canvas.itemconfigure(self._setup_content_window, width=event.width)
        if (
            self._setup_content is not None
            and self._setup_content.winfo_reqheight() > event.height
        ):
            self._show_setup_scrollbar()
        else:
            self._hide_setup_scrollbar()

    def _show_setup_scrollbar(self) -> None:
        """Expose native overflow navigation in a constrained Setup dialog."""
        if self._setup_scrollbar is not None:
            self._setup_scrollbar.pack(side="right", fill="y")

    def _hide_setup_scrollbar(self) -> None:
        """Hide Setup overflow chrome when all controls already fit."""
        if self._setup_scrollbar is not None:
            self._setup_scrollbar.pack_forget()
        if self._setup_canvas is not None:
            self._setup_canvas.yview_moveto(0.0)

    def _scroll_setup_content(self, event: Any) -> None:
        """Scroll overflowing Setup content with the standard mouse wheel."""
        if self._setup_canvas is None or self._setup_scrollbar is None:
            return
        if not self._setup_scrollbar.winfo_ismapped():
            return
        delta = getattr(event, "delta", 0)
        if delta:
            units = int(-delta / 120)
            if units == 0:
                units = -1 if delta > 0 else 1
            self._setup_canvas.yview_scroll(units, "units")

    def _ensure_setup_focus_visible(self, event: Any) -> None:
        """Reveal the focused Setup control during keyboard navigation."""
        if (
            self._setup_canvas is None
            or self._setup_content is None
            or self._setup_scrollbar is None
            or not self._setup_scrollbar.winfo_ismapped()
        ):
            return
        self._ensure_widget_visible(
            event,
            self._setup_canvas,
            self._setup_content,
        )

    def _show_setup_dialog(self) -> None:
        """Show setup without expanding or displacing the print work surface."""
        if not self._inputs_enabled or self._setup_dialog is None:
            return
        dialog = self._setup_dialog
        self._setup_snapshot = (
            self.get_day_folder(),
            self.get_night_folder(),
            self.get_printer_name(),
        )
        dialog.deiconify()
        try:
            dialog.update_idletasks()
            if self._setup_content is None:
                return
            req_width = self._setup_content.winfo_reqwidth()
            req_height = self._setup_content.winfo_reqheight()
            left, top, right, bottom = _get_work_area(dialog)
            work_width = right - left
            work_height = bottom - top
            usable_width = max(520, work_width - _WINDOW_FRAME_WIDTH_RESERVE)
            usable_height = max(400, work_height - _WINDOW_FRAME_HEIGHT_RESERVE)
            width = min(max(720, req_width), usable_width)
            height = min(max(400, req_height), usable_height)
            centered_x = self.root.winfo_rootx() + max(
                0, (self.root.winfo_width() - width) // 2
            )
            x = min(max(left, centered_x), max(left, right - width))
            y = min(max(top, self.root.winfo_rooty() + 48), max(top, bottom - height))
            dialog.geometry(f"{width}x{height}+{x}+{y}")
            if req_height > height:
                self._show_setup_scrollbar()
            else:
                self._hide_setup_scrollbar()
            dialog.grab_set()
        except Exception as e:
            logger.debug(f"Could not position setup dialog: {e}")
        dialog.lift()
        # Ownership and the first lift can create a new Windows frame. Apply
        # DWM colors only after that frame exists, including on the first open.
        self._style_titlebar(dialog)
        dialog.focus_force()
        if self.night_entry is not None:
            self.night_entry.focus_set()

    def _apply_setup_dialog(self) -> None:
        """Keep the edited Setup values and return to the work surface."""
        self._setup_snapshot = None
        self._hide_setup_dialog()

    def _cancel_setup_dialog(self) -> None:
        """Restore the values present when Setup opened, then close it."""
        if self._setup_snapshot is not None:
            day_folder, night_folder, printer = self._setup_snapshot
            self.set_day_folder(day_folder)
            self.set_night_folder(night_folder)
            if self.printer_var is not None:
                self.printer_var.set(printer)
        self._setup_snapshot = None
        self._hide_setup_dialog()

    def _hide_setup_dialog(self) -> None:
        """Close setup back to its compact summary."""
        if self._setup_dialog is None:
            return
        self.refresh_setup_summary()
        try:
            self._setup_dialog.grab_release()
        except Exception as e:
            logger.debug(f"Could not release setup dialog: {e}")
        self._setup_dialog.withdraw()

    def refresh_setup_summary(self) -> None:
        """Identify configured template sources without exposing long paths."""
        day_folder = self.get_day_folder()
        night_folder = self.get_night_folder()
        printer = self.get_printer_name()
        printer_status = (
            printer if printer and printer != DEFAULT_PRINTER_LABEL else "Not selected"
        )
        day_status = self._folder_tail(day_folder)
        night_status = self._folder_tail(night_folder)
        for key, value in (
            ("night", night_status),
            ("day", day_status),
            ("printer", printer_status),
        ):
            if key in self._setup_values:
                self._setup_values[key].config(text=value)

    @staticmethod
    def _folder_tail(folder: str) -> str:
        """Return a compact, recognizable two-part folder identity."""
        if not isinstance(folder, str):
            return "Not configured"
        value = folder.strip().rstrip("/\\")
        if not value or value == _PATH_PLACEHOLDER:
            return "Not configured"
        parts = [part for part in re.split(r"[/\\]+", value) if part]
        if not parts:
            return value
        if parts[0].endswith(":"):
            tokens = parts if len(parts) <= 3 else [parts[0], parts[1], parts[-1]]
        elif value.startswith("\\\\") and len(parts) > 3:
            tokens = [f"{parts[0]}\\{parts[1]}", parts[2], parts[-1]]
        else:
            tokens = parts[-3:]
        compact = " › ".join(tokens)
        if len(compact) <= 52:
            return compact
        shortened = [
            token if len(token) <= 15 else f"{token[:12]}…" for token in tokens
        ]
        return " › ".join(shortened)

    def _create_shift_selection_row(self, parent: ttk.Frame) -> None:
        """Create equal-width Night and Day selection panels."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=self._spacing(0, 16))
        row.grid_columnconfigure(0, weight=1, uniform="shift")
        row.grid_columnconfigure(1, weight=1, uniform="shift")

        if DateEntry is None:
            self._dependency_error = (
                "Date selection is unavailable. Reinstall ShiftPress to restore "
                "tkcalendar."
            )
            ttk.Label(
                row,
                text=self._dependency_error,
                style=_STYLE_ERROR_LABEL,
                wraplength=self._px(760),
                justify="left",
            ).grid(row=0, column=0, columnspan=2, sticky="ew")
            logger.error("tkcalendar is not installed; date pickers unavailable")
            return

        self._create_shift_panel(
            row,
            shift_type="night",
            default_date=self._today,
            column=0,
        )
        self._create_shift_panel(
            row,
            shift_type="day",
            default_date=self._today + timedelta(days=1),
            column=1,
        )

    def _calendar_kwargs(self, select_color: str) -> dict[str, Any]:
        """Return dark-theme calendar colors keyed to one shift's identity.

        Args:
            select_color: The shift accent used to mark the selected day.

        Returns:
            Calendar option mapping to pass inline to ``DateEntry``.
        """
        return {
            "font": FONTS.main,
            "background": self.colors.background,
            "foreground": self.colors.text_main,
            "bordercolor": self.colors.border,
            "headersbackground": self.colors.background,
            "headersforeground": self.colors.text_dim,
            # Dark ink on the accent: near-white on amber measures 1.69:1.
            "selectbackground": select_color,
            "selectforeground": self.colors.background,
            "normalbackground": self.colors.surface,
            "normalforeground": self.colors.text_main,
            "weekendbackground": self.colors.surface,
            "weekendforeground": self.colors.text_dim,
            "othermonthbackground": self.colors.background,
            "othermonthforeground": self.colors.text_dim,
            "othermonthwebackground": self.colors.background,
            "othermonthweforeground": self.colors.text_dim,
            "disabledbackground": self.colors.surface,
            "disabledforeground": self.colors.border,
            "disableddaybackground": self.colors.surface,
            "disableddayforeground": self.colors.border,
            # ISO week numbers are noise for a print-run date choice.
            "showweeknumbers": False,
            "firstweekday": "sunday",
        }

    def _create_shift_panel(
        self,
        parent: ttk.Frame,
        shift_type: ShiftType,
        default_date: date,
        column: int,
    ) -> None:
        """Create one independent native shift selection panel."""
        date_entry_cls = cast(Any, DateEntry)
        label = shift_type.title()
        accent = (
            self.colors.night_accent
            if shift_type == "night"
            else self.colors.day_accent
        )
        calendar_kw = self._calendar_kwargs(accent)
        horizontal_padding = (0, 8) if column == 0 else (8, 0)
        shell, card = self._create_titled_card(parent, f"{label} schedule", label, 18)
        shell.grid(
            row=0, column=column, sticky="nsew", padx=self._spacing(*horizontal_padding)
        )

        enabled_var = tk.BooleanVar(value=True)
        mode_var = tk.StringVar(value="single")

        def sync_panel(selected: ShiftType = shift_type) -> None:
            self._sync_shift_panel_state(selected)

        include_check = ttk.Checkbutton(
            card,
            text=f"Include {label} schedule",
            variable=enabled_var,
            command=sync_panel,
            style=_STYLE_CARD_CHECKBUTTON,
        )
        include_check.pack(anchor="w", pady=(0, self._gap(18)))

        mode_row = ttk.Frame(card, style=_STYLE_CARD_FRAME)
        mode_row.pack(fill="x", pady=(0, self._gap(18)))
        single_radio = ttk.Radiobutton(
            mode_row,
            text="Single date",
            variable=mode_var,
            value="single",
            command=sync_panel,
            style=_STYLE_CARD_RADIOBUTTON,
        )
        single_radio.pack(side="left", padx=self._spacing(0, 24))
        range_radio = ttk.Radiobutton(
            mode_row,
            text="Date range",
            variable=mode_var,
            value="range",
            command=sync_panel,
            style=_STYLE_CARD_RADIOBUTTON,
        )
        range_radio.pack(side="left")

        date_stack = ttk.Frame(card, style=_STYLE_CARD_FRAME)
        date_stack.pack(fill="x")
        date_stack.grid_columnconfigure(0, weight=1)

        # Label-above-entry mirrors the range rows so both modes occupy the
        # same height and toggling never reflows the window.
        single_wrap = ttk.Frame(date_stack, style=_STYLE_CARD_FRAME)
        single_wrap.grid(row=0, column=0, sticky="ew")
        ttk.Label(single_wrap, text="Date", style=_STYLE_CARD_SUB_LABEL).pack(
            anchor="w", pady=self._spacing(0, 6)
        )
        single_picker = self._create_date_entry(
            date_entry_cls,
            single_wrap,
            calendar_kw=calendar_kw,
        )
        single_picker.pack(fill="x")
        single_picker.set_date(default_date)

        range_wrap = ttk.Frame(date_stack, style=_STYLE_CARD_FRAME)
        range_wrap.grid(row=0, column=0, sticky="ew")
        range_wrap.grid_columnconfigure(0, weight=1)
        range_wrap.grid_columnconfigure(1, weight=1)

        range_start_wrap = ttk.Frame(range_wrap, style=_STYLE_CARD_FRAME)
        range_start_wrap.grid(row=0, column=0, sticky="ew", padx=self._spacing(0, 6))
        ttk.Label(
            range_start_wrap, text="Start date", style=_STYLE_CARD_SUB_LABEL
        ).pack(anchor="w", pady=self._spacing(0, 6))
        range_start_picker = self._create_date_entry(
            date_entry_cls,
            range_start_wrap,
            calendar_kw=calendar_kw,
        )
        range_start_picker.pack(fill="x")
        range_start_picker.set_date(default_date)

        range_end_wrap = ttk.Frame(range_wrap, style=_STYLE_CARD_FRAME)
        range_end_wrap.grid(row=0, column=1, sticky="ew", padx=self._spacing(6, 0))
        ttk.Label(range_end_wrap, text="End date", style=_STYLE_CARD_SUB_LABEL).pack(
            anchor="w", pady=self._spacing(0, 6)
        )
        range_end_picker = self._create_date_entry(
            date_entry_cls,
            range_end_wrap,
            calendar_kw=calendar_kw,
        )
        range_end_picker.pack(fill="x")
        range_end_picker.set_date(default_date)

        count_label = ttk.Label(
            card,
            text="Selected · 1 document",
            style=_STYLE_COUNT_SELECTED_LABEL,
        )
        count_label.pack(anchor="w", pady=(self._gap(18), 0))

        panel = _ShiftPanelWidgets(
            enabled_var=enabled_var,
            mode_var=mode_var,
            include_check=include_check,
            single_radio=single_radio,
            range_radio=range_radio,
            single_picker=single_picker,
            range_start_picker=range_start_picker,
            range_end_picker=range_end_picker,
            single_wrap=single_wrap,
            range_wrap=range_wrap,
            count_label=count_label,
        )
        self._shift_panels[shift_type] = panel

        single_picker.bind(
            _DATE_ENTRY_SELECTED_EVENT,
            lambda _event, selected=shift_type: self._on_shift_date_selected(selected),
        )
        range_start_picker.bind(
            _DATE_ENTRY_SELECTED_EVENT,
            lambda _event, selected=shift_type: self._on_range_start_selected(selected),
        )
        range_end_picker.bind(
            _DATE_ENTRY_SELECTED_EVENT,
            lambda _event, selected=shift_type: self._on_shift_date_selected(selected),
        )
        for picker in (single_picker, range_start_picker, range_end_picker):
            self._bind_pick_only(picker)
        self._sync_shift_panel_state(shift_type)

    def _bind_pick_only(self, picker: Any) -> None:
        """Open the calendar on click or key, since the field is not typable.

        Args:
            picker: The ``DateEntry`` to make pick-only.
        """

        def open_calendar(_event: Any = None) -> str:
            try:
                if "disabled" not in picker.state():
                    picker.drop_down()
            except Exception as e:
                logger.debug(f"Could not open calendar: {e}")
            return "break"

        # Replace tkcalendar's arrow-click handler: adding ours would toggle
        # the popup twice when the arrow itself is clicked.
        for sequence in ("<Button-1>", "<Down>", "<space>", "<Return>"):
            picker.bind(sequence, open_calendar)

    def _on_shift_date_selected(self, shift_type: ShiftType) -> None:
        """Refresh visible intent after a shift date changes."""
        del shift_type
        self.refresh_manifest_preview()

    def _reset_run(self) -> None:
        """Restore the common Night-today and Day-tomorrow print scope."""
        if not self._inputs_enabled:
            return
        defaults: dict[ShiftType, date] = {
            "night": self._today,
            "day": self._today + timedelta(days=1),
        }
        for shift_type, panel in self._shift_panels.items():
            default_date = defaults[shift_type]
            panel.enabled_var.set(True)
            panel.mode_var.set("single")
            panel.single_picker.set_date(default_date)
            panel.range_start_picker.set_date(default_date)
            panel.range_end_picker.set_date(default_date)
            self._sync_shift_panel_state(shift_type, refresh=False)
        self.refresh_manifest_preview()

    def _on_range_start_selected(self, shift_type: ShiftType) -> None:
        """Keep one shift's range end on or after its range start."""
        panel = self._shift_panels[shift_type]
        try:
            start_dt = panel.range_start_picker.get_date()
            end_dt = panel.range_end_picker.get_date()
            if end_dt < start_dt:
                panel.range_end_picker.set_date(start_dt)
        except Exception as e:
            logger.debug(f"Error syncing {shift_type} date pickers: {e}")
        self.refresh_manifest_preview()

    def _sync_shift_panel_state(
        self, shift_type: ShiftType, refresh: bool = True
    ) -> None:
        """Apply include/mode state to one panel without changing its values."""
        panel = self._shift_panels[shift_type]
        enabled = bool(panel.enabled_var.get()) and self._inputs_enabled
        state: Literal["normal", "disabled"] = "normal" if enabled else "disabled"
        # Dates are pick-only: a typed value can be silently wrong (mm/dd read
        # as dd/mm), and unparseable text makes tkcalendar report the previous
        # date while the box shows something else.
        picker_state: Literal["readonly", "disabled"] = (
            "readonly" if enabled else "disabled"
        )

        for widget in (panel.single_radio, panel.range_radio):
            widget.config(state=state)
        for picker in (
            panel.single_picker,
            panel.range_start_picker,
            panel.range_end_picker,
        ):
            picker.config(state=picker_state)

        if panel.mode_var.get() == "range":
            panel.single_wrap.grid_remove()
            panel.range_wrap.grid()
        else:
            panel.range_wrap.grid_remove()
            panel.single_wrap.grid()

        if refresh and len(self._shift_panels) == 2:
            self.refresh_manifest_preview()

    def _create_manifest_card(self, parent: ttk.Frame) -> None:
        """Create the exact preflight-neutral print manifest summary."""
        card = ttk.Frame(
            parent, style="Manifest.TFrame", padding=(self._px(18), self._gap(18))
        )
        self._manifest_card = card
        card.pack(fill="x", pady=self._spacing(0, 16))
        card.columnconfigure(0, weight=2)
        card.columnconfigure(1, weight=1)
        self.manifest_title_label = ttk.Label(
            card,
            text="Print scope: No schedules selected",
            style="ManifestTitle.TLabel",
        )
        self.manifest_title_label.grid(
            row=0, column=0, sticky="w", pady=self._spacing(0, 8)
        )
        self.manifest_label = ttk.Label(
            card,
            text="Select schedules to see the print scope",
            style=_STYLE_CARD_SUB_LABEL,
            justify="left",
            anchor="w",
            wraplength=self._px(620),
        )
        self.manifest_label.grid(row=1, column=0, sticky="ew")
        self._manifest_printer_label = ttk.Label(
            card,
            text="Printer\nChoose a printer",
            style="Card.TLabel",
            justify="left",
            wraplength=self._px(280),
        )
        self._manifest_printer_label.grid(
            row=0, column=1, rowspan=2, sticky="e", padx=self._spacing(24, 0)
        )

    def _create_date_entry(
        self,
        date_entry_cls: Any,
        parent: Any,
        calendar_kw: dict[str, Any],
    ) -> Any:
        """Create a themed tkcalendar DateEntry.

        tkcalendar versions differ in supported keyword args; fall back
        gracefully through progressively simpler constructor calls.

        Args:
            date_entry_cls: The ``DateEntry`` class from tkcalendar.
            parent: Parent widget to contain the date entry.
            calendar_kw: Dict of calendar styling keyword arguments.

        Returns:
            A ``DateEntry`` widget instance.
        """

        # Inline options are the working path: tkcalendar accepts an unknown
        # calendar_kw= without raising, so that form silently drops every
        # colour and leaves the popup in its default light theme.
        try:
            return date_entry_cls(
                parent,
                style="DateEntry",
                date_pattern=_DATE_PATTERN,
                **calendar_kw,
            )
        except TypeError as e:
            logger.debug(f"DateEntry inline calendar kwargs not supported: {e}")

        # Builds that reject an inline option may accept the nested form.
        try:
            return date_entry_cls(
                parent,
                style="DateEntry",
                date_pattern=_DATE_PATTERN,
                calendar_kw=calendar_kw,
            )
        except TypeError as e:
            logger.debug(f"DateEntry calendar_kw not supported: {e}")
            return date_entry_cls(
                parent,
                style="DateEntry",
                date_pattern=_DATE_PATTERN,
            )

    def _apply_content_sizing(self) -> None:
        """Size the window from rendered content so it cannot clip itself.

        Deriving both the initial geometry and the minimum size from Tk's
        computed requirement keeps the primary action visible under any
        Windows text-scaling setting, which a hardcoded height cannot.
        Both date modes are the same height by construction, so the
        requirement does not change after launch.
        """

        try:
            self.root.update_idletasks()
            if self._main_content is None:
                return
            req_w = self._main_content.winfo_reqwidth()
            footer_height = (
                self._footer_frame.winfo_reqheight() if self._footer_frame else 0
            )
            req_h = self._main_content.winfo_reqheight() + footer_height
            left, top, right, bottom = _get_work_area(self.root)
            work_width = right - left
            work_height = bottom - top

            target_w = min(
                max(self._px(WINDOW_WIDTH), req_w),
                max(
                    AUTO_RESIZE_MIN_WIDTH,
                    work_width - self._px(_WINDOW_FRAME_WIDTH_RESERVE),
                ),
            )
            usable_h = max(
                AUTO_RESIZE_MIN_HEIGHT,
                work_height - self._px(_WINDOW_FRAME_HEIGHT_RESERVE),
            )
            target_h = min(max(AUTO_RESIZE_MIN_HEIGHT, req_h), usable_h)

            self.root.minsize(min(target_w, self._px(900)), AUTO_RESIZE_MIN_HEIGHT)
            self.root.geometry(f"{target_w}x{target_h}")
            if req_h > target_h:
                self._show_main_scrollbar()
            else:
                self._hide_main_scrollbar()
        except Exception as e:
            logger.debug(f"Content sizing skipped: {e}")

    def _create_printer_row(self, parent: ttk.Frame | ttk.LabelFrame) -> None:
        """Create the printer selection row."""
        output_row = ttk.Frame(parent, style=_STYLE_CARD_FRAME)
        output_row.pack(fill="x", pady=self._spacing(8, 0))
        ttk.Label(output_row, text="Printer", style=_STYLE_CARD_SUB_LABEL).pack(
            anchor="w", pady=self._spacing(0, 8)
        )

        if win32print is None:
            logger.error("win32print is not available; printer enumeration disabled")

        all_printers = self._enumerate_printers()
        self._cached_printers = all_printers
        logger.debug(f"Found {len(all_printers)} printers")

        self.printer_var = tk.StringVar(value=DEFAULT_PRINTER_LABEL)
        try:
            self.printer_var.trace_add("write", self._on_printer_changed)
        except Exception as e:
            logger.debug(f"Could not watch printer selection: {e}")
        printer_row = ttk.Frame(output_row, style=_STYLE_CARD_FRAME)
        printer_row.pack(fill="x")

        self.printer_dropdown = ttk.OptionMenu(
            printer_row, self.printer_var, DEFAULT_PRINTER_LABEL, *all_printers
        )
        self.printer_dropdown.pack(
            side="left", fill="x", expand=True, padx=self._spacing(0, 10)
        )

        self._style_printer_menu()

        self._refresh_btn = ttk.Button(
            printer_row,
            text="Refresh",
            width=10,
            command=self.refresh_printers,
            cursor="hand2",
        )
        self._refresh_btn.pack(side="right")

        self._printer_status_label = ttk.Label(
            output_row,
            text="",
            style=_STYLE_CARD_SUB_LABEL,
            wraplength=self._px(640),
            justify="left",
        )
        self._printer_status_label.pack(anchor="w", pady=self._spacing(6, 0))
        self._update_printer_status(all_printers)

    def _style_printer_menu(self) -> None:
        """Keep the native printer popup in the selected dark palette."""
        if self.printer_dropdown is None:
            return
        try:
            self.printer_dropdown["menu"].configure(
                bg=self.colors.surface,
                fg=self.colors.text_main,
                activebackground=self.colors.action,
                activeforeground=self.colors.action_text,
                selectcolor=self.colors.action,
                font=FONTS.main,
                activeborderwidth=self._px(6),
                borderwidth=1,
                relief="solid",
            )
        except tk.TclError as error:
            logger.debug("Could not style printer dropdown menu: %s", error)

    def _on_printer_changed(self, *_args: object) -> None:
        """Refresh setup and manifest copy after the printer changes."""
        self.refresh_setup_summary()
        self.refresh_manifest_preview()

    def _create_footer(self, parent: tk.Misc) -> None:
        """Create the action footer (status, progress, button)."""
        footer = ttk.Frame(parent, padding=self._spacing(24, 12, 24, 16))
        self._footer_frame = footer
        footer.pack(side="bottom", fill="x")
        footer.grid_columnconfigure(0, weight=1)

        status_wrap = ttk.Frame(footer)
        status_wrap.grid(row=0, column=0, sticky="ew", padx=self._spacing(0, 24))
        self.status_label = ttk.Label(
            status_wrap,
            text="Complete Setup to prepare a print scope",
            style=_STYLE_SUB_LABEL,
            wraplength=self._px(620),
            justify="left",
        )
        self.status_label.pack(side="left")

        open_logs_btn = ttk.Button(
            status_wrap,
            text="Open logs",
            style=_STYLE_TERTIARY_BUTTON,
            command=self.open_logs_folder,
            cursor="hand2",
        )
        self._logs_btn = open_logs_btn

        progress_row = ttk.Frame(footer)
        self._progress_row = progress_row
        progress_row.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=self._spacing(0, 24),
            pady=self._spacing(10, 0),
        )
        progress_row.grid_remove()

        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(
            progress_row,
            variable=self.progress_var,
            maximum=PROGRESS_MAX,
            style="Horizontal.TProgressbar",
        )
        self.progress.pack(
            side="left", fill="x", expand=True, padx=self._spacing(0, 10)
        )

        self._progress_pct = ttk.Label(
            progress_row,
            text="0%",
            style=_STYLE_SUB_LABEL,
            width=5,
            anchor="e",
        )
        self._progress_pct.pack(side="right")

        self.print_btn = ttk.Button(
            footer,
            text=_PRINT_BUTTON_LABEL,
            underline=0,
            style=_STYLE_PRIMARY_BUTTON,
            width=26,
            cursor="hand2",
        )
        self.print_btn.grid(row=0, column=1, rowspan=2, sticky="nsew")

    def _create_path_row(
        self, parent: ttk.Frame | ttk.LabelFrame, label: str, default_val: str
    ) -> ttk.Entry:
        """
        Create a path input row with browse button.

        Args:
            parent: Parent widget
            label: Label text
            default_val: Default path value

        Returns:
            The entry widget
        """
        wrap = ttk.Frame(parent, style=_STYLE_CARD_FRAME)
        wrap.pack(fill="x", pady=self._px(8))
        ttk.Label(wrap, text=label, style=_STYLE_CARD_SUB_LABEL).pack(
            anchor="w", pady=self._spacing(0, 6)
        )

        row = ttk.Frame(wrap, style=_STYLE_CARD_FRAME)
        row.pack(fill="x")

        entry = ttk.Entry(row)
        entry.insert(0, default_val)
        entry.pack(side="left", fill="x", expand=True, padx=self._spacing(0, 10))

        browse_button = ttk.Button(
            row,
            text="Browse",
            width=10,
            command=lambda: self._browse_folder(entry),
            cursor="hand2",
        )
        browse_button.pack(side="right")
        self._browse_buttons.append(browse_button)

        return entry

    def _browse_folder(self, entry: ttk.Entry) -> None:
        """
        Open folder browser dialog.

        Args:
            entry: Entry widget to update with selected path
        """
        current = entry.get().strip()
        # Ignore placeholder text when determining initial directory.
        if current == _PATH_PLACEHOLDER:
            current = ""
        initial = current if current and os.path.isdir(current) else None
        path = filedialog.askdirectory(initialdir=initial)
        if path:
            self._set_folder_entry(entry, path)
            logger.debug(f"Selected folder: {path}")
            self.refresh_setup_summary()
            self.refresh_manifest_preview()

    # ------------------------------------------------------------------
    # Public getters
    # ------------------------------------------------------------------

    def _set_folder_entry(self, entry: Optional[ttk.Entry], path: str) -> None:
        """Write one path entry, honoring the placeholder and colour contract.

        Args:
            entry: The target entry widget, or ``None`` if not yet built.
            path: The folder path to show.  Empty restores the placeholder.
        """
        if entry is None:
            return
        value = (path or "").strip()
        entry.delete(0, tk.END)
        if value:
            entry.config(foreground=self.colors.text_main)
            entry.insert(0, value)
        else:
            entry.config(foreground=self.colors.text_dim)
            entry.insert(0, _PATH_PLACEHOLDER)

    def set_day_folder(self, path: str) -> None:
        """Set the Day templates folder shown in Setup."""
        self._set_folder_entry(self.day_entry, path)

    def set_night_folder(self, path: str) -> None:
        """Set the Night templates folder shown in Setup."""
        self._set_folder_entry(self.night_entry, path)

    def get_day_folder(self) -> str:
        """Get the day folder path."""
        val = self.day_entry.get() if self.day_entry else ""
        return "" if val == _PATH_PLACEHOLDER else val

    def get_night_folder(self) -> str:
        """Get the night folder path."""
        val = self.night_entry.get() if self.night_entry else ""
        return "" if val == _PATH_PLACEHOLDER else val

    def get_printer_name(self) -> str:
        """Get the selected printer name."""
        return self.printer_var.get() if self.printer_var else ""

    def get_available_printers(self) -> list[str]:
        """Return the available printers list (best-effort)."""
        return list(self._cached_printers)

    def _get_picker_date(self, picker: Any, label: str) -> Optional[date]:
        """Read one DateEntry without letting parse failures escape the UI."""
        try:
            selected = picker.get_date()
            return selected if isinstance(selected, date) else None
        except (ValueError, AttributeError):
            logger.warning(f"Could not parse {label} from picker")
            return None

    def _get_shift_selection(self, shift_type: ShiftType) -> ShiftSelection:
        """Collect one panel's state without reading another shift."""
        panel = self._shift_panels[shift_type]
        mode_value = panel.mode_var.get()
        mode: DateMode = "range" if mode_value == "range" else "single"
        if mode == "single":
            start_date = self._get_picker_date(
                panel.single_picker, f"{shift_type} date"
            )
        else:
            start_date = self._get_picker_date(
                panel.range_start_picker, f"{shift_type} range start"
            )
        end_date = self._get_picker_date(
            panel.range_end_picker, f"{shift_type} range end"
        )
        folder = (
            self.get_night_folder() if shift_type == "night" else self.get_day_folder()
        )
        return ShiftSelection(
            shift_type=shift_type,
            enabled=bool(panel.enabled_var.get()),
            mode=mode,
            start_date=start_date,
            end_date=end_date,
            folder=folder,
        )

    def get_shift_selections(self) -> tuple[ShiftSelection, ShiftSelection]:
        """Return independent Night and Day selections in stable display order."""
        return (
            self._get_shift_selection("night"),
            self._get_shift_selection("day"),
        )

    def _format_selection_summary(
        self, selection: ShiftSelection, job_count: int
    ) -> str:
        """Format one enabled shift's active date scope and document count."""
        start_date, end_date = selection.active_range()
        if start_date == end_date:
            scope = start_date.strftime("%m/%d/%Y")
        else:
            scope = (
                f"{start_date.strftime('%m/%d/%Y')} – "
                f"{end_date.strftime('%m/%d/%Y')}"
            )
        noun = "document" if job_count == 1 else "documents"
        return f"{selection.shift_type.title()} — {scope} — {job_count} {noun}"

    @staticmethod
    def _document_noun(count: int) -> str:
        """Return the correctly pluralized document noun for *count*."""
        return "document" if count == 1 else "documents"

    @staticmethod
    def _print_button_text(count: int) -> str:
        """Return the count-bearing label for the primary action."""
        if count == 0:
            return _PRINT_BUTTON_LABEL
        if count == 1:
            return "Print 1 schedule"
        return f"Print {count} schedules"

    def _set_count(self, shift_type: ShiftType, text: str, style: str) -> None:
        """Set one panel's count line text and readiness style together."""
        self._shift_panels[shift_type].count_label.config(text=text, style=style)

    def _refresh_shift_counts(
        self,
        selections: tuple[ShiftSelection, ShiftSelection],
        errors: dict[ShiftType, Optional[str]],
    ) -> None:
        """Update each panel independently so one bad shift cannot accuse the other."""
        for selection in selections:
            shift_type = selection.shift_type
            if not selection.enabled:
                self._set_count(shift_type, "Not included", "CountMuted.TLabel")
            elif errors[shift_type]:
                self._set_count(
                    shift_type,
                    f"Check {shift_type.title()} date selection",
                    "CountError.TLabel",
                )
            else:
                count = len(build_print_manifest((selection,)))
                self._set_count(
                    shift_type,
                    f"Selected · {count} {self._document_noun(count)}",
                    _STYLE_COUNT_SELECTED_LABEL,
                )

    def _describe_manifest(
        self,
        selections: tuple[ShiftSelection, ShiftSelection],
        manifest: tuple[PrintJob, ...],
    ) -> tuple[str, list[str]]:
        """Return the manifest title and one numbered line per included shift."""
        if not manifest:
            return "Print scope: No schedules selected", []

        total = len(manifest)
        noun = "schedule" if total == 1 else "schedules"
        title = f"Print scope: {total} {noun} selected"
        lines: list[str] = []
        row_number = 1
        for selection in selections:
            if not selection.enabled:
                continue
            count = sum(1 for job in manifest if job.shift_type == selection.shift_type)
            lines.append(
                f"{row_number}. {self._format_selection_summary(selection, count)}"
            )
            row_number += 1
        return title, lines

    def _show_dependency_manifest_error(self) -> bool:
        """Render the missing-date-control state and report whether it handled view."""
        if len(self._shift_panels) == 2:
            return False
        if not self._dependency_error:
            return True
        if self.manifest_title_label is not None:
            self.manifest_title_label.config(
                text="Print scope: Date selection unavailable"
            )
        if self.manifest_label is not None:
            self.manifest_label.config(text=self._dependency_error)
        if self.print_btn is not None:
            self.print_btn.config(text=_PRINT_BUTTON_LABEL)
            self.print_btn.config(state="disabled")
        return True

    def _manifest_preview_data(
        self,
        selections: tuple[ShiftSelection, ShiftSelection],
        errors: dict[ShiftType, Optional[str]],
    ) -> tuple[tuple[PrintJob, ...], str, list[str], tuple[ShiftSelection, ...]]:
        """Build the neutral preview data before local blockers are applied."""
        invalid = tuple(
            selection for selection in selections if errors[selection.shift_type]
        )
        if invalid:
            names = " and ".join(selection.shift_type.title() for selection in invalid)
            title = f"Print scope: Check {names} date selection"
            lines = [errors[selection.shift_type] or "" for selection in invalid]
            return (), title, lines, invalid

        manifest = build_print_manifest(selections)
        title, lines = self._describe_manifest(selections, manifest)
        return manifest, title, lines, invalid

    def _render_manifest_preview(
        self,
        title: str,
        lines: list[str],
        manifest_count: int,
        blocker: Optional[str],
        update_status: bool,
    ) -> None:
        """Apply prepared manifest copy and action state to optional widgets."""
        if self.manifest_title_label is not None:
            self.manifest_title_label.config(text=title)
        if self.manifest_label is not None:
            self.manifest_label.config(text="\n".join(lines))
        if update_status and self.status_label is not None:
            status_text = (
                blocker or "Scope selected. Preflight runs when you select Print."
            )
            status_style = _STYLE_ERROR_LABEL if blocker else _STYLE_SUB_LABEL
            self.status_label.config(text=status_text, style=status_style)
        if self.print_btn is not None:
            self.print_btn.config(text=self._print_button_text(manifest_count))
            state: Literal["normal", "disabled"] = (
                "normal" if blocker is None and self._inputs_enabled else "disabled"
            )
            self.print_btn.config(state=state)

    def refresh_manifest_preview(self, update_status: bool = True) -> None:
        """Refresh the preflight-neutral manifest copy and count-aware action."""
        if self._show_dependency_manifest_error():
            return

        selections = self.get_shift_selections()
        errors: dict[ShiftType, Optional[str]] = {
            selection.shift_type: selection.validate() for selection in selections
        }
        self._refresh_shift_counts(selections, errors)
        manifest, title, lines, invalid = self._manifest_preview_data(
            selections, errors
        )

        printer = self.get_printer_name()
        printer_label = (
            printer
            if printer and printer != DEFAULT_PRINTER_LABEL
            else "Choose a printer"
        )
        if self._manifest_printer_label is not None:
            self._manifest_printer_label.config(text=f"Printer\n{printer_label}")
        blocker = _manifest_blocker(selections, invalid, manifest, printer_label)
        if blocker:
            lines.append(f"Cannot print: {blocker}")
        self._render_manifest_preview(
            title, lines, len(manifest), blocker, update_status
        )

    def set_processing_mode(self, processing: bool) -> None:
        """Switch the primary action between print and cancellation states."""
        if self.print_btn is None:
            return
        if processing:
            if self._progress_row is not None:
                self._progress_row.grid()
            self.print_btn.config(text="Cancel", style=_STYLE_DANGER_BUTTON)
        else:
            self.print_btn.config(style=_STYLE_PRIMARY_BUTTON)
            self.refresh_manifest_preview(update_status=False)

    # ------------------------------------------------------------------
    # Public setters / commands
    # ------------------------------------------------------------------

    def set_start_command(
        self,
        command: Callable[[], None],
        cancel_command: Optional[Callable[[], None]] = None,
    ) -> None:
        """Set the command for the print button and keyboard shortcuts.

        Binds ``Enter`` to *command* (start) and ``Escape`` to
        *cancel_command* (stop) if provided.

        Args:
            command: Function to call when button is clicked or Enter is pressed.
            cancel_command: Optional function to call when Escape is pressed.
        """
        if self.print_btn:
            self.print_btn.config(command=command)
            # Allow Enter key to trigger execution only when the button has focus.
            self.print_btn.bind("<Return>", lambda _event: command())
            self.root.bind("<Alt-p>", lambda _event: command())
        if cancel_command is not None:
            self.root.bind("<Escape>", lambda _event: cancel_command())

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable all input widgets during processing.

        Args:
            enabled: True to enable inputs, False to disable.
        """
        self._inputs_enabled = enabled
        state: Literal["normal", "disabled"] = "normal" if enabled else "disabled"
        for widget in (self.day_entry, self.night_entry):
            self._set_widget_state(widget, state, "entry")
        for button in self._browse_buttons:
            self._set_widget_state(button, state, "Browse button")
        self._set_widget_state(self.printer_dropdown, state, "printer dropdown")
        self._set_widget_state(self._refresh_btn, state, "refresh button")
        self._set_widget_state(self._setup_toggle_btn, state, "setup toggle")
        self._set_widget_state(self._reset_btn, state, "reset run")
        for shift_type, panel in self._shift_panels.items():
            self._set_shift_panel_enabled(shift_type, panel, state)

    @staticmethod
    def _set_widget_state(
        widget: Any,
        state: Literal["normal", "disabled"],
        description: str,
    ) -> None:
        """Set one optional widget state without interrupting the UI lock pass."""
        if widget is None:
            return
        try:
            widget.config(state=state)
        except Exception as e:
            logger.debug(f"Could not set {description} state: {e}")

    def _set_shift_panel_enabled(
        self,
        shift_type: ShiftType,
        panel: _ShiftPanelWidgets,
        state: Literal["normal", "disabled"],
    ) -> None:
        """Set one shift panel's processing lock state."""
        try:
            panel.include_check.config(state=state)
            self._sync_shift_panel_state(shift_type, refresh=False)
        except Exception as e:
            logger.debug(f"Could not set {shift_type} panel state: {e}")

    def set_print_button_state(self, state: Literal["normal", "disabled"]) -> None:
        """
        Set the print button state.

        Args:
            state: Either "normal" or "disabled"
        """
        if self.print_btn:
            self.print_btn.config(state=state)

    def update_status(
        self,
        message: str,
        progress: float,
        level: Optional[Literal["info", "success", "error"]] = None,
    ) -> None:
        """
        Update the status label and progress bar.

        Args:
            message: Status message to display
            progress: Progress value (0-100)
            level: Explicit style level.  When ``None`` (default) the style
                is inferred from the message text for backward compatibility.
        """
        if self._progress_row is not None:
            self._progress_row.grid()
        if self.status_label:
            style = _status_style(message, level)
            self.status_label.config(text=message, style=style)
            self._set_logs_button_visibility(style)
        if self.progress_var:
            self.progress_var.set(progress)
        if self._progress_pct:
            self._progress_pct.config(text=f"{int(progress)}%")

    def _set_logs_button_visibility(self, status_style: str) -> None:
        """Show the logs shortcut only while an error status is visible."""
        if self._logs_btn is None:
            return
        if status_style == _STYLE_ERROR_LABEL:
            self._logs_btn.pack(side="left", padx=self._spacing(12, 0))
            return
        self._logs_btn.pack_forget()

    # ------------------------------------------------------------------
    # Dialogs
    # ------------------------------------------------------------------

    def show_error(self, title: str, message: str) -> None:
        """Show an error message box.

        Args:
            title: Dialog window title.
            message: Message body to display.
        """
        logger.error(f"{title}: {message}")
        messagebox.showerror(title, message)

    def show_warning(self, title: str, message: str) -> None:
        """Show a warning message box.

        Args:
            title: Dialog window title.
            message: Message body to display.
        """
        logger.warning(f"{title}: {message}")
        messagebox.showwarning(title, message)

    def show_info(self, title: str, message: str) -> None:
        """Show an info message box.

        Args:
            title: Dialog window title.
            message: Message body to display.
        """
        logger.info(f"{title}: {message}")
        messagebox.showinfo(title, message)

    def show_help(self) -> None:
        """Open a themed, non-modal reference without losing the current run."""
        if self._help_dialog is None:
            self._create_help_dialog()
        dialog = self._help_dialog
        if dialog is None:
            return
        dialog.deiconify()
        self._style_help_dialog()
        left, top, right, bottom = _get_work_area(dialog)
        width = min(self._px(640), right - left - self._px(32))
        available_height = bottom - top - self._px(64)
        height = min(self._px(610), available_height)
        # Lay out at the chosen width before measuring wrapped, mixed-font text.
        # A fixed height can clip just a few pixels and show a needless scrollbar.
        dialog.geometry(f"{width}x{height}")
        dialog.lift()
        # Windows delivers child Configure events after the native frame maps;
        # idle tasks alone leave first-open or previous-open text dimensions.
        dialog.update()
        if self._help_text is not None:
            text = self._help_text
            text_height = cast(int, text.count("1.0", "end", "update", "ypixels"))
            text_height += 2 * int(text.cget("pady"))
            chrome_height = dialog.winfo_height() - text.winfo_height()
            height = min(text_height + chrome_height + self._px(8), available_height)
        x = max(
            left,
            min(self.root.winfo_rootx() + self._px(48), right - width - self._px(16)),
        )
        y = max(
            top,
            min(self.root.winfo_rooty() + self._px(24), bottom - height - self._px(48)),
        )
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.minsize(min(width, self._px(420)), min(height, self._px(300)))
        dialog.lift()
        dialog.focus_force()
        if self._help_text is not None:
            self._help_text.focus_set()

    def _create_help_dialog(self) -> None:
        """Build readable help with native scrolling and an always-visible Close."""
        dialog = tk.Toplevel(self.root)
        self._help_dialog = dialog
        dialog.withdraw()
        dialog.title("How to use ShiftPress")
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", self._hide_help_dialog)
        dialog.bind("<Escape>", lambda _event: self._hide_help_dialog())
        actions = ttk.Frame(dialog, padding=self._spacing(24, 12))
        actions.pack(side="bottom", fill="x")
        ttk.Button(
            actions, text="Close", command=self._hide_help_dialog, width=12
        ).pack(side="right")
        content = ttk.Frame(dialog, padding=self._spacing(24, 20, 12, 0))
        content.pack(fill="both", expand=True)
        text = tk.Text(
            content,
            wrap="word",
            font=FONTS.main,
            borderwidth=0,
            highlightthickness=0,
            padx=self._px(4),
            pady=self._px(4),
            spacing3=self._px(12),
            cursor="arrow",
            takefocus=True,
        )
        self._help_text = text
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=text.yview)

        def sync_scrollbar(first: str | float, last: str | float) -> None:
            first_value, last_value = float(first), float(last)
            scrollbar.set(first_value, last_value)
            if first_value <= 0 and last_value >= 1:
                scrollbar.pack_forget()
            else:
                scrollbar.pack(
                    side="right", fill="y", padx=self._spacing(12, 0), before=text
                )

        text.configure(yscrollcommand=sync_scrollbar)
        text.pack(fill="both", expand=True)
        text.tag_configure("title", font=FONTS.section, spacing3=self._px(20))
        text.tag_configure(
            "heading", font=FONTS.card_title, spacing1=self._px(8), spacing3=self._px(6)
        )
        text.insert("end", "How to use ShiftPress\n", "title")
        for heading, body in (
            (
                "1. Set up your sources",
                "In Setup, choose the Night and Day template folders and a printer.\n"
                "Select Apply to keep Setup changes, or Cancel to restore the previous folders and printer.",
            ),
            (
                "2. Choose your schedules",
                "Include the Night schedule, Day schedule, or both. Choose a single date or date range for each included shift.",
            ),
            (
                "3. Review and print",
                "Review Print scope, then select Print. ShiftPress runs preflight checks before opening Word and stops if a required template or printer is unavailable.",
            ),
            (
                "Start a fresh run",
                "Reset run restores the common Night-today and Day-tomorrow selection.",
            ),
            (
                "Keyboard shortcuts",
                "Alt+S opens Setup · Alt+P prints · Alt+H opens help.\n"
                "Escape closes this help. In the main window, Escape stops after the current document.",
            ),
        ):
            text.insert("end", heading + "\n", "heading")
            text.insert("end", body + "\n")
        text.configure(state="disabled")

    def _style_help_dialog(self) -> None:
        """Keep open help synchronized when the main window changes palette."""
        if self._help_dialog is None or self._help_text is None:
            return
        self._help_dialog.configure(bg=self.colors.background)
        self._help_text.configure(
            background=self.colors.background,
            foreground=self.colors.text_main,
            selectbackground=self.colors.action,
            selectforeground=self.colors.action_text,
            inactiveselectbackground=self.colors.secondary,
        )
        self._help_text.tag_configure("heading", foreground=self.colors.action)
        self._style_titlebar(self._help_dialog)

    def _hide_help_dialog(self) -> None:
        """Return to the help action without mutating print state."""
        if self._help_dialog is not None:
            self._help_dialog.withdraw()
        if self._help_button is not None:
            self._help_button.focus_set()

    def ask_yes_no(self, title: str, message: str) -> bool:
        """Ask the user a yes/no question.

        Args:
            title: Dialog window title.
            message: Question to display.

        Returns:
            ``True`` if the user clicked Yes, ``False`` otherwise.
        """
        return bool(messagebox.askyesno(title, message))

    def open_logs_folder(self) -> None:
        """Open the app data/log directory in the OS file explorer."""

        path = get_data_dir()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug(f"Could not create logs directory: {e}")

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
                return
        except Exception as e:
            logger.debug(f"os.startfile failed: {e}")

        try:
            if sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception:
            logger.exception("Could not open logs folder")
            messagebox.showinfo(
                "Logs Folder",
                f"Could not open folder automatically.\n\nPath:\n{path}",
            )

    def run(self) -> None:
        """Start the main UI loop."""
        logger.info("Starting UI main loop")
        self.root.mainloop()
