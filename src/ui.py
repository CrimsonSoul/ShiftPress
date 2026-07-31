"""
UI components for ShiftPress application.

This module contains all Tkinter UI components and styling.
"""

import os
import sys
import subprocess
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, filedialog, ttk
from datetime import date, timedelta
from pathlib import Path

try:
    from tkcalendar import DateEntry  # type: ignore
except Exception:  # pragma: no cover
    DateEntry = None

from typing import Optional, Callable, Literal, Union, Any, cast

try:
    import win32print  # type: ignore
except Exception:  # pragma: no cover
    win32print = None

from .constants import (
    COLORS,
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
    ShiftSelection,
    ShiftType,
    build_print_manifest,
)

logger = get_logger(__name__)

# Imported lazily to avoid circular dependency; only used for version display.
_APP_VERSION: Optional[str] = None

# Placeholder text shown in empty path entries.
_PATH_PLACEHOLDER = "Click Browse to select folder\u2026"


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
        Version string (e.g. ``"2.1.0"``), or ``""`` if unavailable.
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


class _ToolTip:
    """Lightweight hover tooltip for any Tkinter widget."""

    def __init__(self, widget: Any, text: str, delay: int = 400) -> None:
        """Create a tooltip that appears on hover.

        Args:
            widget: The Tkinter widget to attach the tooltip to.
            text: Tooltip text to display.
            delay: Delay in milliseconds before showing the tooltip.
        """
        self._widget = widget
        self._text = text
        self._delay = delay
        self._tip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def _schedule(self, _event: Any = None) -> None:
        self._cancel()
        self._after_id = self._widget.after(self._delay, self._show)

    def _on_destroy(self, _event: Any = None) -> None:
        self._cancel()
        self._hide()

    def _show(self) -> None:
        if self._tip_window:
            return
        try:
            x = self._widget.winfo_rootx() + 20
            y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        except Exception as e:
            logger.debug(f"Tooltip geometry lookup failed: {e}")
            return
        try:
            tw = tk.Toplevel(self._widget)
        except tk.TclError:
            return
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self._text,
            background=COLORS.surface,
            foreground=COLORS.text_main,
            relief="solid",
            borderwidth=1,
            font=FONTS.sub,
            padx=6,
            pady=4,
        )
        label.pack()
        self._tip_window = tw

    def _hide(self, _event: Any = None) -> None:
        self._cancel()
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None

    def _cancel(self) -> None:
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None


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

    entry.bind("<FocusIn>", _hide, add="+")
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
        self.root.title("ShiftPress")
        self.root.resizable(WINDOW_RESIZABLE, WINDOW_RESIZABLE)
        self.root.configure(bg=COLORS.background)
        self._today = today or date.today()
        self._inputs_enabled = True

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
        self.setup_summary_label: Optional[ttk.Label] = None
        self._setup_details: Optional[ttk.Frame] = None
        self._setup_dialog: Optional[tk.Toplevel] = None
        self._setup_toggle_btn: Optional[ttk.Button] = None
        self._manifest_card: Optional[ttk.Frame] = None
        self._footer_frame: Optional[ttk.Frame] = None
        self.manifest_title_label: Optional[ttk.Label] = None
        self.manifest_label: Optional[ttk.Label] = None
        self.status_label: Optional[ttk.Label] = None
        self.progress_var: Optional[tk.DoubleVar] = None
        self.progress: Optional[ttk.Progressbar] = None
        self._progress_pct: Optional[ttk.Label] = None
        self.printer_dropdown: Optional[ttk.OptionMenu] = None
        self._refresh_btn: Optional[ttk.Button] = None
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

        logger.info("UI initialized")

    def _configure_styles(self) -> None:
        """Configure ttk styles for the application."""
        # Base frame
        self.style.configure("TFrame", background=COLORS.background)
        self.style.configure(
            "TLabel",
            background=COLORS.background,
            foreground=COLORS.text_main,
            font=FONTS.main,
        )
        self.style.configure("Card.TFrame", background=COLORS.surface)
        self.style.configure(
            "Card.TLabel",
            background=COLORS.surface,
            foreground=COLORS.text_main,
            font=FONTS.main,
        )
        self.style.configure(
            "CardSub.TLabel",
            background=COLORS.surface,
            foreground=COLORS.text_dim,
            font=FONTS.sub,
        )

        # Native card shells avoid LabelFrame's platform-specific title patches.
        for style_name, border_color in (
            ("SetupCard.TFrame", COLORS.border),
            ("NightCard.TFrame", COLORS.accent),
            ("DayCard.TFrame", COLORS.day_accent),
            ("Manifest.TFrame", COLORS.border),
            ("DialogCard.TFrame", COLORS.border),
        ):
            self.style.configure(
                style_name,
                background=COLORS.surface,
                bordercolor=border_color,
                borderwidth=1,
                relief="solid",
            )
        self.style.configure(
            "SetupTitle.TLabel",
            background=COLORS.background,
            foreground=COLORS.accent,
            font=FONTS.card_title,
        )
        self.style.configure(
            "NightTitle.TLabel",
            background=COLORS.background,
            foreground=COLORS.accent,
            font=FONTS.card_title,
        )
        self.style.configure(
            "DayTitle.TLabel",
            background=COLORS.background,
            foreground=COLORS.day_accent,
            font=FONTS.card_title,
        )
        self.style.configure("SetupHeader.TSeparator", background=COLORS.border)
        self.style.configure("NightHeader.TSeparator", background=COLORS.accent)
        self.style.configure("DayHeader.TSeparator", background=COLORS.day_accent)

        # Inputs
        self.style.configure(
            "TEntry",
            fieldbackground=COLORS.input,
            foreground=COLORS.text_main,
            insertcolor=COLORS.text_main,
            selectbackground=COLORS.accent,
            selectforeground=COLORS.text_main,
            bordercolor=COLORS.border,
            borderwidth=1,
            padding=(8, 7),
        )
        self.style.map(
            "TEntry",
            fieldbackground=[("disabled", COLORS.border)],
            foreground=[("disabled", COLORS.text_dim)],
        )
        # DateEntry copies TCombobox into its own arrow-bearing style.
        self.style.configure(
            "TCombobox",
            fieldbackground=COLORS.input,
            background=COLORS.secondary,
            foreground=COLORS.text_main,
            arrowcolor=COLORS.text_main,
            bordercolor=COLORS.border,
            lightcolor=COLORS.border,
            darkcolor=COLORS.border,
            padding=(8, 7),
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", COLORS.input),
                ("disabled", COLORS.surface),
            ],
            foreground=[("disabled", COLORS.text_dim)],
            arrowcolor=[("disabled", COLORS.text_dim)],
        )

        # Buttons
        self.style.configure(
            "TButton",
            background=COLORS.secondary,
            foreground=COLORS.text_main,
            bordercolor=COLORS.border,
            borderwidth=1,
            font=FONTS.bold,
            padding=(14, 8),
        )
        self.style.map(
            "TButton",
            background=[
                ("disabled", COLORS.border),
                ("pressed", COLORS.background),
                ("active", COLORS.secondary),
            ],
            foreground=[("disabled", COLORS.text_dim)],
        )
        self.style.configure(
            "Tertiary.TButton",
            background=COLORS.background,
            foreground=COLORS.text_dim,
            borderwidth=0,
            font=FONTS.sub,
            padding=(6, 2),
        )
        self.style.map(
            "Tertiary.TButton",
            background=[
                ("pressed", COLORS.background),
                ("active", COLORS.background),
            ],
            foreground=[
                ("pressed", COLORS.text_main),
                ("active", COLORS.text_main),
            ],
        )
        self.style.configure(
            "Primary.TButton",
            background=COLORS.action,
            foreground=COLORS.text_main,
            bordercolor=COLORS.day_accent,
            borderwidth=1,
            font=FONTS.button,
            padding=(26, 16),
        )
        self.style.map(
            "Primary.TButton",
            background=[
                ("disabled", COLORS.border),
                ("pressed", COLORS.action_hover),
                ("active", COLORS.action_hover),
            ],
            foreground=[
                ("disabled", COLORS.text_dim),
                ("pressed", COLORS.text_main),
                ("active", COLORS.text_main),
            ],
        )
        self.style.configure(
            "Danger.TButton",
            background=COLORS.error,
            foreground=COLORS.background,
            bordercolor=COLORS.error,
            borderwidth=1,
            font=FONTS.button,
            padding=(26, 16),
        )
        self.style.map(
            "Danger.TButton",
            background=[
                ("disabled", COLORS.border),
                ("pressed", "#E25D72"),
                ("active", "#E25D72"),
            ],
            foreground=[("disabled", COLORS.text_dim)],
        )

        # Progress bar
        self.style.configure(
            "Horizontal.TProgressbar",
            thickness=12,
            troughcolor=COLORS.input,
            background=COLORS.success,
            bordercolor=COLORS.border,
        )

        # Specialized Labels
        self.style.configure(
            "Header.TLabel",
            font=FONTS.header,
            foreground=COLORS.text_main,
            background=COLORS.background,
        )
        self.style.configure(
            "Sub.TLabel",
            font=FONTS.sub,
            foreground=COLORS.text_dim,
            background=COLORS.background,
        )
        self.style.configure(
            "ManifestTitle.TLabel",
            font=FONTS.card_title,
            foreground=COLORS.text_main,
            background=COLORS.surface,
        )
        self.style.configure(
            "NightCount.TLabel",
            font=FONTS.bold,
            foreground=COLORS.success,
            background=COLORS.surface,
        )
        self.style.configure(
            "DayCount.TLabel",
            font=FONTS.bold,
            foreground=COLORS.success,
            background=COLORS.surface,
        )

        # Status labels (success / error variants)
        self.style.configure(
            "Success.TLabel",
            font=FONTS.sub,
            foreground=COLORS.success,
            background=COLORS.background,
        )
        self.style.configure(
            "Error.TLabel",
            font=FONTS.sub,
            foreground=COLORS.error,
            background=COLORS.background,
        )

        # Checkbuttons
        self.style.configure(
            "TCheckbutton",
            background=COLORS.background,
            foreground=COLORS.text_main,
            font=FONTS.sub,
        )
        self.style.map(
            "TCheckbutton",
            background=[("active", COLORS.background)],
            foreground=[("disabled", COLORS.text_dim)],
        )
        self.style.configure(
            "TRadiobutton",
            background=COLORS.background,
            foreground=COLORS.text_main,
            font=FONTS.sub,
        )
        self.style.map(
            "TRadiobutton",
            background=[("active", COLORS.background)],
            foreground=[("disabled", COLORS.text_dim)],
        )
        self.style.configure(
            "Card.TCheckbutton",
            background=COLORS.surface,
            foreground=COLORS.text_main,
            font=FONTS.bold,
        )
        self.style.map(
            "Card.TCheckbutton",
            background=[("active", COLORS.surface)],
            foreground=[("disabled", COLORS.text_dim)],
        )
        self.style.configure(
            "Card.TRadiobutton",
            background=COLORS.surface,
            foreground=COLORS.text_main,
            font=FONTS.main,
        )
        self.style.map(
            "Card.TRadiobutton",
            background=[("active", COLORS.surface)],
            foreground=[("disabled", COLORS.text_dim)],
        )
        self.style.configure(
            "Card.TSeparator",
            background=COLORS.border,
        )

        # OptionMenu (printer dropdown)
        self.style.configure(
            "TMenubutton",
            background=COLORS.input,
            foreground=COLORS.text_main,
            borderwidth=0,
            font=FONTS.main,
            padding=(10, 6),
        )
        self.style.map(
            "TMenubutton",
            background=[
                ("disabled", COLORS.border),
                ("active", COLORS.secondary),
            ],
            foreground=[("disabled", COLORS.text_dim)],
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
                self.root.iconbitmap(str(ico_path))
            elif png_path.exists():
                img = tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, img)
                # Keep a reference so the image isn't garbage-collected.
                self._icon_image = img
        except Exception as e:
            logger.debug(f"Could not set window icon: {e}")

    def _center_window(self) -> None:
        """Center the window on the primary monitor."""
        try:
            self.root.update_idletasks()
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            scr_w = self.root.winfo_screenwidth()
            scr_h = self.root.winfo_screenheight()
            x = max(0, (scr_w - w) // 2)
            y = max(0, (scr_h - h) // 2)
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
        except Exception as e:
            logger.error(f"Error enumerating printers: {e}")
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
                # tk._setit is an internal helper; keep usage isolated here.
                set_it = getattr(tk, "_setit", None)
                if callable(set_it):
                    menu.add_command(label=name, command=set_it(self.printer_var, name))
                else:
                    var = self.printer_var
                    if var is not None:
                        menu.add_command(
                            label=name, command=lambda v=name, vv=var: vv.set(v)
                        )

            current = self.printer_var.get()
            if current and current in printers:
                self.printer_var.set(current)
            else:
                self.printer_var.set(DEFAULT_PRINTER_LABEL)
        except Exception as e:
            logger.error(f"Could not update printer dropdown: {e}")

    # ------------------------------------------------------------------
    # Widget creation
    # ------------------------------------------------------------------

    def _create_widgets(self) -> None:
        """Create all UI widgets."""
        bg_canvas = ttk.Frame(self.root, padding="28")
        bg_canvas.pack(fill="both", expand=True)

        self._create_header(bg_canvas)
        self._create_setup_card(bg_canvas)
        self._create_shift_selection_row(bg_canvas)
        self._create_manifest_card(bg_canvas)
        self._create_footer(bg_canvas)
        self.refresh_manifest_preview()

    def _create_header(self, parent: ttk.Frame) -> None:
        """Create the header section."""
        header_row = ttk.Frame(parent)
        header_row.pack(fill="x", pady=(0, 20))

        title_row = ttk.Frame(header_row)
        title_row.pack(fill="x")
        ttk.Label(
            title_row,
            text="Prepare print run",
            style="Header.TLabel",
        ).pack(side="left")
        version = _get_version()
        if version:
            ttk.Label(
                title_row,
                text=f"ShiftPress  ·  v{version}",
                style="Sub.TLabel",
            ).pack(side="right", anchor="s", pady=(0, 5))

        ttk.Label(
            header_row,
            text="Choose exactly which schedules go to print.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(6, 0))

    def _create_titled_card(
        self,
        parent: ttk.Frame,
        title: str,
        style_prefix: str,
        padding: int,
    ) -> tuple[ttk.Frame, ttk.Frame]:
        """Create a native card with a clean title and thin accent rule."""
        shell = ttk.Frame(parent)
        title_row = ttk.Frame(shell)
        title_row.pack(fill="x")
        ttk.Label(
            title_row,
            text=title,
            style=f"{style_prefix}Title.TLabel",
        ).pack(side="left")
        ttk.Separator(
            title_row,
            style=f"{style_prefix}Header.TSeparator",
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        card = ttk.Frame(
            shell,
            style=f"{style_prefix}Card.TFrame",
            padding=str(padding),
        )
        card.pack(fill="both", expand=True)
        return shell, card

    def _create_setup_card(self, parent: ttk.Frame) -> None:
        """Create a setup summary whose details open in a separate dialog."""
        shell, card = self._create_titled_card(parent, "Setup", "Setup", 18)
        shell.pack(fill="x", pady=(0, 16))

        summary_row = ttk.Frame(card, style="Card.TFrame")
        summary_row.pack(fill="x")
        self.setup_summary_label = ttk.Label(
            summary_row,
            text="Template folders not configured\nChoose a printer",
            style="Card.TLabel",
            justify="left",
        )
        self.setup_summary_label.pack(side="left", anchor="w")
        self._setup_toggle_btn = ttk.Button(
            summary_row,
            text="Change…",
            command=self._show_setup_dialog,
            width=12,
        )
        self._setup_toggle_btn.pack(side="right", padx=(18, 0))

        self._create_setup_dialog()
        self.refresh_setup_summary()

    def _create_setup_dialog(self) -> None:
        """Build the withdrawn setup dialog without changing the main layout."""
        dialog = tk.Toplevel(self.root)
        self._setup_dialog = dialog
        dialog.withdraw()
        dialog.title("ShiftPress Setup")
        dialog.configure(bg=COLORS.background)
        dialog.resizable(True, False)
        dialog.protocol("WM_DELETE_WINDOW", self._hide_setup_dialog)

        canvas = ttk.Frame(dialog, padding="24")
        canvas.pack(fill="both", expand=True)
        ttk.Label(canvas, text="Setup", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            canvas,
            text="Choose the template folders and printer used for print runs.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 18))

        self._setup_details = ttk.Frame(
            canvas,
            style="DialogCard.TFrame",
            padding="18",
        )
        self._setup_details.pack(fill="both", expand=True)

        self.day_entry = self._create_path_row(self._setup_details, "Day Templates", "")
        self.night_entry = self._create_path_row(
            self._setup_details, "Night Templates", ""
        )

        _setup_placeholder(self.day_entry, _PATH_PLACEHOLDER)
        _setup_placeholder(self.night_entry, _PATH_PLACEHOLDER)
        self._create_printer_row(self._setup_details)
        ttk.Button(
            canvas,
            text="Done",
            command=self._hide_setup_dialog,
            width=14,
        ).pack(anchor="e", pady=(18, 0))

    def _show_setup_dialog(self) -> None:
        """Show setup without expanding or displacing the print work surface."""
        if self._setup_dialog is None:
            return
        dialog = self._setup_dialog
        dialog.deiconify()
        try:
            dialog.transient(self.root)
            dialog.update_idletasks()
            width = max(720, dialog.winfo_reqwidth())
            height = dialog.winfo_reqheight()
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
            y = self.root.winfo_rooty() + 48
            dialog.geometry(f"{width}x{height}+{x}+{y}")
            dialog.grab_set()
        except Exception as e:
            logger.debug(f"Could not position setup dialog: {e}")
        dialog.lift()
        dialog.focus_force()

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
        """Summarize configured templates and printer without exposing paths."""
        if self.setup_summary_label is None:
            return
        day_configured = bool(self.get_day_folder())
        night_configured = bool(self.get_night_folder())
        if day_configured and night_configured:
            template_status = "Templates configured"
        elif day_configured or night_configured:
            template_status = "Template folders incomplete"
        else:
            template_status = "Template folders not configured"
        printer = self.get_printer_name()
        printer_status = (
            printer
            if printer and printer != DEFAULT_PRINTER_LABEL
            else "Choose a printer"
        )
        self.setup_summary_label.config(text=f"{template_status}\n{printer_status}")

    def _create_shift_selection_row(self, parent: ttk.Frame) -> None:
        """Create equal-width Night and Day selection panels."""
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 16))
        row.grid_columnconfigure(0, weight=1, uniform="shift")
        row.grid_columnconfigure(1, weight=1, uniform="shift")

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

    def _calendar_kwargs(self) -> dict[str, Any]:
        """Return the shared dark-theme calendar colors."""
        return {
            "background": COLORS.surface,
            "foreground": COLORS.text_main,
            "bordercolor": COLORS.border,
            "headersbackground": COLORS.background,
            "headersforeground": COLORS.text_dim,
            "selectbackground": COLORS.accent,
            "selectforeground": COLORS.text_main,
            "normalbackground": COLORS.surface,
            "normalforeground": COLORS.text_main,
            "weekendbackground": COLORS.surface,
            "weekendforeground": COLORS.text_dim,
            "othermonthbackground": COLORS.background,
            "othermonthforeground": COLORS.text_dim,
            "othermonthwebackground": COLORS.background,
            "othermonthweforeground": COLORS.text_dim,
        }

    def _create_shift_panel(
        self,
        parent: ttk.Frame,
        shift_type: ShiftType,
        default_date: date,
        column: int,
    ) -> None:
        """Create one independent native shift selection panel."""
        if DateEntry is None:
            ttk.Label(
                parent,
                text="Missing dependency: tkcalendar. Please reinstall requirements.txt.",
                style="Error.TLabel",
            ).grid(row=0, column=column, sticky="nsew", padx=8)
            logger.error("tkcalendar is not installed; date pickers unavailable")
            return

        date_entry_cls = cast(Any, DateEntry)
        label = shift_type.title()
        horizontal_padding = (0, 8) if column == 0 else (8, 0)
        shell, card = self._create_titled_card(parent, label, label, 22)
        shell.grid(row=0, column=column, sticky="nsew", padx=horizontal_padding)

        enabled_var = tk.BooleanVar(value=True)
        mode_var = tk.StringVar(value="single")

        def sync_panel(selected: ShiftType = shift_type) -> None:
            self._sync_shift_panel_state(selected)

        include_check = ttk.Checkbutton(
            card,
            text=f"Include {label} schedule",
            variable=enabled_var,
            command=sync_panel,
            style="Card.TCheckbutton",
        )
        include_check.pack(anchor="w", pady=(0, 18))

        mode_row = ttk.Frame(card, style="Card.TFrame")
        mode_row.pack(fill="x", pady=(0, 18))
        single_radio = ttk.Radiobutton(
            mode_row,
            text="Single date",
            variable=mode_var,
            value="single",
            command=sync_panel,
            style="Card.TRadiobutton",
        )
        single_radio.pack(anchor="w", pady=(0, 10))
        range_radio = ttk.Radiobutton(
            mode_row,
            text="Date range",
            variable=mode_var,
            value="range",
            command=sync_panel,
            style="Card.TRadiobutton",
        )
        range_radio.pack(anchor="w")

        date_stack = ttk.Frame(card, style="Card.TFrame")
        date_stack.pack(fill="x")
        date_stack.grid_columnconfigure(0, weight=1)

        # Label-above-entry mirrors the range rows so both modes occupy the
        # same height and toggling never reflows the window.
        single_wrap = ttk.Frame(date_stack, style="Card.TFrame")
        single_wrap.grid(row=0, column=0, sticky="ew")
        ttk.Label(single_wrap, text="Date", style="CardSub.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        single_picker = self._create_date_entry(
            date_entry_cls,
            single_wrap,
            calendar_kw=self._calendar_kwargs(),
        )
        single_picker.pack(fill="x")
        single_picker.set_date(default_date)

        range_wrap = ttk.Frame(date_stack, style="Card.TFrame")
        range_wrap.grid(row=0, column=0, sticky="ew")
        range_wrap.grid_columnconfigure(0, weight=1)
        range_wrap.grid_columnconfigure(1, weight=1)

        range_start_wrap = ttk.Frame(range_wrap, style="Card.TFrame")
        range_start_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Label(range_start_wrap, text="Start date", style="CardSub.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        range_start_picker = self._create_date_entry(
            date_entry_cls,
            range_start_wrap,
            calendar_kw=self._calendar_kwargs(),
        )
        range_start_picker.pack(fill="x")
        range_start_picker.set_date(default_date)

        range_end_wrap = ttk.Frame(range_wrap, style="Card.TFrame")
        range_end_wrap.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Label(range_end_wrap, text="End date", style="CardSub.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        range_end_picker = self._create_date_entry(
            date_entry_cls,
            range_end_wrap,
            calendar_kw=self._calendar_kwargs(),
        )
        range_end_picker.pack(fill="x")
        range_end_picker.set_date(default_date)

        ttk.Separator(card, style="Card.TSeparator").pack(fill="x", pady=(20, 14))
        count_label = ttk.Label(
            card,
            text="Selected · 1 document",
            style=f"{label}Count.TLabel",
        )
        count_label.pack(anchor="w")

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
            "<<DateEntrySelected>>",
            lambda _event, selected=shift_type: self._on_shift_date_selected(selected),
        )
        range_start_picker.bind(
            "<<DateEntrySelected>>",
            lambda _event, selected=shift_type: self._on_range_start_selected(selected),
        )
        range_end_picker.bind(
            "<<DateEntrySelected>>",
            lambda _event, selected=shift_type: self._on_shift_date_selected(selected),
        )
        self._sync_shift_panel_state(shift_type)

    def _on_shift_date_selected(self, shift_type: ShiftType) -> None:
        """Refresh visible intent after a shift date changes."""
        del shift_type
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

    def _sync_shift_panel_state(self, shift_type: ShiftType) -> None:
        """Apply include/mode state to one panel without changing its values."""
        panel = self._shift_panels[shift_type]
        enabled = bool(panel.enabled_var.get()) and self._inputs_enabled
        state: Literal["normal", "disabled"] = "normal" if enabled else "disabled"

        for widget in (
            panel.single_radio,
            panel.range_radio,
            panel.single_picker,
            panel.range_start_picker,
            panel.range_end_picker,
        ):
            widget.config(state=state)

        if panel.mode_var.get() == "range":
            panel.single_wrap.grid_remove()
            panel.range_wrap.grid()
        else:
            panel.range_wrap.grid_remove()
            panel.single_wrap.grid()

        if len(self._shift_panels) == 2:
            self.refresh_manifest_preview()

    def _create_manifest_card(self, parent: ttk.Frame) -> None:
        """Create the exact preflight-neutral print manifest summary."""
        card = ttk.Frame(parent, style="Manifest.TFrame", padding="18")
        self._manifest_card = card
        card.pack(fill="x", pady=(0, 16))
        self.manifest_title_label = ttk.Label(
            card,
            text="This run: No schedules selected",
            style="ManifestTitle.TLabel",
        )
        self.manifest_title_label.pack(anchor="w", pady=(0, 10))
        self.manifest_label = ttk.Label(
            card,
            text="Printer: Choose a printer",
            style="CardSub.TLabel",
            justify="left",
            anchor="w",
        )
        self.manifest_label.pack(fill="x")

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

        # Prefer using ttk styling for the entry itself.
        try:
            return date_entry_cls(
                parent,
                style="DateEntry",
                date_pattern="mm/dd/yyyy",
                calendar_kw=calendar_kw,
            )
        except TypeError as e:
            logger.debug(f"DateEntry calendar_kw not supported, falling back: {e}")

        # Older builds may not support calendar_kw; try passing common color keys directly.
        try:
            return date_entry_cls(
                parent,
                style="DateEntry",
                date_pattern="mm/dd/yyyy",
                **calendar_kw,
            )
        except TypeError as e:
            logger.debug(f"DateEntry inline calendar kwargs not supported: {e}")
            return date_entry_cls(
                parent,
                style="DateEntry",
                date_pattern="mm/dd/yyyy",
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
            req_w = self.root.winfo_reqwidth()
            req_h = self.root.winfo_reqheight()
            scr_w = self.root.winfo_screenwidth()
            scr_h = self.root.winfo_screenheight()

            target_w = min(
                max(WINDOW_WIDTH, req_w), max(AUTO_RESIZE_MIN_WIDTH, scr_w - 80)
            )
            target_h = min(
                max(AUTO_RESIZE_MIN_HEIGHT, req_h),
                max(AUTO_RESIZE_MIN_HEIGHT, scr_h - 80),
            )

            self.root.minsize(target_w, target_h)
            self.root.geometry(f"{target_w}x{target_h}")
        except Exception as e:
            logger.debug(f"Content sizing skipped: {e}")

    def _create_printer_row(self, parent: Union[ttk.Frame, ttk.LabelFrame]) -> None:
        """Create the printer selection row."""
        output_row = ttk.Frame(parent, style="Card.TFrame")
        output_row.pack(fill="x", pady=(8, 0))
        ttk.Label(output_row, text="Printer", style="CardSub.TLabel").pack(
            anchor="w", pady=(0, 8)
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
        printer_row = ttk.Frame(output_row, style="Card.TFrame")
        printer_row.pack(fill="x")

        self.printer_dropdown = ttk.OptionMenu(
            printer_row, self.printer_var, DEFAULT_PRINTER_LABEL, *all_printers
        )
        self.printer_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # Style the dropdown popup menu to match the dark theme.
        try:
            menu = self.printer_dropdown["menu"]
            menu.configure(
                bg=COLORS.surface,
                fg=COLORS.text_main,
                activebackground=COLORS.accent,
                activeforeground=COLORS.text_main,
                borderwidth=1,
                relief="flat",
            )
        except Exception as e:
            logger.debug(f"Could not style printer dropdown menu: {e}")

        self._refresh_btn = ttk.Button(
            printer_row,
            text="Refresh",
            width=10,
            command=self.refresh_printers,
            cursor="hand2",
        )
        self._refresh_btn.pack(side="right")
        _ToolTip(self._refresh_btn, "Re-scan for available printers")

        if not all_printers:
            msg = "No printers found. Check connections."
            if win32print is None:
                msg = "Printing requires Windows with pywin32 installed (win32print unavailable)."
            ttk.Label(
                output_row,
                text=msg,
                style="CardSub.TLabel",
                foreground=COLORS.error,
            ).pack(anchor="w", pady=(4, 0))

    def _on_printer_changed(self, *_args: object) -> None:
        """Refresh setup and manifest copy after the printer changes."""
        self.refresh_setup_summary()
        self.refresh_manifest_preview()

    def _create_footer(self, parent: ttk.Frame) -> None:
        """Create the action footer (status, progress, button)."""
        footer = ttk.Frame(parent)
        self._footer_frame = footer
        footer.pack(fill="x")
        footer.grid_columnconfigure(0, weight=1)

        status_wrap = ttk.Frame(footer)
        status_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 24))
        self.status_label = ttk.Label(
            status_wrap,
            text="Review the selected schedules",
            style="Sub.TLabel",
        )
        self.status_label.pack(side="left")

        open_logs_btn = ttk.Button(
            status_wrap,
            text="Open logs",
            style="Tertiary.TButton",
            command=self.open_logs_folder,
            cursor="hand2",
        )
        open_logs_btn.pack(side="left", padx=(12, 0))
        _ToolTip(open_logs_btn, "Open configuration, log, and report folder")

        progress_row = ttk.Frame(footer)
        progress_row.grid(row=1, column=0, sticky="ew", padx=(0, 24), pady=(10, 0))

        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(
            progress_row,
            variable=self.progress_var,
            maximum=PROGRESS_MAX,
            style="Horizontal.TProgressbar",
        )
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self._progress_pct = ttk.Label(
            progress_row,
            text="0%",
            style="Sub.TLabel",
            width=5,
            anchor="e",
        )
        self._progress_pct.pack(side="right")

        self.print_btn = ttk.Button(
            footer,
            text="Print schedules",
            style="Primary.TButton",
            width=20,
            cursor="hand2",
        )
        self.print_btn.grid(row=0, column=1, rowspan=2, sticky="nsew")

    def _create_path_row(
        self, parent: Union[ttk.Frame, ttk.LabelFrame], label: str, default_val: str
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
        wrap = ttk.Frame(parent, style="Card.TFrame")
        wrap.pack(fill="x", pady=8)
        ttk.Label(wrap, text=label, style="CardSub.TLabel").pack(
            anchor="w", pady=(0, 6)
        )

        row = ttk.Frame(wrap, style="Card.TFrame")
        row.pack(fill="x")

        entry = ttk.Entry(row)
        entry.insert(0, default_val)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

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
            entry.config(foreground=COLORS.text_main)
            entry.insert(0, value)
        else:
            entry.config(foreground=COLORS.text_dim)
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
        return f"{selection.shift_type.title()} — {scope} — " f"{job_count} {noun}"

    def refresh_manifest_preview(self) -> None:
        """Refresh the preflight-neutral manifest copy and count-aware action."""
        if len(self._shift_panels) != 2:
            return

        selections = self.get_shift_selections()
        try:
            manifest = build_print_manifest(selections)
            if manifest:
                title = f"This run: {len(manifest)} schedules"
                lines: list[str] = []
                row_number = 1
                for selection in selections:
                    if not selection.enabled:
                        self._shift_panels[selection.shift_type].count_label.config(
                            text="Not included"
                        )
                        continue
                    count = sum(
                        1 for job in manifest if job.shift_type == selection.shift_type
                    )
                    lines.append(
                        f"{row_number}. "
                        f"{self._format_selection_summary(selection, count)}"
                    )
                    self._shift_panels[selection.shift_type].count_label.config(
                        text=(
                            f"Selected · {count} "
                            f"{'document' if count == 1 else 'documents'}"
                        )
                    )
                    row_number += 1
            else:
                title = "This run: No schedules selected"
                lines = []
                for selection in selections:
                    self._shift_panels[selection.shift_type].count_label.config(
                        text="Not included"
                    )
        except ValueError as e:
            manifest = ()
            title = "This run: Check date selection"
            lines = [str(e)]
            for selection in selections:
                self._shift_panels[selection.shift_type].count_label.config(
                    text=(
                        "Check date selection" if selection.enabled else "Not included"
                    )
                )

        printer = self.get_printer_name()
        printer_label = (
            printer
            if printer and printer != DEFAULT_PRINTER_LABEL
            else "Choose a printer"
        )
        lines.append(f"Printer: {printer_label}")

        if self.manifest_title_label is not None:
            self.manifest_title_label.config(text=title)
        if self.manifest_label is not None:
            self.manifest_label.config(text="\n".join(lines))
        if self.print_btn is not None:
            count = len(manifest)
            if count == 0:
                button_text = "Print schedules"
            elif count == 1:
                button_text = "Print 1 schedule"
            else:
                button_text = f"Print {count} schedules"
            self.print_btn.config(text=button_text)

    def set_processing_mode(self, processing: bool) -> None:
        """Switch the primary action between print and cancellation states."""
        if self.print_btn is None:
            return
        if processing:
            self.print_btn.config(text="Cancel", style="Danger.TButton")
        else:
            self.print_btn.config(style="Primary.TButton")
            self.refresh_manifest_preview()

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
            if widget is not None:
                try:
                    widget.config(state=state)
                except Exception as e:
                    logger.debug(f"Could not set entry state: {e}")
        for button in self._browse_buttons:
            try:
                button.config(state=state)
            except Exception as e:
                logger.debug(f"Could not set Browse button state: {e}")
        if self.printer_dropdown is not None:
            try:
                self.printer_dropdown.config(state=state)
            except Exception as e:
                logger.debug(f"Could not set printer dropdown state: {e}")
        if self._refresh_btn is not None:
            try:
                self._refresh_btn.config(state=state)
            except Exception as e:
                logger.debug(f"Could not set refresh button state: {e}")
        if self._setup_toggle_btn is not None:
            try:
                self._setup_toggle_btn.config(state=state)
            except Exception as e:
                logger.debug(f"Could not set setup toggle state: {e}")
        for shift_type, panel in self._shift_panels.items():
            try:
                panel.include_check.config(state=state)
                self._sync_shift_panel_state(shift_type)
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
        if self.status_label:
            if level == "success":
                style = "Success.TLabel"
            elif level == "error":
                style = "Error.TLabel"
            elif level is not None:
                style = "Sub.TLabel"
            else:
                # Infer from message for callers that don't pass level.
                msg_lower = message.lower()
                if "complete" in msg_lower:
                    style = "Success.TLabel"
                elif (
                    "cancel" in msg_lower or "error" in msg_lower or "fail" in msg_lower
                ):
                    style = "Error.TLabel"
                else:
                    style = "Sub.TLabel"
            self.status_label.config(text=message, style=style)
        if self.progress_var:
            self.progress_var.set(progress)
        if self._progress_pct:
            self._progress_pct.config(text=f"{int(progress)}%")

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
        except Exception as e:
            logger.error(f"Could not open logs folder: {e}")
            messagebox.showinfo(
                "Logs Folder",
                f"Could not open folder automatically.\n\nPath:\n{path}",
            )

    def run(self) -> None:
        """Start the main UI loop."""
        logger.info("Starting UI main loop")
        self.root.mainloop()
