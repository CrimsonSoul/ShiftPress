# ShiftPress

A Windows desktop utility that batch-prints dated shift schedules from Microsoft
Word templates. Requires Windows, Microsoft Word, and a printer; the native
Tkinter/ttk app uses Python 3.12, pywin32, and tkcalendar.

## Run

Use `setup.bat` to install dependencies and `start_app.bat` to launch, or run:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

1. Open **Setup…**, choose Night/Day template folders and a printer, then
   **Apply**. **Cancel** restores the settings present when Setup opened.
2. Include Night, Day, or both; choose a single date or independent range for
   each. A fresh run defaults to Night today and Day tomorrow.
3. Review **Print scope** and the document count, then print. Preflight checks
   the selected templates before processing starts. **Cancel** stops before the
   next document; an active Word call must finish first.

**Reset run** restores the daily defaults. **How to use** explains the workflow;
keyboard shortcuts are Alt+S for Setup, Alt+P for Print, Alt+H for Help, and
Escape for cancellation.

Templates remain unchanged. Date replacement covers body, header, and footer
story ranges. Printing stops if macros cannot be disabled, the requested
printer cannot be selected, or no supported date text is found. Missing or
ambiguous templates block preflight. Failed documents receive CSV reports.

## Development and releases

Install `requirements-dev.txt` for development. [AGENTS.md](AGENTS.md) owns
verification commands and protected publication/release rules. Non-Windows
tests mock Windows dependencies. Packaged Windows startup is required for
release; real Word COM and physical printing remain unverified until the
[Windows smoke test](docs/windows-smoke-test.md) passes. Release notes disclose
any unavailable physical-print validation.

Each merged `main` push produces a PyInstaller executable artifact named
`ShiftPress-v<version>-<commit>`, retained for seven days. Release versions come
only from `src/__init__.py`; a published release requires a committed bump and
an explicitly authorized Build dispatch on `main` with `create_release` enabled.

Read [PRODUCT.md](PRODUCT.md) for behavior, [DESIGN.md](DESIGN.md) for native UI
rules, and the [surface brief](.impeccable/surfaces/src-ui-py.md) for UI scope.
The controller is `src/main.py`, UI `src/ui.py`, job model
`src/print_manifest.py`, and Word integration `src/word_processor.py`.

MIT licensed; see [LICENSE](LICENSE).
