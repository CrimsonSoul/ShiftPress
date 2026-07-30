<!-- SEED: established with the user before implementation; re-run $impeccable document once there's code to capture the actual tokens and components. -->
---
name: ShiftPress
description: A low-risk native print console for deliberate shift-schedule runs.
---

# Design System: ShiftPress

## Overview

**Creative North Star: "The Operator's Print Desk"**

ShiftPress should feel like a focused Windows utility an operator can trust
while preparing physical print jobs. It favors familiar controls, explicit
state, compact working density, and plain-language confirmation over decorative
metaphors. The interface may be distinctive through disciplined hierarchy and
semantic shift color, but it must remain visibly implementable with native
Tkinter/ttk widgets.

The visual system is flat, quiet, and operational. Configuration, print intent,
validation, and execution should read as separate layers without hiding the
information that determines what paper will be produced.

**Key Characteristics:**

- Native Windows utility conventions
- Simultaneously visible related work
- Explicit enabled, disabled, ready, and error states
- Restrained dark surfaces with semantic shift accents
- Exact print scope and document counts near the primary action

## Colors

Use a restrained dark neutral system with one action accent and narrow semantic
accents for shift identity.

### Primary

- **Press Amber** `[to be resolved during implementation]`: Reserved for the
  primary print action, focus, and Night-shift identity.

### Secondary

- **Day Signal Blue** `[to be resolved during implementation]`: Identifies
  Day-shift controls and status without competing with the primary action.
- **Ready Green** `[to be resolved during implementation]`: Indicates successful
  validation and print readiness.

### Neutral

- **Window Charcoal** `[to be resolved during implementation]`: Main application
  background.
- **Control Graphite** `[to be resolved during implementation]`: Group and field
  surfaces.
- **Divider Steel** `[to be resolved during implementation]`: Borders and
  separators.
- **Paper White** `[to be resolved during implementation]`: Primary text.
- **Muted Slate** `[to be resolved during implementation]`: Supporting labels
  and secondary status.

### Named Rules

**The Semantic Accent Rule.** Amber and blue identify Night and Day or convey a
real control state; they are not ambient decoration.

**The One Primary Action Rule.** Only the final print button receives the
strongest filled treatment.

## Typography

**Display Font:** Segoe UI with the native system sans-serif fallback

**Body Font:** Segoe UI with the native system sans-serif fallback

**Label Font:** Segoe UI; use a monospaced system face only for diagnostic paths
or log output.

**Character:** Familiar, workmanlike, and highly legible at ordinary Windows
desktop scaling. Hierarchy comes from size and weight, not all-caps decoration
or unusual letter spacing.

### Hierarchy

- **Headline:** Semibold and compact; names the current task.
- **Title:** Semibold; labels a schedule group or settings section.
- **Body:** Regular; explains state and consequences in plain language.
- **Label:** Regular or semibold; uses sentence case for fields and controls.

### Named Rules

**The Plain Label Rule.** Controls use sentence case and operational nouns:
"Include Night schedule", "Single date", and "Print 2 schedules".

## Layout

Use a single-window desktop work surface wide enough to show two peer task
groups side by side, with the exact default dimensions resolved against the
rendered Tkinter implementation and Windows text scaling. Related controls live
inside bordered native groups. The active print scope remains visible without
switching tabs or opening a modal. The window stays resizable and may expand
automatically when native content would otherwise clip.

Use a compact spacing rhythm with larger separation between configuration,
schedule intent, and execution. Preserve a clear top-to-bottom sequence:
understand setup, choose work, confirm exact scope, then print.

**The Visible Scope Rule.** Information that changes what will print must remain
on the main surface; do not hide one shift behind tabs or secondary navigation.

## Elevation & Depth

The system is flat. It uses tonal surface changes, one-pixel borders, and
spacing rather than shadows, glow, glass, or layered translucency. Focus and
selection are state changes, not simulated physical elevation.

**The Flat Native Rule.** No shadows are required for hierarchy; if a control
cannot be expressed cleanly with standard ttk state and border styling, simplify
the control.

## Shapes

Use native rectangular controls with square or gently softened corners. Avoid
large radii, pills, circular controls, and decorative clipping. Section identity
may use a narrow straight color bar or colored title text that is feasible with
ordinary frames and labels.

## Do's and Don'ts

### Do:

- **Do** build core interactions from standard Tkinter/ttk widgets already
  present in the project.
- **Do** keep Night and Day visually distinct while giving both the same control
  structure.
- **Do** state exact dates, ranges, document counts, printer, and readiness
  before execution.
- **Do** preserve keyboard navigation, Windows scaling, and disabled states.

### Don't:

- **Don't** use custom-painted gauges, animated canvases, browser effects, or
  image-based controls.
- **Don't** let configured template folders imply that a shift is selected for
  printing.
- **Don't** hide a selected schedule's dates or readiness behind a tab.
- **Don't** use color as the only indication of shift or validation state.
