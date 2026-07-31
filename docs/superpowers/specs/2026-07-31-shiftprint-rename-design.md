# ShiftPrint Rename and Icon — Design

Date: 2026-07-31
Status: Approved

## Problem

"ShiftPress" does not say what the application does. "Press" reads ambiguously —
printing press, press a button, compress — so someone meeting the name cold
cannot tell it prints shift schedules. The name is renamed to **ShiftPrint**,
which states both the domain (shift) and the action (print).

The current icon has the same problem in a different form. It was designed in
March 2026 (`docs/plans/2026-03-03-icon-and-rename-design.md`) as a calendar page
with a press arrow in amber `#F59E0B` on zinc-900 — a palette that predates the
current design system and no longer matches it. Rendered at 16px, its date rows
blur into a grey smear and the arrow nearly disappears.

## Decisions

1. **Name: ShiftPrint.** Chosen over `PrintShift` (buries the domain behind the
   verb, and "print shift" invites a Shift-key misreading) and `SchedulePrint`
   (drops "shift", the app's defining concept of independent Day and Night).
2. **Full rename, including the data directory,** with config migration so no
   operator loses their template folders or printer.
3. **Icon composition: the pair leads.** Two offset sheets, Night behind, Day in
   front. Selected by the user over a single split page carrying a print arrow.
   The pair states the product's actual differentiator — the two shifts are
   independent objects, not one divided page.
4. **`DESIGN.md` gains an Icon section.** Explicitly approved as a durable system
   change, which impeccable requires for an extension of an established world.

### Process note

Impeccable classifies this as extension of an established world, not creation of
a new one, so the visual world is inherited rather than reopened: the icon uses
existing `DESIGN.md` tokens and adds no new colour. Per `visualize.md`, three
compositional options were rendered and put before the user at one approval
point. The approved comp is `.impeccable/mocks/icon-2-two-sheets-approved.png`.

## Icon specification

Geometry is expressed as a fraction of the canvas so it is resolution
independent. The source renders at 1024×1024 and downsamples per size.

| Element | Value |
| --- | --- |
| Ground tile | `#16171A`, full bleed, corner radius `0.12` |
| Night sheet | `#38BDF8`, origin `(0.195, 0.155)`, size `0.42 × 0.50`, radius `0.035` |
| Day sheet | `#F2B340`, origin `(0.385, 0.345)`, size `0.42 × 0.50`, radius `0.035` |
| Separation gap | `0.035` of canvas, drawn in ground colour behind the Day sheet |

The tile radius follows `DESIGN.md`'s Shapes rule ("square or gently softened
corners; avoid large radii"). An initial 22% radius was rejected against that
rule. The system is flat: no shadow, gradient, or glow, per the Flat Native Rule.

The gap and offset are not arbitrary. Three separations were rendered and read at
true 16px: at `0.020` the Night sheet collapses to a sliver, at `0.050` it
reduces to a bare corner, and `0.035` keeps both sheets distinct at 16px while
still reading as an overlapping pair at full size.

### Outputs

- `icon.png` — 1024×1024 RGBA
- `icon.ico` — 16, 24, 32, 48, 64, 128, 256 px

These are the same filenames and the same size set as today, so no build
configuration changes.

### What must not be literalized

The comp is a 512px reference, not a trace target. If the production pipeline
shifts geometry, re-verify legibility at 16px rather than pixel-matching the
comp. No shadow or gradient may be introduced during production.

### Generation and dependency

The icon is drawn geometry, not a sourced raster, so it is reproducible from
code. A script at `tools/make_icon.py` renders both outputs from the table above,
and the generated `icon.png` and `icon.ico` are committed as assets. Anyone can
regenerate them without reverse-engineering a binary.

This requires **Pillow**, which the project does not currently depend on. Pillow
is added to `requirements-dev.txt` only — never `requirements.txt`. The running
application loads `icon.ico` through Tkinter and needs no imaging library at
runtime; Pillow is needed to regenerate the asset and to run the icon tests
below, both of which are development concerns.

## Rename inventory

Occurrences of `ShiftPress` / `shiftpress`, verified by scan:

| File | Occurrences |
| --- | --- |
| `src/__init__.py` | 7 |
| `src/main.py` | 6 |
| `src/ui.py` | 5 |
| `src/app_paths.py` | 4 |
| `src/logger.py` | 4 |
| `src/constants.py` | 2 |
| `src/config.py`, `src/path_validation.py`, `src/print_manifest.py`, `src/scheduler.py`, `src/word_processor.py` | 1 each |
| `main.py` | 2 |
| `.github/workflows/build.yml` | 4 |
| `setup.bat` | 1 |
| `start_app.bat` | 2 |
| `tests/test_logger.py` | 10 |
| `tests/test_main.py` | 6 |
| `tests/test_app_paths.py` | 2 |
| `tests/__init__.py` | 1 |

Identity-bearing constants:

```
src/app_paths.py:12   APP_DIRNAME  = "ShiftPress"      ->  "ShiftPrint"
src/constants.py:88   LOG_FILENAME = "shiftpress.log"  ->  "shiftprint.log"
```

`CONFIG_FILENAME` is `config.json` and does not carry the name; it is unchanged.

Also updated: the window title, the PyInstaller `--name` in the workflow, and the
prose name in `README.md`, `DESIGN.md`, `PRODUCT.md`, `docs/windows-smoke-test.md`,
and `.impeccable/surfaces/src-ui-py.md`.

`PRODUCT.md`'s brand commitment "Preserve the ShiftPress name" becomes "Preserve
the ShiftPrint name". Leaving it would contradict the code.

### Historical documents are not rewritten

`docs/plans/2026-03-03-icon-and-rename-design.md` and everything under
`docs/superpowers/specs/` and `docs/superpowers/plans/` are dated records of
decisions made under the old name. They are left as written. Retroactively
editing them would falsify the history of why the app is named what it is. The
new spec and plan use the new name; the old ones keep theirs.

## Config migration

Renaming `APP_DIRNAME` points `get_data_dir()` at `%APPDATA%\ShiftPrint`, which
is empty for every existing operator. Without migration they silently lose their
saved template folders and printer selection on first launch after upgrading.

`ConfigManager` already solves this shape of problem: it detects a config at a
legacy path, loads it, saves it to the current path, and renames the original so
it is not picked up again. That mechanism is extended rather than duplicated.

Design:

- `app_paths.get_legacy_data_dir()` returns the previous per-user directory
  (`%APPDATA%\ShiftPress` on Windows, `~/.shiftpress` elsewhere).
- On load, when the current config file does not exist, `ConfigManager` checks
  the legacy data directory before falling back to defaults.
- A legacy config found there is loaded, written to the new path, and the
  original renamed to `config.json.migrated`, matching existing behaviour.
- The existing working-directory legacy check is preserved; the new check is
  additive, so both upgrade paths work.
- Migration failures are logged and fall back to defaults. A failed migration
  must never prevent the app from starting.

Log files are not migrated. They are diagnostic, rotate on their own, and the
old file remains readable in the old directory.

## Testing

Test-driven, following the existing suite's conventions.

| Area | Test |
| --- | --- |
| Migration | a legacy-directory config is loaded when the new path is empty |
| Migration | the legacy file is renamed so it is not re-migrated |
| Migration | an existing new-path config wins over a legacy one |
| Migration | an unreadable legacy config falls back to defaults without raising |
| Paths | `get_data_dir()` and `get_legacy_data_dir()` differ on both platforms |
| Icon | `icon.ico` contains exactly the seven required sizes |
| Icon | `icon.png` is 1024×1024 RGBA |
| Name | no `ShiftPress` occurrence remains outside historical docs |

Regression bar: the full suite stays green, `black --check`, `mypy src`, and
`pylint src --fail-under=8.0` stay clean, and both CI jobs pass — including
`windows-test`, which exercises the real pywin32 path where `%APPDATA%`
resolution actually runs.

## Out of scope

- **`gh repo rename`** and the local folder rename. Both are outward-facing, and
  renaming the working directory would move this session out from under itself.
  They are done last, deliberately, with the user present.
- **Version bump.** The rename does not change `__version__`; that is a separate
  release decision.
- **Any UI change beyond the window title.** The interface keeps its current
  layout, copy, and behaviour.
