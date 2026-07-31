# Review Defect Remediation — Design

Date: 2026-07-31
Status: Approved

## Problem

A frontend-design and backend-functionality review of ShiftPress found fifteen
defects. The quality gates did not catch any of them: 219 tests pass, `black`
and `mypy` are clean, and `pylint` scores 8.85/10. Every defect below was
reproduced against a rendered instance of the UI or against live module code,
not inferred from reading.

Three defects are user-visible on a normal launch (window can clip its own
primary action; saved template paths render as if unconfigured; the manifest
reads "1 schedules"). One defect can silently print the wrong schedule. One
allows a release to ship with failing tests.

## Decisions

Three decisions were open. All three are settled.

1. **Template-name collisions block the run at preflight.** Consistent with the
   existing multi-match `TemplateLookupError` and with product principle 5,
   "Fail before printing when required inputs or templates are unavailable."
   Accepted cost: an operator with a long-standing stray-space duplicate must
   rename a file before printing.
2. **Window sizing is resolved by making both date modes the same height, then
   deriving the window size from content.** This closes the decision the
   Impeccable surface contract (`.impeccable/surfaces/src-ui-py.md`) explicitly
   deferred: "Exact default window dimensions and final token values will be
   resolved against the rendered Tkinter implementation and Windows display
   scaling." Accepted cost: ~26px of quiet space in the single-date card.
3. **The stale screenshot is removed rather than replaced.** A genuine
   replacement cannot be produced from this environment (macOS host, Windows
   target, screen-recording permission denied). Fabricating one is not an
   option. The README Preview section is removed and the capture step is
   recorded in the Windows smoke-test doc.

## Evidence

Measured against a rendered `ScheduleAppUI`:

```
required height (single date)  : 759
required height (date range)   : 785
declared minsize               : (1040, 720)

at the allowed minimum 1040x720:
  print button  top=696 height=61 bottom=757  -> clipped by 37px of 61
  progress bar  bottom=753                    -> clipped by 33px
```

```
_load_config inserts '/tmp/Day'
  day_entry foreground : #B5B7BD  (text_dim — placeholder gray)
  expected             : #F4F4F5  (text_main)
```

```
files : Thursday.docx, Thursday .docx, THIRD Thursday.docx, Thursday Night.docx
cache : {'thursday': 'Thursday .docx', ...}      # Thursday.docx silently gone
'Thursday' -> Thursday .docx                     # no error, no warning
```

```
manifest title : 'This run: 1 schedules'
print button   : 'Print 1 schedule'
```

```
only the Night range is invalid; Day is untouched and valid
  night panel reads: 'Check date selection'
  day   panel reads: 'Check date selection'      # wrong shift flagged
  error text       : 'End date cannot be before start date'   # names no shift
```

## Backend design

### B1 — Template collision detection

`WordProcessor._build_template_cache` normalizes each stem with
`" ".join(stem.lower().split())` and stores it in a `dict[str, str]`. Two files
whose stems normalize identically collapse to one key; the survivor depends on
directory iteration order. The existing ambiguity check never sees the
collision because it happens during cache construction.

Change the cache to `dict[str, list[str]]`. `find_template_file` raises
`TemplateLookupError` when a matched key holds more than one path, listing the
colliding file names and instructing the operator to rename them.
`_preflight_templates` already converts `TemplateLookupError` into a blocking
validation error, so no new plumbing is required.

The exact-match branch, the word-boundary matching branch, the `third` filter,
and the refresh-once-on-miss behaviour are all preserved.

### B2 — `safe_com_call` retry precision

`transient_keywords` currently includes the bare substring `"server"`, which
matches permanent faults such as "The server threw an exception". Each such
failure costs 5 retries at 1 second, per document.

Replace with specific transient markers: `"call was rejected"`,
`"server is busy"`, `"message filter"`, `"rpc_e_"`. The retry count and delay
constants are unchanged.

### B3 — Remove dead constants

`WD_PRIMARY_HEADER_STORY`, `WD_EVEN_PAGES_HEADER_STORY`,
`WD_PRIMARY_FOOTER_STORY`, `WD_EVEN_PAGES_FOOTER_STORY`,
`WD_FIRST_PAGE_HEADER_STORY`, and `WD_FIRST_PAGE_FOOTER_STORY` are defined and
exported but imported nowhere. They are fossils of a removed header/footer-only
mode. Remove the definitions, the `__all__` entries, and the section comment.

`WD_FIND_CONTINUE` and `WD_REPLACE_ALL` are in active use and stay.

## Frontend design

### F1 — Equal-height date modes and content-derived window size

Today the single-date row is a label beside an entry (34px tall) and the range
rows are labels above entries (60px tall). Toggling modes changes the layout
height by 26px, and `_auto_resize_to_content()` runs only once at construction,
so the window never re-fits.

Restructure the single-date row to label-above-entry, with the label `Date`,
matching the `Start date` / `End date` rows. Both modes then occupy the same
height by construction. No `grid_propagate` manipulation and no re-fit hook are
needed, and the two modes gain the same control structure that DESIGN.md
already requires across shifts.

With content height constant, derive the window size from Tk's computed
requirement after widget construction:

- initial geometry: `WINDOW_WIDTH` x computed required height
- `minsize`: `WINDOW_WIDTH` x computed required height

`WINDOW_HEIGHT` and `WINDOW_MIN_HEIGHT` are no longer authoritative for height
and are removed, along with their `__all__` entries and their `src/ui.py`
imports. No test references either constant, so removal is contained.
`WINDOW_WIDTH` stays. `AUTO_RESIZE_MIN_WIDTH` and `AUTO_RESIZE_MIN_HEIGHT`
remain as the clamp floors for the screen-bound calculation.

Because the derived height comes from the live font metrics of the running
system, this is correct under Windows text scaling, which a hardcoded constant
measured on macOS is not.

### F2 — Folder-path setters own the placeholder contract

`ShiftPressApp._load_config` reaches into `self.ui.day_entry` and calls
`.delete()` / `.insert()` directly. `_setup_placeholder` had already set the
entry foreground to `text_dim`, and nothing resets it, so a loaded path renders
in placeholder gray. `_browse_folder` handles this correctly, which is why the
bug only appears on the config path.

Add `ScheduleAppUI.set_day_folder(path)` and `set_night_folder(path)`. These
own the invariant: clear the entry, insert the value, and set the foreground to
`text_main` for a real value or leave the placeholder in place for an empty
one. `_load_config` calls the setters instead of touching widget internals.

This fixes the defect at the boundary. The controller stops manipulating widget
internals it does not own.

### F3 — Manifest pluralization

`refresh_manifest_preview` hardcodes `f"This run: {len(manifest)} schedules"`.
Use the same singular/plural logic the print button already applies:

- 0 jobs: `This run: No schedules selected` (unchanged)
- 1 job: `This run: 1 schedule`
- N jobs: `This run: N schedules`

### F4 — Semantic count-label states

`NightCount.TLabel` and `DayCount.TLabel` are byte-identical, both hardcoded to
`foreground=COLORS.success`. Only the label text changes across states, so a
validation error and an excluded shift both render in success green.

Replace both with three shared state styles:

| State    | Text                          | Style                | Token      | Hex       |
| -------- | ----------------------------- | -------------------- | ---------- | --------- |
| Ready    | `Selected · N document(s)`    | `CountReady.TLabel`  | `success`  | `#4ADE80` |
| Excluded | `Not included`                | `CountMuted.TLabel`  | `text_dim` | `#B5B7BD` |
| Error    | `Check <Shift> date selection`| `CountError.TLabel`  | `error`    | `#FB7185` |

`refresh_manifest_preview` sets both `text` and `style` together.

Shift identity remains carried by the card title colour and border accent
(amber for Night, cyan for Day). The count line communicates readiness, not
identity, so it uses semantic state tokens. Text differs across all three
states, so colour reinforces rather than solely conveys state, satisfying
DESIGN.md's "Don't use color as the only indication of shift or validation
state."

No existing test asserts `NightCount.TLabel` or `DayCount.TLabel`.

### F5 — Per-shift error attribution

`refresh_manifest_preview` calls `build_print_manifest(selections)`, which
raises on the first invalid selection. The `except ValueError` branch then
marks every enabled panel `Check date selection`, including shifts that are
perfectly valid, and the message `End date cannot be before start date`
originates in `validate_date_range` and names no shift.

Add a pure method to `print_manifest.py`:

```python
def validate(self) -> Optional[str]:
    """Return a shift-labelled error, or None when this selection is valid."""
```

It returns `None` for a disabled selection, reuses `active_range()` for the
missing-date cases (which already produce labelled messages), and wraps
`validate_date_range` failures as `f"{label} schedule: {error}"`.

`refresh_manifest_preview` evaluates each selection independently:

- valid enabled shift: `CountReady`, real document count
- invalid enabled shift: `CountError`, `Check <Shift> date selection`
- disabled shift: `CountMuted`, `Not included`

The manifest title names the offending shift. The body lists the labelled error
for each invalid shift. The print button falls back to `Print schedules` with
no count whenever any enabled shift is invalid, because `_validate_inputs`
blocks the whole run in that case; the button must not imply a printable count.

`_validate_inputs` uses the same `validate()` method, replacing its own
inline range checking. This removes the current divergence where the controller
labels errors by shift and the preview does not.

`build_print_manifest` continues to raise on invalid input. It remains the
last-line guard.

## CI and release design

### C1 — Build depends on quality

The `build` job has no `needs:`, so on `workflow_dispatch` it runs in parallel
with `quality` and `action-gh-release` can publish with failing tests. Add
`needs: quality`.

### C2 — Enforce the documented pylint gate

README documents `pylint src --fail-under=8.0` as a quality gate; the workflow
does not run it. Add the step to the `quality` job. Current score is 8.85.

### C3 — Single-source the version

The workflow takes a hand-typed `version` input used for the artifact name and
release tag, while the in-app header reads `src/__init__.py.__version__`.
Nothing keeps them in sync.

Add a `version` step to the `build` job that extracts `__version__` from
`src/__init__.py` and writes it to `$GITHUB_OUTPUT`:

```yaml
- name: Read version
  id: version
  shell: bash
  run: |
    v=$(python -c "import re,pathlib; \
      print(re.search(r'__version__ = \"([^\"]+)\"', \
      pathlib.Path('src/__init__.py').read_text()).group(1))")
    echo "value=$v" >> "$GITHUB_OUTPUT"
```

Both the artifact name and the release tag consume
`${{ steps.version.outputs.value }}`. Remove the `version` workflow input. The
`create_release` input stays. Releasing becomes: bump `__version__`, commit,
dispatch.

## Docs and copy design

- **D1.** Delete `docs/screenshots/main.png` and the README Preview section. Add
  a screenshot-capture step to `docs/windows-smoke-test.md` so the refresh
  happens where a real Windows instance exists.
- **D2.** Remove "Date replacement automation with optional header/footer-only
  mode" from README Core Features. No such control exists and `replace_dates`
  always spans all story ranges.
- **D3.** `_show_failure_summary` says "Click 'Open Logs' in the app footer";
  the button reads `Open logs`. Match the button.
- **D4.** The `main.py` comment claims "keyboard shortcuts (Enter = start,
  Escape = cancel)". Enter only fires when the print button already has focus;
  Escape is bound globally on the root. Correct the comment to say so.

## Testing strategy

Test-driven: each fix gets a failing test first, then the implementation.

### Harness constraint

`tests/test_ui.py` patches every `ttk` widget class and passes a
`MagicMock(spec=tk.Tk)` as the root. Real geometry is therefore unavailable in
the unit suite: `winfo_reqheight()` returns a `MagicMock`, not an integer. F1
must not be tested by measuring rendered pixels there. It is split into two
testable contracts instead:

- **Structure:** the single-date row is built with the same label-above-entry
  shape as the range rows, asserted against the mocked construction calls.
- **Derivation:** with `root.winfo_reqheight.return_value` stubbed to a known
  integer, `root.minsize` and `root.geometry` are called with that value.

The rendered-pixel check stays a manual verification step (below), which is how
the defect was originally found.

### New tests

| Fix | Test |
| --- | --- |
| B1 | colliding normalized stems raise `TemplateLookupError` naming both files |
| B1 | a non-colliding folder still resolves exact and word-boundary matches |
| B2 | `"server threw an exception"` is not retried; `"server is busy"` is |
| F1 | the single-date row uses label-above-entry, matching the range rows |
| F1 | `minsize` and initial geometry use the computed required height |
| F2 | `set_day_folder` with a real path sets foreground to `text_main` |
| F2 | `set_day_folder("")` leaves the placeholder and dim foreground |
| F3 | a 1-job manifest renders `This run: 1 schedule` |
| F4 | each of the three states sets its matching style |
| F5 | an invalid Night range leaves the Day panel in `CountReady` |
| F5 | the error message names the offending shift |

The 1-schedule case is currently untested; only 0-job and 2-job manifests are
covered, which is why F3 shipped.

### Manual verification

Against a real (unmocked) Tk instance on this host, confirm that the single and
range modes report equal required height, and that the window's `minsize`
equals its required height so the primary action cannot be clipped. The Windows
smoke test remains the release gate for real Word COM and printer behaviour.

Regression bar: all 219 existing tests stay green, `black --check`, `mypy src`,
and `pylint src --fail-under=8.0` stay clean.

## Out of scope

- No unrelated refactoring of `src/ui.py` size or structure.
- The uncapped combined manifest size (each shift may span 366 days, so up to
  732 documents) is left as-is; `LARGE_BATCH_THRESHOLD` already prompts at 30.
- CSV failure reports are not hardened against spreadsheet formula injection.
  The fields are computed template names and COM error strings, and this is a
  single-operator desktop tool.
- No new Windows-only integration testing; the suite continues to mock
  Windows-only modules.
