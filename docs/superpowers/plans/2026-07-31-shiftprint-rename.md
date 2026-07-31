# ShiftPrint Rename and Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the application from ShiftPress to ShiftPrint, migrate existing operators' saved config to the new data directory, and ship an icon that matches the current design system.

**Architecture:** Five tasks in dependency order. The icon is independent and goes first. Then the identity constants change together with a legacy-directory accessor, then the config migration that consumes it, then the bulk textual rename, then prose docs. Historical design documents are deliberately left under the old name.

**Tech Stack:** Python 3.12, Pillow (new dev-only dependency, for icon generation and icon tests), Tkinter/ttk, pytest, black, mypy, pylint, PyInstaller, GitHub Actions.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-31-shiftprint-rename-design.md`. Read it before starting.
- Work directly on the current branch (`test`). No worktree.
- New name is exactly `ShiftPrint` (capital S, capital P). Lowercase form is `shiftprint`.
- All existing tests must stay green. Run the full suite before every commit.
- `black --check src tests` clean. Run `black src tests` before committing.
- `mypy src` reports no issues. `pylint src --fail-under=8.0` passes.
- Python 3.12 required. The system `python3` on this host is 3.9 and will not work. Use `.venv/bin/*`, which already exists.
- Pillow goes in `requirements-dev.txt` **only**. Never `requirements.txt` — the app loads `icon.ico` through Tkinter and needs no imaging library at runtime.
- **Never rewrite historical documents.** `docs/plans/**` and `docs/superpowers/**` (except files this plan creates) keep the old name. They are dated records of decisions made under it.
- **`src/app_paths.py` must retain the literal `"ShiftPress"`** as the legacy directory name. A blanket find-and-replace across it silently breaks migration.

---

### Task 1: Icon generation and assets

The current icon is amber-on-zinc from a palette that predates the design system, and its detail dies at 16px. Replace it with the approved composition: two offset sheets, Night behind, Day in front.

**Files:**
- Create: `tools/make_icon.py`
- Create: `tests/test_icon.py`
- Modify: `requirements-dev.txt`
- Replace: `icon.png`, `icon.ico`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tools/make_icon.py` exposing `render(size: int = 1024) -> PIL.Image.Image` and `main() -> None`. Nothing in `src/` imports it.

- [ ] **Step 1: Add Pillow as a dev dependency**

In `requirements-dev.txt`, under the `# Build tools` section, add:

```
# Icon generation and icon asset tests (not needed at runtime)
pillow>=12.3.0
```

Then install it:

```bash
.venv/bin/pip install -r requirements-dev.txt
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_icon.py`:

```python
"""The shipped icon assets must stay in spec and in palette."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_ICO_SIZES = {
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
}


def test_icon_png_is_full_resolution_rgba():
    """PyInstaller and the Tk fallback both read the PNG master."""
    with Image.open(ROOT / "icon.png") as im:
        assert im.size == (1024, 1024)
        assert im.mode == "RGBA"


def test_icon_ico_carries_every_windows_size():
    """Windows picks a size per context; a missing one gets a blurry upscale."""
    with Image.open(ROOT / "icon.ico") as ico:
        assert set(ico.info["sizes"]) == REQUIRED_ICO_SIZES


def test_icon_uses_the_committed_shift_tokens():
    """The icon shares the app's palette rather than inventing its own."""
    with Image.open(ROOT / "icon.png") as im:
        colors = {c for _, c in im.convert("RGB").getcolors(maxcolors=1_000_000)}

    assert (0x38, 0xBD, 0xF8) in colors  # night_accent
    assert (0xF2, 0xB3, 0x40) in colors  # day_accent
    assert (0x16, 0x17, 0x1A) in colors  # window charcoal ground
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_icon.py -v --no-cov`
Expected: `test_icon_uses_the_committed_shift_tokens` FAILS — the current icon is amber `#F59E0B` on zinc-900 `#18181B`, so neither the Night token nor the charcoal ground is present.

- [ ] **Step 4: Write the generator**

Create `tools/make_icon.py`:

```python
"""Regenerate the ShiftPrint application icon.

Geometry is expressed as a fraction of the canvas, so the mark is resolution
independent. The values come from reading the mark at true 16px: a 0.020 gap
collapses the Night sheet to a sliver and 0.050 reduces it to a bare corner.

Requires Pillow, which is a development dependency only. The running
application loads icon.ico through Tkinter and needs no imaging library.

Usage:
    .venv/bin/python tools/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = 1024
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

GROUND = "#16171A"  # window charcoal
NIGHT = "#38BDF8"   # night_accent
DAY = "#F2B340"     # day_accent

TILE_RADIUS = 0.12   # "gently softened corners" per DESIGN.md Shapes
SHEET_RADIUS = 0.035
SHEET_W = 0.42
SHEET_H = 0.50
OFFSET = 0.19
GAP = 0.035


def render(size: int = CANVAS) -> Image.Image:
    """Draw the icon at *size* square.

    Args:
        size: Edge length in pixels.

    Returns:
        An RGBA image of the mark.
    """
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, s, s], radius=int(s * TILE_RADIUS), fill=GROUND)

    r = int(s * SHEET_RADIUS)
    nx0 = s * (0.5 - SHEET_W / 2 - OFFSET / 2)
    ny0 = s * (0.5 - SHEET_H / 2 - OFFSET / 2)
    nx1, ny1 = nx0 + s * SHEET_W, ny0 + s * SHEET_H
    dx0, dy0 = nx0 + s * OFFSET, ny0 + s * OFFSET
    dx1, dy1 = dx0 + s * SHEET_W, dy0 + s * SHEET_H

    # Night sheet sits behind, up and left.
    d.rounded_rectangle([nx0, ny0, nx1, ny1], radius=r, fill=NIGHT)
    # Ground-coloured gap keeps the two sheets legible at 16px.
    g = s * GAP
    d.rounded_rectangle([dx0 - g, dy0 - g, dx1 + g, dy1 + g], radius=r, fill=GROUND)
    # Day sheet sits in front, down and right.
    d.rounded_rectangle([dx0, dy0, dx1, dy1], radius=r, fill=DAY)
    return im


def main() -> None:
    """Write icon.png and icon.ico to the repository root."""
    root = Path(__file__).resolve().parent.parent
    master = render()
    master.save(root / "icon.png")
    master.save(root / "icon.ico", sizes=[(n, n) for n in ICO_SIZES])
    print(f"wrote {root / 'icon.png'} and {root / 'icon.ico'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Generate the assets**

Run: `.venv/bin/python tools/make_icon.py`
Expected: prints the two written paths.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_icon.py -v --no-cov`
Expected: 3 passed.

- [ ] **Step 7: Confirm the mark survives 16px**

Run:

```bash
.venv/bin/python -c "
from PIL import Image
im = Image.open('icon.png').resize((16,16), Image.LANCZOS).convert('RGB')
cols = {c for _, c in im.getcolors(maxcolors=100000)}
def near(t, cs, tol=60):
    return any(sum(abs(a-b) for a,b in zip(t,c)) < tol for c in cs)
print('night visible at 16px:', near((0x38,0xBD,0xF8), cols))
print('day   visible at 16px:', near((0xF2,0xB3,0x40), cols))
"
```

Expected: both `True`. If either is `False`, the sheets have merged and the `GAP` value needs revisiting before continuing.

- [ ] **Step 8: Run the full suite and gates**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/black src tests && .venv/bin/mypy src && .venv/bin/pylint src --fail-under=8.0
```
Expected: 242 passed (239 existing + 3 new); all gates clean. `tools/` is outside `src` and `tests`, so it is not linted or type-checked by the gates.

- [ ] **Step 9: Commit**

```bash
git add tools/make_icon.py tests/test_icon.py requirements-dev.txt icon.png icon.ico
git commit -m "feat: ship an icon that matches the design system"
```

---

### Task 2: Identity constants and the legacy data directory

`APP_DIRNAME` drives `%APPDATA%\ShiftPress`. Renaming it points the app at an empty directory, so the old location must remain reachable for Task 3's migration.

**Files:**
- Modify: `src/app_paths.py` (whole file)
- Modify: `src/constants.py:88` (`LOG_FILENAME`)
- Test: `tests/test_app_paths.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `app_paths.APP_DIRNAME = "ShiftPrint"`, `app_paths.LEGACY_APP_DIRNAME = "ShiftPress"`, `get_data_dir() -> Path`, and `get_legacy_data_dir() -> Path`. Task 3 consumes `get_legacy_data_dir`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_app_paths.py`, inside `class TestGetDataDir`:

```python
    def test_legacy_dir_differs_from_current_on_windows(self):
        """Migration needs both locations to be reachable and distinct."""
        with patch("os.name", "nt"), patch.dict(
            os.environ, {"APPDATA": "C:\\Users\\Test\\AppData\\Roaming"}, clear=True
        ):
            assert get_data_dir().name == "ShiftPrint"
            assert get_legacy_data_dir().name == "ShiftPress"

    def test_legacy_dir_differs_from_current_elsewhere(self):
        """The non-Windows dev path also has to be distinguishable."""
        with patch("os.name", "posix"), patch(
            "pathlib.Path.home", return_value=Path("/home/testuser")
        ):
            assert str(get_data_dir()) == "/home/testuser/.shiftprint"
            assert str(get_legacy_data_dir()) == "/home/testuser/.shiftpress"
```

Update the import at the top of `tests/test_app_paths.py` to include the new accessor:

```python
from src.app_paths import get_data_dir, get_legacy_data_dir
```

Confirm `os`, `Path`, and `patch` are already imported in that file; add any that are missing.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_app_paths.py -k legacy_dir -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'get_legacy_data_dir'`.

- [ ] **Step 3: Rewrite `src/app_paths.py`**

Replace the whole file with:

```python
"""App-specific filesystem paths.

The app writes user-specific state (config/logs) to an OS-appropriate per-user
directory by default, rather than the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path


APP_DIRNAME = "ShiftPrint"
APP_DOTNAME = ".shiftprint"

# The app was named ShiftPress before 2026-07-31. Existing installs still have
# their config here, so the old location stays reachable for migration.
LEGACY_APP_DIRNAME = "ShiftPress"
LEGACY_APP_DOTNAME = ".shiftpress"


def _data_dir_for(app_dirname: str, dotname: str) -> Path:
    """Return the per-user directory for one app identity.

    Args:
        app_dirname: Windows directory name under %APPDATA%.
        dotname: Dot-directory name used on other platforms.

    Returns:
        Path to the per-user data directory. Not created.
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / app_dirname
        return Path.home() / app_dirname

    # Non-Windows environments are primarily for development/tests.
    return Path.home() / dotname


def get_data_dir() -> Path:
    """Return the per-user data directory for the app.

    The directory is *not* created by this function; callers are responsible
    for calling ``mkdir()`` if needed.

    Windows: %APPDATA%\\ShiftPrint (fallback to %LOCALAPPDATA%)
    Other OSes (dev/test): ~/.shiftprint

    Returns:
        Path to the per-user data directory.
    """
    return _data_dir_for(APP_DIRNAME, APP_DOTNAME)


def get_legacy_data_dir() -> Path:
    """Return the per-user data directory used before the ShiftPrint rename.

    Returns:
        Path to the pre-rename data directory. Not created.
    """
    return _data_dir_for(LEGACY_APP_DIRNAME, LEGACY_APP_DOTNAME)
```

- [ ] **Step 4: Rename the log file**

In `src/constants.py`, change:

```python
LOG_FILENAME: Final = "shiftpress.log"
```

to:

```python
LOG_FILENAME: Final = "shiftprint.log"
```

- [ ] **Step 5: Update the existing non-Windows path test**

In `tests/test_app_paths.py`, the existing `test_non_windows` asserts the old dot-directory. Change its docstring and assertion:

```python
        """Should use ~/.shiftprint on non-Windows."""
```

```python
            assert str(result) == "/home/testuser/.shiftprint"
```

Also update `tests/test_logger.py:52`, which asserts the log filename:

```python
        assert log_files[0].name == "shiftprint.log"
```

- [ ] **Step 6: Run the full suite and gates**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/black src tests && .venv/bin/mypy src && .venv/bin/pylint src --fail-under=8.0
```
Expected: 244 passed; all gates clean.

- [ ] **Step 7: Commit**

```bash
git add src/app_paths.py src/constants.py tests/test_app_paths.py tests/test_logger.py
git commit -m "feat: point the data directory at ShiftPrint and keep the old one reachable"
```

---

### Task 3: Migrate config from the pre-rename data directory

Without this, every existing operator silently loses their template folders and printer selection on first launch after upgrading.

**Files:**
- Modify: `src/config.py` (imports, `__init__`, `load`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `app_paths.get_legacy_data_dir() -> Path` from Task 2.
- Produces: `ConfigManager._legacy_data_config_path: Path` and `ConfigManager._migrate_from(legacy_path: Path) -> Optional[AppConfig]`. The existing `_legacy_config_path` attribute keeps its name — `tests/test_config.py::test_legacy_migration` sets it directly.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`, inside `class TestConfigManager`:

```python
    def test_migrates_config_from_pre_rename_data_dir(self, tmp_path):
        """An operator upgrading from ShiftPress keeps their saved setup."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "config.json").write_text(
            json.dumps({"day_folder": "/old/day", "printer_name": "OldPrinter"})
        )

        manager = ConfigManager()
        manager.config_path = tmp_path / "current" / "config.json"
        manager._legacy_data_config_path = legacy_dir / "config.json"
        manager._legacy_config_path = tmp_path / "nonexistent-cwd" / "config.json"
        manager._allow_legacy_migration = True

        config = manager.load()

        assert config.day_folder == "/old/day"
        assert config.printer_name == "OldPrinter"
        assert manager.config_path.exists()

    def test_pre_rename_config_is_renamed_after_migration(self, tmp_path):
        """The old file must not be re-migrated over a later edit."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        legacy_file = legacy_dir / "config.json"
        legacy_file.write_text(json.dumps({"day_folder": "/old/day"}))

        manager = ConfigManager()
        manager.config_path = tmp_path / "current" / "config.json"
        manager._legacy_data_config_path = legacy_file
        manager._legacy_config_path = tmp_path / "nonexistent-cwd" / "config.json"
        manager._allow_legacy_migration = True

        manager.load()

        assert not legacy_file.exists()
        assert (legacy_dir / "config.json.migrated").exists()

    def test_existing_config_wins_over_pre_rename_one(self, tmp_path):
        """Migration must never overwrite a config the operator already has."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "config.json").write_text(json.dumps({"day_folder": "/old/day"}))
        new_dir = tmp_path / "current"
        new_dir.mkdir()
        (new_dir / "config.json").write_text(json.dumps({"day_folder": "/current/day"}))

        manager = ConfigManager()
        manager.config_path = new_dir / "config.json"
        manager._legacy_data_config_path = legacy_dir / "config.json"
        manager._allow_legacy_migration = True

        assert manager.load().day_folder == "/current/day"

    def test_unreadable_pre_rename_config_falls_back_to_defaults(self, tmp_path):
        """A corrupt old config must not stop the app from starting."""
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "config.json").write_text("{ not valid json")

        manager = ConfigManager()
        manager.config_path = tmp_path / "current" / "config.json"
        manager._legacy_data_config_path = legacy_dir / "config.json"
        manager._legacy_config_path = tmp_path / "nonexistent-cwd" / "config.json"
        manager._allow_legacy_migration = True

        config = manager.load()

        assert config.day_folder == ""
        assert config.printer_name == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -k "pre_rename" -v --no-cov`
Expected: FAIL with `AttributeError: 'ConfigManager' object has no attribute '_legacy_data_config_path'`.

- [ ] **Step 3: Import the legacy directory accessor**

In `src/config.py`, change:

```python
from .app_paths import get_data_dir
```

to:

```python
from .app_paths import get_data_dir, get_legacy_data_dir
```

- [ ] **Step 4: Register the second legacy location**

In `ConfigManager.__init__`, immediately after the existing `self._legacy_config_path` line, add:

```python
        self._legacy_data_config_path = get_legacy_data_dir() / CONFIG_FILENAME
```

- [ ] **Step 5: Extract the migration into one reusable method**

Add these two methods to `ConfigManager`, directly above `load`:

```python
    def _legacy_paths(self) -> tuple[Path, ...]:
        """Older config locations to check, most recent first."""
        return (self._legacy_data_config_path, self._legacy_config_path)

    def _migrate_from(self, legacy_path: Path) -> Optional[AppConfig]:
        """Adopt a config from an older location.

        Args:
            legacy_path: Candidate config file from a previous app version.

        Returns:
            The migrated config, or ``None`` when *legacy_path* is absent or
            unreadable.  A failed migration must never stop the app starting.
        """
        if not legacy_path.exists():
            return None

        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                config = AppConfig.from_dict(json.load(f))
        except Exception as e:
            logger.warning(f"Could not load legacy config at {legacy_path}: {e}")
            return None

        logger.info(
            f"Configuration loaded from legacy path {legacy_path}; "
            f"migrating to {self.config_path}"
        )
        try:
            self.save(config)
        except Exception as e:
            logger.warning(f"Could not migrate legacy config to {self.config_path}: {e}")

        # Rename so the next launch does not migrate over a newer edit.
        try:
            migrated = legacy_path.with_suffix(".json.migrated")
            legacy_path.rename(migrated)
            logger.info(f"Legacy config renamed to {migrated}")
        except Exception as e:
            logger.debug(f"Could not rename legacy config: {e}")

        return config
```

- [ ] **Step 6: Route `load` through it**

In `ConfigManager.load`, replace the entire `if not self.config_path.exists():` block — from that line down to and including its `return self._config` — with:

```python
        if not self.config_path.exists():
            # Backward-compatibility: earlier versions stored config under the
            # ShiftPress data directory, and older ones in the working directory.
            if self._allow_legacy_migration:
                for legacy_path in self._legacy_paths():
                    migrated = self._migrate_from(legacy_path)
                    if migrated is not None:
                        self._config = migrated
                        return self._config

            logger.info(f"Config file not found at {self.config_path}, using defaults")
            self._config = AppConfig()
            return self._config
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v --no-cov`
Expected: all pass, including the pre-existing `test_legacy_migration`, which still exercises the working-directory path.

- [ ] **Step 8: Run the full suite and gates**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/black src tests && .venv/bin/mypy src && .venv/bin/pylint src --fail-under=8.0
```
Expected: 248 passed; all gates clean.

- [ ] **Step 9: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: carry saved config across the ShiftPrint rename"
```

---

### Task 4: Rename across code, tests, workflow, and scripts

**Files:**
- Modify: every tracked `.py`, `.bat`, and `.yml` outside `docs/`, **except `src/app_paths.py` and `tests/test_app_paths.py`**
- Modify: `.github/workflows/build.yml` (PyInstaller `--name`)

**Interfaces:**
- Consumes: nothing.
- Produces: no new symbols. The window title becomes `ShiftPrint`; the built artifact becomes `ShiftPrint.exe`.

- [ ] **Step 1: Rename everything except the two legacy-bearing files**

Both exclusions are deliberate and load-bearing. `src/app_paths.py` must keep the literal `"ShiftPress"` for `LEGACY_APP_DIRNAME`, and `tests/test_app_paths.py` asserts that exact literal. A blanket replace would rewrite both sides in lockstep, so the assertion would still pass while the migration quietly pointed at the wrong directory — a green suite hiding a broken upgrade. Task 2 already left both files correct.

```bash
FILES=$(git ls-files '*.py' '*.bat' '*.yml' \
  | grep -v '^docs/' \
  | grep -v '^src/app_paths.py$' \
  | grep -v '^tests/test_app_paths.py$')
echo "$FILES"
sed -i '' -e 's/ShiftPress/ShiftPrint/g' -e 's/shiftpress/shiftprint/g' -e 's/SHIFTPRESS/SHIFTPRINT/g' $FILES
```

- [ ] **Step 2: Verify the legacy name survived where it must**

Run:

```bash
grep -n "LEGACY_APP_DIRNAME\|LEGACY_APP_DOTNAME" src/app_paths.py
```

Expected: `LEGACY_APP_DIRNAME = "ShiftPress"` and `LEGACY_APP_DOTNAME = ".shiftpress"`. If either now reads `ShiftPrint`, the exclusion failed — restore this file with `git checkout src/app_paths.py`, redo Task 2's Step 3, and rerun Step 1 with the exclusion in place.

- [ ] **Step 3: Confirm no code-side occurrences remain**

Run:

```bash
grep -rn "ShiftPress\|shiftpress" --include="*.py" --include="*.bat" --include="*.yml" . \
  | grep -v '^\./docs/' | grep -v '\.venv' \
  | grep -v '^\./src/app_paths.py' | grep -v '^\./tests/test_app_paths.py'
```

Expected: no output. The only legitimate remaining occurrences are the legacy constants in `src/app_paths.py` and the assertions covering them in `tests/test_app_paths.py`; both are filtered above. Any other hit is a miss.

Then confirm those two files still say what they should:

```bash
grep -c "ShiftPress" src/app_paths.py tests/test_app_paths.py
```

Expected: `src/app_paths.py:1` and `tests/test_app_paths.py:1` — one legacy literal each. A `0` means the exclusion failed.

- [ ] **Step 4: Run the full suite and gates**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/black src tests && .venv/bin/mypy src && .venv/bin/pylint src --fail-under=8.0
```
Expected: 248 passed; all gates clean. The suite covers the renamed logger tag (`_shiftprint`) and default logger name (`shiftprint`) because `sed` rewrote both the source and its assertions together.

- [ ] **Step 5: Confirm the app still launches under the new identity**

Run:

```bash
.venv/bin/python -c "
import tkinter as tk
from datetime import date
from src.ui import ScheduleAppUI
from src.app_paths import get_data_dir, get_legacy_data_dir
root = tk.Tk()
ui = ScheduleAppUI(root, today=date(2026, 7, 31))
root.update_idletasks()
print('window title :', root.title())
print('data dir     :', get_data_dir())
print('legacy dir   :', get_legacy_data_dir())
root.destroy()
" 2>&1 | grep -v 'win32print'
```

Expected: title `ShiftPrint`, data dir ending `.shiftprint`, legacy dir ending `.shiftpress`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename ShiftPress to ShiftPrint across code and build"
```

---

### Task 5: Documentation, brand commitment, and the icon record

**Files:**
- Modify: `README.md`, `PRODUCT.md`, `DESIGN.md`, `docs/windows-smoke-test.md`, `.impeccable/surfaces/src-ui-py.md`

**Interfaces:**
- Consumes: the icon geometry from Task 1.
- Produces: no code symbols.

- [ ] **Step 1: Rename in prose docs only**

`docs/plans/**` and `docs/superpowers/**` are excluded: they are dated records of decisions made under the old name.

```bash
sed -i '' -e 's/ShiftPress/ShiftPrint/g' -e 's/shiftpress/shiftprint/g' \
  README.md PRODUCT.md DESIGN.md docs/windows-smoke-test.md .impeccable/surfaces/src-ui-py.md
```

- [ ] **Step 2: Update the brand commitment**

`PRODUCT.md`'s commitment now reads "Preserve the ShiftPrint name" after Step 1, which is correct. Directly below that bullet, replace the icon bullet:

```markdown
- Existing application icons are available at `icon.ico` and `icon.png`.
```

with:

```markdown
- Application icons live at `icon.ico` and `icon.png`, regenerated from
  `tools/make_icon.py`; see the Icon section of DESIGN.md.
```

- [ ] **Step 3: Record the icon in DESIGN.md**

This is the durable system change the user approved. In `DESIGN.md`, insert this section immediately before `## Typography`:

```markdown
## Icon

**Concept: the pair leads.** Two offset sheets — Night behind, Day in front —
on a charcoal ground. The mark states what the app is for: two shift schedules,
chosen independently.

Geometry is a fraction of the canvas, so the mark is resolution independent.

| Element | Value |
| --- | --- |
| Ground tile | `#16171A`, full bleed, corner radius `0.12` |
| Night sheet | `#38BDF8`, origin `(0.195, 0.155)`, size `0.42 × 0.50`, radius `0.035` |
| Day sheet | `#F2B340`, origin `(0.385, 0.345)`, size `0.42 × 0.50`, radius `0.035` |
| Separation gap | `0.035` of canvas, in ground colour, behind the Day sheet |

Outputs are `icon.png` at 1024×1024 and `icon.ico` at 16/24/32/48/64/128/256,
generated by `tools/make_icon.py`.

**The 16px Rule.** The separation gap exists so both sheets stay readable in the
Windows taskbar. At `0.020` the Night sheet collapses to a sliver; at `0.050` it
reduces to a bare corner. Any change to the geometry must be re-read at true
16px, not judged at full size.

The icon takes no colour outside this system and carries no shadow or gradient,
per the Flat Native Rule.
```

- [ ] **Step 4: Record the approved comp in the surface brief**

In `.impeccable/surfaces/src-ui-py.md`, append to the `## Resolved Decisions` section:

```markdown

The application icon was resolved as "the pair leads": two offset sheets, Night
behind and Day in front. Approved comp:
`.impeccable/mocks/icon-2-two-sheets-approved.png`.
```

- [ ] **Step 5: Verify only historical documents still carry the old name**

Run:

```bash
grep -rln "ShiftPress\|shiftpress" --include="*.md" . | grep -v '\.venv' | sort
```

Expected: exactly `./docs/plans/2026-03-03-icon-and-rename-design.md`, `./docs/superpowers/plans/2026-07-31-review-defect-remediation.md`, `./docs/superpowers/specs/2026-07-30-independent-shift-printing-design.md`, `./docs/superpowers/specs/2026-07-31-review-defect-remediation-design.md`, and `./docs/superpowers/specs/2026-07-31-shiftprint-rename-design.md` (which quotes the old name while describing the change). Anything else is a miss.

- [ ] **Step 6: Run the full suite and gates**

Run:
```bash
.venv/bin/pytest -q && .venv/bin/black --check src tests && .venv/bin/mypy src && .venv/bin/pylint src --fail-under=8.0
```
Expected: 248 passed; all gates clean.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "docs: rename to ShiftPrint and record the icon in the design system"
```

---

## Final verification

```bash
.venv/bin/pytest -q
.venv/bin/black --check src tests && .venv/bin/mypy src && .venv/bin/pylint src --fail-under=8.0
.venv/bin/python tools/make_icon.py && .venv/bin/pytest tests/test_icon.py -q --no-cov
```

Expected: 248 passed, all gates clean, icon regenerates deterministically and its tests still pass.

Then push to `test` and confirm both CI jobs pass — `windows-test` matters here, because it is the only place `%APPDATA%` resolution runs against real pywin32.

Report the final test count, coverage percentage, and pylint score.

## Held back deliberately

These are **not** part of this plan. They are outward-facing, and the folder rename would move the working directory out from under an in-progress session. Do them last, with the user present, or in a fresh session:

```bash
gh repo rename ShiftPrint
git remote set-url origin https://github.com/CrimsonSoul/ShiftPrint.git
# then, from outside the directory:
mv /Users/ryan/Apps/ShiftPress /Users/ryan/Apps/ShiftPrint
```

GitHub redirects the old URL, so existing clones keep working.
