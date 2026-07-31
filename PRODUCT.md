# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is an operator responsible for preparing and printing shift
schedules. The exact organizational role is not yet confirmed.

## Product Purpose

ShiftPrint is a Windows desktop utility that turns Microsoft Word schedule
templates into dated print jobs. Success means the operator can deliberately
print only the schedules needed for a run without reprinting an already-used
shift.

## Positioning

ShiftPrint combines shift-specific schedule rules, template lookup, date
replacement, printer selection, and auditable failure handling in one focused
operator workflow.

## Operating Context

- The app runs on Windows and controls Microsoft Word through COM automation.
- Day and Night schedules use separate template folders and naming rules.
- A common run prints the selected date's Night schedule and the following
  date's Day schedule.
- Day and Night work must remain independent: each can use its own single date
  or date range within the same run.
- Operators may also need single-schedule and multi-date batch runs.

## Capabilities and Constraints

- Preserve template-folder configuration, printer selection, date replacement,
  preflight checks, background processing, cancellation, progress reporting,
  and CSV failure reports.
- A print run must contain at least one selected schedule job.
- Validation and template preflight must apply only to enabled schedule jobs.
- Job counts, progress, confirmation copy, and completion summaries must reflect
  the schedules actually selected.
- Windows, Microsoft Word, and `pywin32` are required for real document printing.
- The repository's automated tests mock Windows-only dependencies so logic and
  quality gates can run outside Windows.
- The `web` platform value above describes the closest Impeccable interface
  design-language category; the shipped product itself is a Windows desktop
  Tkinter application.

## Brand Commitments

- Preserve the ShiftPrint name.
- Application icons live at `icon.ico` and `icon.png`, regenerated from
  `tools/make_icon.py`; see the Icon section of DESIGN.md.
- The interface should use direct, operational language and avoid implying that
  configured template folders are automatically selected for printing.

## Evidence on Hand

- Current Tkinter implementation: `src/ui.py`
- Current controller and print workflow: `src/main.py`
- Existing automated tests: `tests/`
- Existing interface screenshot: `docs/screenshots/main.png`
- No user research, usage analytics, testimonials, or performance benchmarks
  are currently available and future work must not fabricate them.

## Product Principles

1. Make print intent explicit before execution.
2. Keep Day and Night schedules independently controllable.
3. Show the exact job count and scope before paper is consumed.
4. Preserve fast repeat use for the common Night-then-next-Day workflow.
5. Fail before printing when required inputs or templates are unavailable.
