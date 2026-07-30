# Independent Shift Printing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shared Day/Night date range with independent, side-by-side Night and Day selections, and drive validation, preflight, progress, printing, and results from one exact immutable print manifest.

**Architecture:** Add a small pure `print_manifest` module for shift-selection and concrete-job types. The Tkinter UI owns only native widget state and exposes immutable selections; the controller validates those selections into a frozen batch request before starting the worker. The worker iterates that request's manifest without reading Tkinter state or reconstructing dates.

**Tech Stack:** Python 3.12, Tkinter/ttk, tkcalendar `DateEntry`, pytest, unittest.mock, Black, mypy, pylint, Microsoft Word COM through the existing `WordProcessor`.

## Global Constraints

- Keep the approved side-by-side native Tkinter composition. Do not add Canvas controls, browser UI, image buttons, animation, or custom-drawn widgets.
- Both shifts default enabled in Single date mode. Night defaults to local today; Day defaults to the following local calendar date.
- Disabling a shift preserves its date and mode values but excludes it from validation, preflight, confirmation, progress, printing, and results.
- Continue persisting only the existing Day folder, Night folder, and printer. Never persist dates, modes, or include toggles.
- Build the final manifest once on the Tkinter thread after validation. Pass that exact immutable tuple to preflight, confirmation, and the worker.
- Sort jobs chronologically, with Night before Day only when two jobs share a date.
- Preserve cancellation before every document, the preflight `WordProcessor` cache, CSV failure reports, thread cleanup, and window-close behavior.
- Keep all existing repository behavior green. Do not change template naming, Word replacement, or printer semantics.
- Treat macOS/Linux tests as automation coverage only. Do not claim Word COM or physical printing is verified until the recorded Windows smoke test passes.
- Preserve unrelated worktree changes. Do not push unless the user separately asks.

---

## Implementation Environment

The current machine has Homebrew but no `python3.12`. Prepare the repository's
ignored virtual environment before Task 1:

```bash
command -v python3.12 || brew install python@3.12
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python --version
```

Expected: the last command reports Python 3.12.x. `.venv/` remains ignored.

---

## Task 1: Introduce the Pure Print Manifest

**Files:**

- Create: `src/print_manifest.py`
- Create: `tests/test_print_manifest.py`
- Modify: `src/constants.py:48,109-112`
- Delete during Task 4: `src/main.py:56-69`

- [ ] **Step 1: Write failing manifest tests**

Create `tests/test_print_manifest.py` with fixed dates and these cases:

```python
from datetime import date

import pytest

from src.print_manifest import PrintJob, ShiftSelection, build_print_manifest


def selection(
    shift_type: str,
    *,
    enabled: bool = True,
    mode: str = "single",
    start: date = date(2026, 7, 30),
    end: date = date(2026, 7, 30),
    folder: str = "/templates",
) -> ShiftSelection:
    return ShiftSelection(
        shift_type=shift_type,
        enabled=enabled,
        mode=mode,
        start_date=start,
        end_date=end,
        folder=folder,
    )


def test_builds_night_only_single_date() -> None:
    manifest = build_print_manifest((selection("night"),))
    assert manifest == (
        PrintJob(
            date=date(2026, 7, 30),
            shift_type="night",
            template_name="Thursday Night",
            folder="/templates",
        ),
    )


def test_ignores_disabled_shift() -> None:
    manifest = build_print_manifest(
        (selection("night"), selection("day", enabled=False))
    )
    assert [job.shift_type for job in manifest] == ["night"]


def test_uses_single_date_even_when_saved_range_end_differs() -> None:
    manifest = build_print_manifest(
        (
            selection(
                "day",
                mode="single",
                start=date(2026, 7, 31),
                end=date(2026, 8, 8),
            ),
        )
    )
    assert [job.date for job in manifest] == [date(2026, 7, 31)]


def test_expands_independent_ranges_and_sorts_chronologically() -> None:
    manifest = build_print_manifest(
        (
            selection(
                "night",
                mode="range",
                start=date(2026, 7, 31),
                end=date(2026, 8, 1),
                folder="/night",
            ),
            selection(
                "day",
                mode="range",
                start=date(2026, 7, 30),
                end=date(2026, 7, 31),
                folder="/day",
            ),
        )
    )
    assert [(job.date, job.shift_type) for job in manifest] == [
        (date(2026, 7, 30), "day"),
        (date(2026, 7, 31), "night"),
        (date(2026, 7, 31), "day"),
        (date(2026, 8, 1), "night"),
    ]


@pytest.mark.parametrize("mode", ["weekly", ""])
def test_rejects_unknown_mode(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        build_print_manifest((selection("night", mode=mode),))


def test_rejects_missing_active_date() -> None:
    item = ShiftSelection(
        shift_type="day",
        enabled=True,
        mode="single",
        start_date=None,
        end_date=None,
        folder="/day",
    )
    with pytest.raises(ValueError, match="Day date"):
        build_print_manifest((item,))
```

Include a separate tie-break test asserting Night precedes Day on the same date, and a template-name test covering the existing `THIRD Thursday` Day rule.

- [ ] **Step 2: Run the new tests and confirm the RED state**

Run:

```bash
.venv/bin/python -m pytest tests/test_print_manifest.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'src.print_manifest'`.

- [ ] **Step 3: Implement immutable selection and job types**

Create `src/print_manifest.py` with this public shape:

```python
from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional, Sequence, cast

from .scheduler import get_date_range, get_shift_template_name

ShiftType = Literal["night", "day"]
DateMode = Literal["single", "range"]


@dataclass(frozen=True)
class ShiftSelection:
    shift_type: ShiftType
    enabled: bool
    mode: DateMode
    start_date: Optional[date]
    end_date: Optional[date]
    folder: str

    def active_range(self) -> tuple[date, date]:
        label = self.shift_type.title()
        if self.start_date is None:
            raise ValueError(f"Select a {label} date")
        if self.mode == "single":
            return self.start_date, self.start_date
        if self.mode != "range":
            raise ValueError(f"Invalid {label} date mode")
        if self.end_date is None:
            raise ValueError(f"Select a {label} range end date")
        return self.start_date, self.end_date


@dataclass(frozen=True)
class PrintJob:
    date: date
    shift_type: ShiftType
    template_name: str
    folder: str


def build_print_manifest(
    selections: Sequence[ShiftSelection],
) -> tuple[PrintJob, ...]:
    jobs: list[PrintJob] = []
    for selection in selections:
        if not selection.enabled:
            continue
        start_date, end_date = selection.active_range()
        for scheduled_date in get_date_range(start_date, end_date):
            jobs.append(
                PrintJob(
                    date=scheduled_date,
                    shift_type=selection.shift_type,
                    template_name=get_shift_template_name(
                        scheduled_date, selection.shift_type
                    ),
                    folder=selection.folder,
                )
            )
    return tuple(
        sorted(
            jobs,
            key=lambda job: (
                job.date,
                0 if job.shift_type == "night" else 1,
            ),
        )
    )
```

Use explicit runtime guards before `cast` if mypy requires the test helper to pass plain strings. Do not silently coerce invalid shift or mode strings.

Change `LARGE_BATCH_THRESHOLD` in `src/constants.py` to mean concrete documents:

```python
LARGE_BATCH_THRESHOLD: Final = 30  # documents — prompt user for confirmation
```

Delete `_compute_batch_size` only after its callers have been migrated in Tasks 3 and 4.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_print_manifest.py tests/test_scheduler.py -q
```

Expected: all manifest and scheduler tests pass.

- [ ] **Step 5: Commit the pure model**

```bash
git add src/print_manifest.py src/constants.py tests/test_print_manifest.py
git commit -m "feat: add independent shift print manifest"
```

---

## Task 2: Build the Side-by-Side Native Shift UI

**Files:**

- Modify: `src/ui.py:1-35,164-229,434-904`
- Modify: `src/constants.py:99-143`
- Modify: `tests/test_ui.py:1-119`

- [ ] **Step 1: Expand the UI fixture and write failing behavior tests**

Update the widget patches in `tests/test_ui.py` to include `ttk.Radiobutton`. Instantiate with a fixed clock:

```python
ui = ScheduleAppUI(root, today=date(2026, 7, 30))
```

Add focused tests for:

```python
def test_defaults_night_today_and_day_tomorrow(ui) -> None:
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


def test_shift_selections_are_independent(ui) -> None:
    # Assign explicit mock variables and pickers to both panel records.
    # Night is enabled/range; Day is disabled/single.
    night, day = ui.get_shift_selections()
    assert night != day
    assert night.mode == "range"
    assert day.enabled is False


def test_disabling_night_does_not_disable_day_controls(ui) -> None:
    ui._shift_panels["night"].enabled_var.get.return_value = False
    ui._shift_panels["day"].enabled_var.get.return_value = True
    ui._sync_shift_panel_state("night")
    ui._shift_panels["night"].single_radio.config.assert_called_with(
        state="disabled"
    )
    ui._shift_panels["day"].single_radio.config.assert_not_called_with(
        state="disabled"
    )


def test_mode_change_preserves_hidden_picker_values(ui) -> None:
    # Change the mode variable and call _sync_shift_panel_state.
    # Assert config/grid methods change, but no picker receives set_date().


def test_manifest_preview_updates_count_and_button(ui) -> None:
    ui._update_manifest_preview()
    ui.manifest_label.config.assert_called()
    ui.print_btn.config.assert_any_call(text="Print 2 schedules")


def test_set_inputs_enabled_controls_every_shift_widget(ui) -> None:
    ui.set_inputs_enabled(False)
    # Assert setup controls, include toggles, radios, and all six DateEntry
    # widgets receive state="disabled".
```

Retain the current status, dialogs, start-command, and folder-getter tests.

- [ ] **Step 2: Run the UI tests and confirm the RED state**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui.py -q
```

Expected: failures because `ScheduleAppUI` does not accept `today`, has no `_shift_panels`, and still exposes one shared date range.

- [ ] **Step 3: Add native shift-panel state and exact defaults**

In `src/ui.py`:

- import `dataclass`, `timedelta`, and the manifest types/helper;
- add a private `_ShiftPanelWidgets` dataclass holding the include variable, mode variable, checkbutton, two radiobuttons, three date pickers, and the single/range wrapper frames;
- change the constructor to `ScheduleAppUI(root, today: Optional[date] = None)`;
- store `self._today = today or date.today()`;
- initialize `self._shift_panels: dict[ShiftType, _ShiftPanelWidgets] = {}`;
- initialize `self.manifest_label` and retain `self.print_btn`.

Use these exact initial dimensions and Day token in `src/constants.py`:

```python
WINDOW_WIDTH: Final = 980
WINDOW_HEIGHT: Final = 820

@dataclass(frozen=True)
class Colors:
    # existing values remain unchanged
    day_accent: str = "#38BDF8"  # Sky-400
```

Add `Night.TLabelframe.Label` and `Day.TLabelframe.Label` styles. Both panels must also contain the written shift name and Include label so color is supplementary.

- [ ] **Step 4: Replace the shared cards with the approved composition**

Refactor `_create_widgets` into this order:

```python
self._create_header(bg_canvas)
self._create_setup_card(bg_canvas)
self._create_shift_selection_row(bg_canvas)
self._create_manifest_card(bg_canvas)
self._create_footer(bg_canvas)
```

Implementation details:

- `_create_setup_card` contains Day Templates, Night Templates, and Printer.
- `_create_shift_selection_row` uses a `ttk.Frame` with `grid_columnconfigure(0, weight=1)` and `grid_columnconfigure(1, weight=1)`.
- Put Night in column 0 and Day in column 1 with equal padding.
- `_create_shift_panel` creates only `ttk.LabelFrame`, `ttk.Checkbutton`, `ttk.Radiobutton`, `ttk.Frame`, `ttk.Label`, and existing `DateEntry` widgets.
- Night defaults to `self._today`; Day defaults to `self._today + timedelta(days=1)`.
- Single and range picker values are all initialized to that shift's default.
- `_sync_shift_panel_state(shift_type)` disables only that shift's mode/date controls when excluded, uses `grid`/`grid_remove` for the active date mode, and never calls `set_date`.
- Bind every `<<DateEntrySelected>>`, include command, and mode command to state synchronization plus manifest refresh.
- Preserve the existing behavior that advances a range end when its start moves past it, but scope it to the affected shift panel.

Expose the new controller boundary:

```python
def get_shift_selections(self) -> tuple[ShiftSelection, ShiftSelection]:
    return (
        self._get_shift_selection("night"),
        self._get_shift_selection("day"),
    )
```

`_get_shift_selection` must read only the selected shift's variables and pickers. For Single mode it may retain the hidden range end in the dataclass, because `active_range()` ignores it.

The manifest card should show:

- `This run: N schedules`
- one line per enabled shift with its active date or range and count;
- `Printer: <name>` or `Printer: Choose a printer`;
- button text `Print 1 schedule` or `Print N schedules`.

When no shift is included, show `This run: No schedules selected` and use `Print schedules`. Do not display `Ready` before controller preflight.

- [ ] **Step 5: Make processing lock state composable**

Implement a UI-wide flag such as `self._inputs_enabled`. `set_inputs_enabled(False)` disables:

- both folder entries and their Browse buttons;
- printer dropdown and Refresh;
- both Include checkbuttons;
- all mode radios and date pickers.

`set_inputs_enabled(True)` restores Setup controls and Include checkbuttons, then calls `_sync_shift_panel_state` for each shift so an excluded shift remains visually disabled. Store Browse buttons when creating path rows so they can be locked.

Add a public `refresh_manifest_preview()` method for Task 4's `_reset_ui` to
call instead of hard-coding `Print Schedules`.

- [ ] **Step 6: Run focused UI and manifest tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui.py tests/test_print_manifest.py -q
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit the native UI**

```bash
git add src/ui.py src/constants.py tests/test_ui.py
git commit -m "feat: add independent native shift controls"
```

---

## Task 3: Validate and Preflight Only the Selected Manifest

**Files:**

- Modify: `src/main.py:1-371`
- Modify: `tests/test_main.py:1-104,286-351,456-482,509-530`

- [ ] **Step 1: Replace shared-range test fixtures with selections**

Import `dataclass`, `replace`, `PrintJob`, `ShiftSelection`, and `build_print_manifest` where needed. Add a frozen request next to `FailedOperation`:

```python
@dataclass(frozen=True)
class _BatchRequest:
    manifest: tuple[PrintJob, ...]
    printer_name: str
    day_folder: str
    night_folder: str
```

Change the app fixture to return independent selections:

```python
mock_ui.get_shift_selections.return_value = (
    ShiftSelection(
        shift_type="night",
        enabled=True,
        mode="single",
        start_date=date(2026, 1, 14),
        end_date=date(2026, 1, 14),
        folder="/tmp/night",
    ),
    ShiftSelection(
        shift_type="day",
        enabled=True,
        mode="single",
        start_date=date(2026, 1, 15),
        end_date=date(2026, 1, 15),
        folder="/tmp/day",
    ),
)
```

Write failing tests that assert:

- neither enabled returns `Select at least one Night or Day schedule`;
- a missing disabled Day folder does not call `validate_folder_path` for Day;
- a missing enabled Night folder produces a Night-specific error;
- a reversed Day range produces the existing date-range error labeled Day;
- Night-only preflight looks up only the Night template;
- selected missing and ambiguous templates still fail;
- success returns a `_BatchRequest` whose manifest contains exactly the selected jobs;
- quoted folder paths are normalized once in both request folders and job folders.

Use a return contract of:

```python
request, error = app._validate_inputs()
assert request is not None
assert error is None
```

- [ ] **Step 2: Run validation/preflight tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_main.py \
  -k "validate_inputs or preflight_templates or start_processing_batch_params" -q
```

Expected: failures because `_validate_inputs` still requires both folders and one shared range, and `_preflight_templates` synthesizes both shifts.

- [ ] **Step 3: Build one validated batch request**

Change `_validate_inputs` to:

```python
def _validate_inputs(
    self,
) -> tuple[Optional[_BatchRequest], Optional[str]]:
```

Apply validation in the approved order:

1. Read both selections once from `ui.get_shift_selections()`.
2. Normalize both folder strings with the existing whitespace/quote stripping.
3. Require at least one enabled selection.
4. For each enabled selection, call `active_range()` and then `validate_date_range`.
5. Validate the printer once and check it against the available-printer snapshot.
6. Check Word automation availability.
7. Validate only enabled folders.
8. Build one immutable manifest with `build_print_manifest`.
9. Preflight that manifest.
10. Return `_BatchRequest(manifest, printer_name, day_folder, night_folder)`.

Use `dataclasses.replace` to put normalized folder values back into selections before manifest construction. Preserve both configured folders in `_BatchRequest`, even when one shift is disabled, so configuration persistence does not change.

Change `_preflight_templates` to accept only concrete jobs:

```python
def _preflight_templates(
    self, manifest: tuple[PrintJob, ...]
) -> tuple[bool, Optional[str]]:
```

Deduplicate checks by `(job.folder, job.shift_type, job.template_name)`. Keep the existing `TemplateLookupError`, truncation, warm-cache, and missing-template message behavior. Label every issue with `Night` or `Day`.

- [ ] **Step 4: Make start confirmation consume the validated request**

In `start_processing`:

```python
request, error_msg = self._validate_inputs()
if request is None:
    self.ui.show_warning("Validation Error", error_msg or "Unknown error")
    return
```

For `len(request.manifest) >= LARGE_BATCH_THRESHOLD`, confirm using the exact document count and concise per-shift scope. Never call the removed shared-date getters and never recalculate `days × 2`.

Pass `request` directly to the worker:

```python
self._processing_thread = threading.Thread(
    target=self._process_batch,
    args=(request,),
    daemon=False,
)
```

- [ ] **Step 5: Run the focused controller tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_main.py \
  -k "validate_inputs or preflight_templates or start_processing" -q
```

Expected: all selected validation, preflight, and request-handoff tests pass.

- [ ] **Step 6: Commit validation and preflight**

```bash
git add src/main.py tests/test_main.py
git commit -m "refactor: validate selected shift manifest"
```

---

## Task 4: Execute, Report, and Cancel by Concrete Job

**Files:**

- Modify: `src/main.py:46-69,375-570`
- Modify: `tests/test_main.py:105-285,379-455,509-530`

- [ ] **Step 1: Write failing worker tests using explicit manifests**

Replace old `start_date`/`end_date` dictionaries with `_BatchRequest` instances. Add or update tests for:

```python
def test_processes_night_today_then_day_tomorrow(self, app) -> None:
    mock_wp = MagicMock()
    mock_wp.__enter__.return_value = mock_wp
    mock_wp.__exit__.return_value = False
    mock_wp.print_document.return_value = (True, None)
    app._preflight_wp = mock_wp

    request = _BatchRequest(
        manifest=(
            PrintJob(
                date=date(2026, 1, 14),
                shift_type="night",
                template_name="Wednesday Night",
                folder="/tmp/night",
            ),
            PrintJob(
                date=date(2026, 1, 15),
                shift_type="day",
                template_name="THIRD Thursday",
                folder="/tmp/day",
            ),
        ),
        printer_name="Test Printer",
        day_folder="/tmp/day",
        night_folder="/tmp/night",
    )

    app._process_batch(request)

    assert [call.args[:3] for call in mock_wp.print_document.call_args_list] == [
        ("/tmp/night", "Wednesday Night", date(2026, 1, 14)),
        ("/tmp/day", "THIRD Thursday", date(2026, 1, 15)),
    ]
```

Also assert:

- Night-only and Day-only each call `print_document` once.
- Progress messages end at `1/1` or `2/2`, based on manifest length.
- Success says `All 2 selected schedules have been processed and sent to the printer.`, not the old day-based message.
- Cancellation set before the batch prints zero jobs.
- Cancellation set after the first job prevents the second.
- A failed Night job records `"shift": "night"` and does not prevent the remaining selected job.
- The saved `AppConfig` still contains both folder values and the printer.
- Reused preflight `WordProcessor` is cleared after acquisition.
- `_reset_ui` restores the count-aware manifest button through the UI.

- [ ] **Step 2: Run worker tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_main.py \
  -k "process_batch or cancel or failure or reset_ui" -q
```

Expected: failures because `_process_batch` still expects a dictionary, reconstructs two jobs per date, and reports days.

- [ ] **Step 3: Replace `_print_shift` with concrete-job processing**

Rename `_print_shift` to `_print_job` and use:

```python
def _print_job(
    self,
    word_proc: WordProcessor,
    job: PrintJob,
    printer_name: str,
    job_index: int,
    total_jobs: int,
    failed_operations: list[FailedOperation],
) -> None:
```

Derive `shift_label`, display text, Word arguments, logging, and failure fields from `job`. Keep progress as `(job_index + 1) / total_jobs`.

- [ ] **Step 4: Iterate only the frozen request manifest**

Change:

```python
def _process_batch(self, request: _BatchRequest) -> None:
```

The worker must:

- save `request.day_folder`, `request.night_folder`, and `request.printer_name`;
- set `total_jobs = len(request.manifest)`;
- acquire and clear the preflight WordProcessor;
- check cancellation immediately before every manifest job;
- call `_print_job` in tuple order;
- keep processing after an individual print failure;
- report `All {total_jobs} selected schedules have been processed and sent to the printer.`;
- keep existing CSV, warning, exception, and `finally` cleanup paths.

Delete `_compute_batch_size` and all imports/usages of `get_date_range` and `get_shift_template_name` from `src/main.py` after the migration is complete. Template naming now belongs only to manifest construction.

Change `_reset_ui` to:

```python
self.ui.set_inputs_enabled(True)
self.ui.refresh_manifest_preview()
self.ui.set_print_button_state("normal")
```

The UI method restores the count-aware label and amber button styling.

- [ ] **Step 5: Run all main, manifest, and scheduler tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_main.py tests/test_print_manifest.py tests/test_scheduler.py -q
```

Expected: all selected tests pass, with no references to `_compute_batch_size`, `get_start_date`, or `get_end_date`.

- [ ] **Step 6: Commit manifest-driven execution**

```bash
git add src/main.py src/ui.py tests/test_main.py
git commit -m "feat: print only selected shift jobs"
```

---

## Task 5: Render the Native UI and Close Automated Regressions

**Files:**

- Inspect and modify only if the render exposes a defect: `src/ui.py`, `src/constants.py`, `tests/test_ui.py`
- Create: `docs/windows-smoke-test.md`
- Modify: `README.md`

- [ ] **Step 1: Run the full suite before visual adjustment**

Run:

```bash
.venv/bin/python -m pytest --cov=src --cov-report=term-missing
```

Expected: full suite passes. If an unrelated existing test fails, record it before changing code; do not hide it with skips or broad mocks.

- [ ] **Step 2: Launch and inspect the real Tkinter window**

Run:

```bash
.venv/bin/python main.py
```

Inspect the rendered app at its default size and after narrowing/re-expanding:

- Setup is compact and contains both paths plus Printer.
- Night and Day are equal-width and simultaneously visible.
- Night shows amber identity; Day shows blue identity; both have written names.
- Defaults are Night today and Day tomorrow.
- Include and mode changes affect only their own panel.
- Single/range values survive mode and include toggles.
- Manifest and button count update immediately.
- No control is clipped at the 980 × 820 initial size.
- Keyboard focus reaches controls in visual order.
- Disabled text remains readable against the charcoal surface.

Make only evidence-based spacing, sizing, or state fixes. Add a regression test before each behavior change; visual-only spacing changes must be accompanied by a rerender.

- [ ] **Step 3: Record the Windows operational checklist**

Create `docs/windows-smoke-test.md` with:

- prerequisites: Windows 10/11, Python 3.12 or the built executable, Word installed, test printer or PDF printer, known Day/Night templates;
- build identifier/commit field;
- tester/date/result fields;
- exact cases:
  1. Night today plus Day tomorrow prints exactly two documents in manifest order.
  2. Night-only prints one Night document without requiring a valid Day folder.
  3. Day-only prints one Day document without requiring a valid Night folder.
  4. Independent ranges print the exact ordered manifest count.
  5. A missing selected template stops before Word opens.
  6. Cancel stops before the next document and Word exits cleanly.
  7. A forced partial failure creates an accurate CSV and continues remaining jobs.
  8. Relaunch preserves folders/printer but restores fresh today/tomorrow defaults.

Mark the checklist `Pending Windows execution` until it is actually performed. Do not fabricate results.

Add a short README link under Testing or Quality Checks:

```markdown
For Word COM and physical print verification, complete the
[Windows smoke test](docs/windows-smoke-test.md).
```

- [ ] **Step 4: Commit the rendered UI adjustments and checklist**

```bash
git add src/ui.py src/constants.py tests/test_ui.py README.md docs/windows-smoke-test.md
git commit -m "docs: add Windows print smoke test"
```

If the render required no code or test adjustment, stage and commit only `README.md` and `docs/windows-smoke-test.md`.

---

## Task 6: Run Final Quality Gates and Review the Diff

**Files:**

- Verify: all changed files

- [ ] **Step 1: Format, then prove formatting is clean**

Run:

```bash
.venv/bin/python -m black src tests
.venv/bin/python -m black --check src tests
```

Expected: the check reports all files would be left unchanged. If Black rewrites files, rerun all affected tests before continuing.

- [ ] **Step 2: Run repository quality gates**

Run:

```bash
.venv/bin/python -m mypy src --ignore-missing-imports
.venv/bin/python -m pytest --cov=src --cov-report=term-missing
.venv/bin/python -m pylint src --fail-under=8.0
```

Expected:

- mypy: success with no issues;
- pytest: all tests pass and coverage report completes;
- pylint: score is at least 8.0.

- [ ] **Step 3: Run focused selection regressions once more**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_print_manifest.py tests/test_ui.py tests/test_main.py -q
```

Expected: all independent Night/Day, disabled-shift, manifest-order, cancellation, and failure-report tests pass.

- [ ] **Step 4: Self-review against the approved specification**

Run:

```bash
git diff --check
git status --short
git diff origin/test...HEAD -- \
  src tests README.md docs/windows-smoke-test.md \
  docs/superpowers/specs/2026-07-30-independent-shift-printing-design.md
rg -n "TO[D]O|T[B]D|FIX[M]E|days x 2|days × 2|get_start_date|get_end_date|_compute_batch_size" \
  src tests README.md docs/windows-smoke-test.md
```

Expected:

- no whitespace errors;
- only intended feature/doc files differ;
- no implementation placeholders;
- no old shared-range or two-jobs-per-day assumptions remain;
- design spec, tests, UI getters, controller request types, and worker types agree.

- [ ] **Step 5: Commit any quality-tool rewrites**

If formatting or review produced tracked fixes:

```bash
git add src tests README.md docs/windows-smoke-test.md
git commit -m "test: close independent shift regressions"
```

If nothing changed, do not create an empty commit.

- [ ] **Step 6: Report the verified boundary**

Report:

- exact local commit hash and branch;
- commands and pass counts for Black, mypy, pytest/coverage, and pylint;
- native render result;
- that Night and Day automated behavior is verified;
- whether the Windows checklist remains pending or has real tester/date/build evidence;
- explicitly that Word COM and physical printer output are not end-to-end verified if the Windows checklist is pending.
