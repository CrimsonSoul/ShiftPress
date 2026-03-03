"""
UI components for ShiftPress application.

This module contains all Tkinter UI components and styling.
"""

import os
import sys
import subprocess
import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from datetime import date
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
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
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

logger = get_logger(__name__)

# Imported lazily to avoid circular dependency; only used for version display.
_APP_VERSION: Optional[str] = None

# Placeholder text shown in empty path entries.
_PATH_PLACEHOLDER = "Click Browse to select folder\u2026"


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

    def __init__(self, root: tk.Tk):
        """
        Initialize the UI.

        Args:
            root: The Tkinter root window
        """
        self.root = root
        self.root.title("ShiftPress")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(WINDOW_RESIZABLE, WINDOW_RESIZABLE)
        self.root.configure(bg=COLORS.background)

        # Apply window icon if available.
        self._apply_icon()

        # Provide a sane minimum size; DPI scaling can otherwise clip content.
        try:
            self.root.minsize(WINDOW_WIDTH, WINDOW_MIN_HEIGHT)
        except Exception as e:
            logger.debug(f"Could not set minimum window size: {e}")

        # Configure styles
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._configure_styles()

        # UI components
        self.day_entry: Optional[ttk.Entry] = None
        self.night_entry: Optional[ttk.Entry] = None
        self.start_date_picker: Optional[Any] = None
        self.end_date_picker: Optional[Any] = None
        self.printer_var: Optional[tk.StringVar] = None
        self.status_label: Optional[ttk.Label] = None
        self.progress_var: Optional[tk.DoubleVar] = None
        self.progress: Optional[ttk.Progressbar] = None
        self._progress_pct: Optional[ttk.Label] = None
        self.printer_dropdown: Optional[ttk.OptionMenu] = None
        self._refresh_btn: Optional[ttk.Button] = None
        self.print_btn: Optional[tk.Button] = None

        # Cached enumerations
        self._cached_printers: list[str] = []

        # Create widgets
        self._create_widgets()

        # If DPI scaling / fonts push content beyond default height, expand once.
        self._auto_resize_to_content()

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

        # Card frames (LabelFrame)
        self.style.configure(
            "TLabelframe",
            background=COLORS.background,
            foreground=COLORS.accent,
            bordercolor=COLORS.border,
            borderwidth=1,
        )
        self.style.configure(
            "TLabelframe.Label",
            background=COLORS.background,
            foreground=COLORS.accent,
            font=FONTS.card_title,
        )

        # Inputs
        self.style.configure(
            "TEntry",
            fieldbackground=COLORS.surface,
            foreground=COLORS.text_main,
            insertcolor=COLORS.text_main,
            selectbackground=COLORS.accent,
            selectforeground=COLORS.text_main,
            borderwidth=0,
        )
        self.style.map(
            "TEntry",
            fieldbackground=[("disabled", COLORS.border)],
            foreground=[("disabled", COLORS.text_dim)],
        )

        # Buttons
        self.style.configure(
            "TButton",
            background=COLORS.surface,
            foreground=COLORS.text_main,
            borderwidth=0,
            font=FONTS.bold,
            padding=(12, 6),
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

        # Progress bar
        self.style.configure(
            "Horizontal.TProgressbar",
            thickness=8,
            troughcolor=COLORS.border,
            background=COLORS.accent,
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

        # OptionMenu (printer dropdown)
        self.style.configure(
            "TMenubutton",
            background=COLORS.surface,
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

        # Header
        self._create_header(bg_canvas)

        # Card 1 — Templates
        self._create_templates_card(bg_canvas)

        # Card 2 — Print Settings
        self._create_print_settings_card(bg_canvas)

        # Footer (status + progress + action button)
        self._create_footer(bg_canvas)

    def _create_header(self, parent: ttk.Frame) -> None:
        """Create the header section."""
        header_row = ttk.Frame(parent)
        header_row.pack(fill="x", pady=(0, 24))

        # Title row: app name + version badge
        title_row = ttk.Frame(header_row)
        title_row.pack(fill="x")
        ttk.Label(title_row, text="ShiftPress", style="Header.TLabel").pack(side="left")
        version = _get_version()
        if version:
            ttk.Label(
                title_row,
                text=f"v{version}",
                style="Sub.TLabel",
            ).pack(side="left", padx=(12, 0), anchor="s", pady=(0, 4))

        ttk.Label(
            header_row,
            text="Batch print shift schedules",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

    def _create_templates_card(self, parent: ttk.Frame) -> None:
        """Create the Templates card (day / night template paths)."""
        card = ttk.LabelFrame(parent, text=" Templates ", padding="20")
        card.pack(fill="x", pady=(0, 16))

        self.day_entry = self._create_path_row(card, "Day Templates", "")
        self.night_entry = self._create_path_row(card, "Night Templates", "")

        # Attach placeholder text to both entries.
        _setup_placeholder(self.day_entry, _PATH_PLACEHOLDER)
        _setup_placeholder(self.night_entry, _PATH_PLACEHOLDER)

    def _create_print_settings_card(self, parent: ttk.Frame) -> None:
        """Create the Print Settings card (date range + printer)."""
        card = ttk.LabelFrame(parent, text=" Print Settings ", padding="20")
        card.pack(fill="x", pady=(0, 16))

        # Date range
        self._create_date_range_row(card)

        # Printer
        self._create_printer_row(card)

    def _create_date_range_row(self, parent: Union[ttk.Frame, ttk.LabelFrame]) -> None:
        """Create the date range selection row."""
        if DateEntry is None:
            ttk.Label(
                parent,
                text="Missing dependency: tkcalendar. Please reinstall requirements.txt.",
                style="Error.TLabel",
            ).pack(anchor="w", pady=(0, 8))
            logger.error("tkcalendar is not installed; date pickers unavailable")
            return

        date_entry_cls = cast(Any, DateEntry)

        calendar_kw = {
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

        range_row = ttk.Frame(parent)
        range_row.pack(fill="x", pady=(0, 20))

        # Start Date
        start_wrap = ttk.Frame(range_row)
        start_wrap.pack(side="left", expand=True, fill="x", padx=(0, 12))
        ttk.Label(start_wrap, text="Start date", style="Sub.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        start_picker = self._create_date_entry(
            date_entry_cls,
            start_wrap,
            calendar_kw=calendar_kw,
        )
        start_picker.pack(fill="x")
        self.start_date_picker = start_picker

        try:
            start_picker.bind("<<DateEntrySelected>>", self._on_start_date_selected)
        except Exception as e:
            logger.debug(f"Could not bind DateEntrySelected event: {e}")

        # End Date
        end_wrap = ttk.Frame(range_row)
        end_wrap.pack(side="left", expand=True, fill="x", padx=(12, 0))
        ttk.Label(end_wrap, text="End date", style="Sub.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        end_picker = self._create_date_entry(
            date_entry_cls,
            end_wrap,
            calendar_kw=calendar_kw,
        )
        end_picker.pack(fill="x")
        self.end_date_picker = end_picker

    def _on_start_date_selected(self, event: Optional[object] = None) -> None:
        """Sync end date to match start date if end is currently before start."""

        start_picker = self.start_date_picker
        end_picker = self.end_date_picker

        if start_picker is None or end_picker is None:
            return

        try:
            start_dt = cast(Any, start_picker).get_date()
            end_dt = cast(Any, end_picker).get_date()
            if end_dt < start_dt:
                cast(Any, end_picker).set_date(start_dt)
        except Exception as e:
            # DateEntry implementations vary; never block the UI on this helper.
            logger.debug(f"Error syncing date pickers: {e}")
            return

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
                style="TEntry",
                date_pattern="mm/dd/yyyy",
                calendar_kw=calendar_kw,
            )
        except TypeError as e:
            logger.debug(f"DateEntry calendar_kw not supported, falling back: {e}")

        # Older builds may not support calendar_kw; try passing common color keys directly.
        try:
            return date_entry_cls(
                parent,
                style="TEntry",
                date_pattern="mm/dd/yyyy",
                **calendar_kw,
            )
        except TypeError as e:
            logger.debug(f"DateEntry inline calendar kwargs not supported: {e}")
            return date_entry_cls(parent, style="TEntry", date_pattern="mm/dd/yyyy")

    def _auto_resize_to_content(self) -> None:
        """Expand the window once if content would be clipped."""

        try:
            self.root.update_idletasks()
            req_w = self.root.winfo_reqwidth()
            req_h = self.root.winfo_reqheight()
            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            scr_w = self.root.winfo_screenwidth()
            scr_h = self.root.winfo_screenheight()

            target_w = min(max(cur_w, req_w), max(AUTO_RESIZE_MIN_WIDTH, scr_w - 80))
            target_h = min(max(cur_h, req_h), max(AUTO_RESIZE_MIN_HEIGHT, scr_h - 80))
            if target_w != cur_w or target_h != cur_h:
                self.root.geometry(f"{target_w}x{target_h}")
        except Exception as e:
            logger.debug(f"Auto-resize skipped: {e}")
            return

    def _create_printer_row(self, parent: Union[ttk.Frame, ttk.LabelFrame]) -> None:
        """Create the printer selection row."""
        output_row = ttk.Frame(parent)
        output_row.pack(fill="x", pady=(0, 0))
        ttk.Label(output_row, text="Printer", style="Sub.TLabel").pack(
            anchor="w", pady=(0, 8)
        )

        if win32print is None:
            logger.error("win32print is not available; printer enumeration disabled")

        all_printers = self._enumerate_printers()
        self._cached_printers = all_printers
        logger.debug(f"Found {len(all_printers)} printers")

        self.printer_var = tk.StringVar(value=DEFAULT_PRINTER_LABEL)
        printer_row = ttk.Frame(output_row)
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
                output_row, text=msg, style="Sub.TLabel", foreground=COLORS.error
            ).pack(anchor="w", pady=(4, 0))

    def _create_footer(self, parent: ttk.Frame) -> None:
        """Create the action footer (status, progress, button)."""
        footer = ttk.Frame(parent)
        footer.pack(fill="x", side="bottom")

        # Status row: label on left, Open Logs on right
        status_wrap = ttk.Frame(footer)
        status_wrap.pack(fill="x", pady=(0, 12))
        self.status_label = ttk.Label(
            status_wrap,
            text="Ready when you are",
            style="Sub.TLabel",
        )
        self.status_label.pack(side="left")

        open_logs_btn = ttk.Button(
            status_wrap,
            text="Open Logs",
            width=10,
            command=self.open_logs_folder,
            cursor="hand2",
        )
        open_logs_btn.pack(side="right")
        _ToolTip(open_logs_btn, "Open configuration, log, and report folder")

        # Progress row: bar + percentage label
        progress_row = ttk.Frame(footer)
        progress_row.pack(fill="x", pady=(0, 24))

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

        # Action button
        self.print_btn = tk.Button(
            footer,
            text="Print Schedules",
            bg=COLORS.accent,
            fg=COLORS.text_main,
            font=FONTS.button,
            relief="flat",
            pady=18,
            cursor="hand2",
            activebackground=COLORS.accent_hover,
            activeforeground=COLORS.text_main,
            disabledforeground=COLORS.text_dim,
        )
        self.print_btn.pack(fill="x")

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
        wrap = ttk.Frame(parent)
        wrap.pack(fill="x", pady=8)
        ttk.Label(wrap, text=label, style="Sub.TLabel").pack(anchor="w", pady=(0, 4))

        row = ttk.Frame(wrap)
        row.pack(fill="x")

        entry = ttk.Entry(row)
        entry.insert(0, default_val)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ttk.Button(
            row,
            text="Browse",
            width=10,
            command=lambda: self._browse_folder(entry),
            cursor="hand2",
        ).pack(side="right")

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
            entry.delete(0, tk.END)
            entry.config(foreground=COLORS.text_main)
            entry.insert(0, path)
            logger.debug(f"Selected folder: {path}")

    # ------------------------------------------------------------------
    # Public getters
    # ------------------------------------------------------------------

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

    def get_start_date(self) -> Optional[date]:
        """Get the start date, or None if unavailable or invalid."""
        if not self.start_date_picker:
            return None
        try:
            return self.start_date_picker.get_date()
        except (ValueError, AttributeError):
            logger.warning("Could not parse start date from picker")
            return None

    def get_end_date(self) -> Optional[date]:
        """Get the end date, or None if unavailable or invalid."""
        if not self.end_date_picker:
            return None
        try:
            return self.end_date_picker.get_date()
        except (ValueError, AttributeError):
            logger.warning("Could not parse end date from picker")
            return None

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
        state: Literal["normal", "disabled"] = "normal" if enabled else "disabled"
        for widget in (self.day_entry, self.night_entry):
            if widget is not None:
                try:
                    widget.config(state=state)
                except Exception as e:
                    logger.debug(f"Could not set entry state: {e}")
        for picker in (self.start_date_picker, self.end_date_picker):
            if picker is not None:
                try:
                    picker.config(state=state)
                except Exception as e:
                    logger.debug(f"Could not set date picker state: {e}")
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
