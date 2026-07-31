---
version: 1
slug: "src-ui-py"
primary_target: "src/ui.py"
related_targets: ["src/main.py"]
---

## Scope and Mode

- Surface: ShiftPress main Tkinter window (`src/ui.py`)
- Mode: Operate

## Audience and Job

An operator prepares deliberate Word-backed schedule print runs. The common
run is the current Night schedule plus the following Day schedule, while either
shift may independently use a single date or a range.

## Primary Task and Content

Confirm template/printer setup, independently include Night and Day work, set
each date scope, review the exact print manifest, then print. Both shifts must
remain visible. The manifest must state actual jobs and document counts.

## Constraints

- Standard Tkinter/ttk widgets only.
- Windows desktop, Microsoft Word COM, and physical printer workflow.
- Preserve cancellation, progress, preflight, and failure reporting.
- No custom Canvas controls, web effects, hidden tabs, or image-based widgets.
- Do not claim readiness before preflight succeeds.

## Chosen Direction

Low-risk Independent Shift Sections using the approved side-by-side
composition. Night uses written night-sky blue identity, Day uses written
daylight amber identity, and both share the same native control structure.

## Memorable Moment

The operator can compare both selected shift scopes at once, then read one
full-width manifest that says exactly what paper the button will produce.

## Resolved Decisions

Window dimensions are no longer fixed tokens. Both date modes are built to the
same height, and geometry and minimum size are derived from Tk's computed
requirement at launch, so the layout cannot clip its primary action under any
Windows text-scaling setting.

Shift identity resolved to night-sky blue for Night and daylight amber for Day,
matching the sun-and-moon reading an operator already carries.
