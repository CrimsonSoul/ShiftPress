# ShiftPress

ShiftPress is a Windows desktop app that batch-prints shift schedule templates via Microsoft Word COM automation.

![Platform](https://img.shields.io/badge/platform-Windows-0a7ea4) ![Language](https://img.shields.io/badge/language-Python%203.12-2ea043) ![UI](https://img.shields.io/badge/ui-Tkinter%2Fttk-4b5563) ![Automation](https://img.shields.io/badge/automation-Word%20COM-1f6feb)

## Snapshot

- Production-focused Word automation: open, replace, print, and close with cleanup safeguards
- Domain logic handles complex monthly rotation scheduling (e.g. "third Thursday" patterns)
- Defensive workflow with preflight checks, per-document retry paths, and CSV failure reporting
- Modular architecture with strong unit-test coverage and static quality gates
- Packaged as a single-file executable for non-technical end users via PyInstaller

## Preview

![Main window](docs/screenshots/main.png)

## Core Features

- Batch print processing for date ranges across day/night template folders
- Date replacement automation with optional header/footer-only mode
- Template path, printer, and date-range preflight validation before any processing begins
- Per-document retry handling for transient COM errors with structured failure logging
- Cancelable background processing with responsive UI progress updates
- Timestamped CSV failure reports for audit and retry workflows

## Architecture

- `src/main.py` — orchestration and workflow control
- `src/ui.py` — Tkinter/ttk interface layer
- `src/word_processor.py` — Word COM automation lifecycle (open, replace, print, close)
- `src/scheduler.py` — date resolution and template path logic
- `src/config.py` — config management
- `src/path_validation.py` — path traversal and filename safety checks

## Tech Stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.12 |
| UI | Tkinter/ttk |
| Office integration | pywin32 (Word COM) |
| Date picker | tkcalendar |
| Testing | pytest + pytest-cov |
| Quality | black + mypy + pylint |
| Packaging | PyInstaller |

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Windows helper scripts:

- `setup.bat` — installs all dependencies into a virtualenv
- `start_app.bat` — activates the environment and launches the app

## Quality and Testing

```bash
pip install -r requirements-dev.txt
pytest                           # run test suite with coverage
black --check src tests          # formatting check
mypy src                         # type checking
pylint src --fail-under=8.0      # linting gate
```

The test suite mocks all Windows-only modules so it can run on any platform in CI.

## Security

- Word documents open in read-only mode during processing; originals are never modified
- Word macros are force-disabled on every document open
- Path validation blocks traversal outside configured template root directories
- Date range limits prevent runaway batch operations
- Config writes are atomic; all operations are logged with structured timestamps

## Project Layout

- `main.py` — top-level entry point
- `src/` — application modules (controller, UI, scheduler, COM processor, config, validation)
- `tests/` — unit tests and module fixtures
- `.github/workflows/build.yml` — Windows build and release workflow via PyInstaller

## License

MIT (see `LICENSE`)
