<!--
THESIS: Make print intent explicit through two independent native shift sections; refuse the old assumption that configured folders mean both shifts print.
OWN-WORLD: A flat Windows operator console with charcoal surfaces, native rectangular controls, Night amber, Day blue, written state, and no custom-drawn effects.
STORY: The operator confirms setup, independently selects Night and Day dates or ranges, sees the exact manifest, and prints only those documents.
FIRST VIEWPORT: Setup spans the top; Night and Day sit side by side; the exact manifest and one print action span the bottom.
FORM: Independent Shift Sections ranked first of three native layouts, using the second side-by-side composition probe; concept seed 2d6a4298.
-->

# Independent Shift Printing and Native UI Redesign

**Date:** 2026-07-30

**Status:** Approved

**Surface:** `src/ui.py` and the print workflow it drives

## Problem

ShiftPress currently treats every selected date as two mandatory jobs. It
requires both template folders, preflights both shift types, calculates
`days × 2` jobs, and unconditionally prints Day followed by Night. In the real
workflow, an operator commonly prints the current Night schedule and the next
Day schedule in one run. The current model therefore prints schedules that may
already have been used or are not yet needed.

Configured template folders must no longer imply print intent.

## Goals

- Make Night and Day independently selectable and independently dated.
- Support a single date or a date range for either shift.
- Default a fresh launch to Night today and Day tomorrow, both enabled and in
  Single date mode.
- Keep both shift selections visible at the same time.
- Show the exact print manifest and document count before execution.
- Preserve existing template lookup, Word automation, cancellation, progress,
  failure reporting, and configuration behavior.
- Implement the redesign entirely with standard Tkinter/ttk controls already
  used by the project.
- Verify the complete automated suite and document the remaining Windows-only
  smoke-test boundary.

## Non-Goals

- An arbitrary add/remove job queue.
- Tabs or modal steps that hide one shift.
- Custom-painted controls, Canvas gauges, animation, web rendering, or
  image-based widgets.
- Rebranding ShiftPress or replacing its application icon.
- Live template scanning on every date-field edit.
- Changing Word document replacement or print semantics beyond selecting which
  jobs reach them.

## Approved Interface

### Composition

The default window becomes wider so two native shift groups can sit side by
side without crowding. The exact width is finalized against a rendered Tkinter
window and Windows display scaling; the generated composition is a hierarchy
reference, not a pixel specification.

The vertical sequence is:

1. Header and compact Setup group.
2. Side-by-side Night and Day selection groups.
3. Full-width print manifest.
4. Progress/status and one primary print action.

The Setup group preserves separate Day Templates and Night Templates paths plus
the printer selector. The shift groups control print intent; the folder fields
only configure sources.

### Shift groups

Night and Day use the same native control structure:

- `Include Night schedule` or `Include Day schedule` checkbutton.
- `Single date` and `Date range` radiobuttons.
- A `DateEntry` for Single date mode.
- Start and end `DateEntry` controls for Date range mode.
- Plain-language selected-document count.

Night uses a narrow amber identity treatment and Day uses a narrow blue
identity treatment. Each group also contains the written shift name, so color
is never the only identifier.

Disabling a shift:

- removes it from validation, preflight, confirmation, progress, and printing;
- disables its mode and date controls;
- preserves its current values so re-enabling it is lossless.

Switching modes preserves both the single-date value and the last range values.
Only the active mode contributes jobs.

### Defaults and persistence

Every application launch starts with:

- Night enabled;
- Night in Single date mode using the local current date;
- Day enabled;
- Day in Single date mode using the following local calendar date.

The app continues to persist template folders and printer selection. It does
not persist shift enablement, date modes, or dates because stale dates create a
print-safety risk and conflict with the daily default.

### Manifest and action

The full-width manifest is derived from the same immutable job list passed to
the worker thread. It states:

- each enabled shift;
- its exact date or range;
- its document count;
- the selected printer;
- the total documents that will print.

The primary button includes the actual count, for example
`Print 2 schedules`. When no shift is enabled, the action is blocked and a
plain validation message instructs the operator to include Night, Day, or both.

The generated mockups show green `Ready` text for composition only. The
implementation must not claim templates are ready before the existing preflight
has actually succeeded. Before preflight, the UI reports selected document
counts rather than readiness.

## Processing Model

### Shift selections

The controller collects one independent selection for Night and one for Day on
the Tkinter thread. Each selection contains:

- shift type;
- enabled state;
- mode (`single` or `range`);
- active start and end dates;
- configured template folder.

These values are collected before the worker starts so background processing
never reads Tkinter state.

### Print manifest

A pure manifest-building helper expands enabled selections into concrete print
jobs. Each job contains:

- date;
- shift type;
- template name;
- template folder.

Jobs are sorted chronologically. Night precedes Day only when both target the
same date. The manifest is the single source of truth for validation counts,
large-batch confirmation, progress, processing order, completion messaging,
and failure reporting.

The existing `_compute_batch_size` assumption that every date produces two
jobs is removed or replaced with manifest-based counting.

### Validation and preflight

Validation proceeds in this order:

1. Require at least one enabled shift.
2. Validate the active date or range for each enabled shift with the existing
   range rules.
3. Validate the printer once.
4. Verify Word automation availability.
5. Validate only the folders belonging to enabled shifts.
6. Preflight only the templates required by the manifest.

An empty or invalid folder for a disabled shift does not block printing.
Missing or ambiguous templates for an enabled shift fail before Word opens.

Large-batch confirmation uses the actual manifest size and describes the
selected shift scopes rather than `days × 2 shifts`.

### Execution, progress, and errors

The worker receives the manifest and printer name. It:

- saves the existing folder and printer configuration;
- reuses the preflight `WordProcessor` cache;
- iterates the manifest in its established order;
- checks cancellation before every document;
- updates progress as `completed jobs / manifest jobs`;
- records failures with the existing date, shift, template, and error fields;
- reports exact successes or failures against the manifest total;
- always resets the UI and releases Word resources.

All selection controls, setup controls, and date widgets are disabled while a
batch is active. Existing Cancel and Escape behavior remains intact.

## Error and Edge States

- **Neither shift selected:** block before Word checks and explain how to select
  at least one schedule.
- **Disabled shift has no folder:** ignore it.
- **Enabled shift has no folder:** identify that shift in the validation error.
- **Single date:** treat start and end as the same date.
- **Range end before start:** use the existing date-range error.
- **Selected template missing or ambiguous:** fail preflight with shift and
  template identity.
- **Cancellation:** stop before the next manifest job and keep the existing
  cancellation status.
- **Partial failure:** continue remaining jobs and write the existing CSV
  report with accurate shift data.
- **High DPI or larger text:** keep both groups visible by allowing the native
  window to auto-resize and remain user-resizable.

## Testing

### Controller and manifest tests

- Night only, single date.
- Day only, single date.
- Night today plus Day tomorrow.
- Independent Night and Day ranges with different bounds.
- Chronological ordering and Night-before-Day tie breaking.
- Neither shift enabled.
- Disabled shift folder missing or invalid.
- Enabled shift folder missing or invalid.
- Preflight checks only enabled templates.
- Missing and ambiguous selected templates.
- Actual manifest counts in large-batch confirmation.
- Actual manifest totals in progress and completion messages.
- Cancellation before and between selected jobs.
- Failure reports retain the correct shift.

### UI tests

- Night defaults to enabled, Single date, and today.
- Day defaults to enabled, Single date, and tomorrow.
- Shift getters return independent selections.
- Include toggles enable and disable only their own controls.
- Mode changes expose or enable the correct date widgets.
- Values survive disable/re-enable and mode changes.
- `set_inputs_enabled` controls the new widgets during processing.
- Manifest copy and button count reflect the selected jobs.

### Existing behavior

The complete existing suite remains green, including scheduling, path
validation, configuration, logging, application paths, Word automation, and
date replacement tests.

## Verification

Local verification uses Python 3.12 and the repository's development
dependencies:

```bash
black --check src tests
mypy src --ignore-missing-imports
pytest --cov=src --cov-report=term-missing
pylint src --fail-under=8.0
```

The redesign also requires a rendered Tkinter inspection for clipping, focus
order, disabled states, and window scaling.

Actual Microsoft Word COM automation and physical printer output cannot be
proven on macOS. Final operational verification therefore includes a Windows
smoke test using the built executable or a Python 3.12 environment:

1. Night today plus Day tomorrow prints exactly two documents in manifest
   order.
2. Night-only and Day-only each print exactly one selected document.
3. Independent ranges print the exact manifest count.
4. Disabled shifts do not require folders or templates.
5. Cancellation stops before the next document and Word exits cleanly.

## Acceptance Criteria

- The operator can independently include Night, Day, or both.
- Each enabled shift can use a single date or its own range.
- Fresh-launch defaults are Night today and Day tomorrow.
- Disabled shifts do not validate, preflight, count, or print.
- The manifest, confirmation, progress, completion, and failure output all use
  the same concrete job list.
- The interface uses only standard Tkinter/ttk widgets.
- Both shift groups remain simultaneously visible in the approved side-by-side
  composition.
- Automated tests and quality gates pass.
- The Windows smoke-test procedure is recorded and performed before claiming
  end-to-end physical printing is verified.
