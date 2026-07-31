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
composition. Night uses written amber identity, Day uses written blue identity,
and both share the same native control structure.

## Memorable Moment

The operator can compare both selected shift scopes at once, then read one
full-width manifest that says exactly what paper the button will produce.

## Unresolved Decisions

Exact default window dimensions and final token values will be resolved against
the rendered Tkinter implementation and Windows display scaling.
