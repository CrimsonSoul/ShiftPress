# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

This is an Impeccable design-language category only. ShiftPress ships as a
Windows desktop Tkinter/ttk application using Microsoft Word COM.

## Users and Purpose

Operators prepare dated shift schedules from Word templates. Success means
printing exactly the needed documents without reprinting an already-used shift.
No user research, analytics, testimonials, or performance benchmarks are
available; do not invent them.

## Print contract

- Night and Day are independently included and dated, each with a single date
  or inclusive range. Fresh launch and **Reset run** enable both in Single date
  mode: Night today, Day tomorrow, using local calendar dates.
- Persist only template folders, printer, and dark color theme, never dates, modes, or
  include toggles. Disabling a shift or switching modes preserves its values;
  only enabled shifts and their active modes contribute jobs or validation.
- At least one job is required. Invalid enabled dates, missing required folders,
  missing printer selection, or unavailable date controls block Print locally.
  Filesystem, template, Word, and device checks belong to preflight; selected
  counts must never imply those checks already passed.
- Collect selections on the Tkinter thread and pass the same immutable manifest
  through preflight, confirmation, and the worker; workers never read Tk state.
  Jobs sort by date, with Night before Day for ties. Preview, large-batch
  confirmation, progress, results, and CSV failures must describe those actual
  jobs and the chosen printer.
- Preserve scheduling/template naming rules, range limits, root-contained paths,
  selective template preflight, and ambiguity rejection. Disabled shifts need
  no valid folder or template. Missing or ambiguous selected templates block
  before document processing.
- Lock setup and selection controls during a batch; keep Cancel/Escape and
  safe window-close behavior. Reset and keyboard Setup cannot bypass the lock.
  Check cancellation before every document; an
  active Word call is not interruptible. Always release Word and restore UI
  state. Preserve bounded transient COM retries and per-document CSV failures.
  Retain failures already recorded if the run is cancelled, aborted, or closed.
- Advance progress after a document attempt finishes. Distinguish full success,
  partial failure, and cancellation, with accurate counts and shift/date errors.
  “Sent to printer” does not establish that physical pages were printed.
- Open source documents read-only; replace dates across body/header/footer story
  ranges. Fail closed if macros cannot be disabled, the requested printer cannot
  be selected, any story traversal or date-processing operation fails, or no
  supported date was replaced. Never modify source templates. Close documents
  and quit Word without saving. A cleanup error after successful submission is
  logged separately and must not turn the submitted job into a retryable failure.

## Identity and settings

Preserve the ShiftPress identity. `src/app_paths.py` retains active
`ShiftPress`/`.shiftpress` and legacy `ShiftPrint`/`.shiftprint` paths. When the
active config is absent, `src/config.py` checks the legacy data directory and
older working-directory config. An existing active config always wins.

Write settings atomically. Rename a migration source to `config.json.migrated`
only after saving succeeds. If saving fails, keep the readable settings in memory
and the legacy file intact for retry. Migration failure must not prevent
startup; logs stay in their original location. Surface settings-save failures
before printing and on close. Keep the external Sonar key
`CrimsonSoul_ShiftPrint` to preserve the hosted project linkage.

## Related guides

[DESIGN.md](DESIGN.md) owns visual rules and icons. The
[Windows smoke test](docs/windows-smoke-test.md) owns real Word/physical-printer
evidence; automated tests alone do not establish that boundary.
