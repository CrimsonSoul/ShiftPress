---
version: 1
slug: "src-ui-py"
primary_target: "src/ui.py"
related_targets: ["src/main.py"]
---

## Scope and Mode

ShiftPress main Tkinter window, Setup, and How to use; mode: Operate. An operator
confirms setup, independently selects Night and Day dates/ranges, reviews the
exact manifest, and prints. The common run is Night today plus Day tomorrow.

## Chosen Direction

Dark-only precision scheduling desk; two palettes, Midnight and pink-focused
Rose. Generated targets: [Rose](../mocks/shiftpress-rose-reference.png) and
[Midnight](../mocks/shiftpress-midnight-reference.png). The user requested image
fidelity, dark-only color choices, and more distinctive typography; these are
implementation targets, not a claim of separate image approval.

THESIS: make the next shift's paper consequences effortless to inspect.
OWN-WORLD: dark ink, generous margins, precise native controls, tinted shift
headers; expressive headings over calm form text.
STORY: identify setup, select independent scopes, inspect output, print.
FIRST VIEWPORT: brand/theme/help rail, compact three-column setup, equal Night
and Day work areas, manifest and a single prominent action.
FORM: direction seed `16019748`, scheduling desk (candidate 3); horizontal
choice controls and full-width date rows. Native controls replace decorative
mockup pictograms and textures; typography follows the user's later request.

[PRODUCT.md](../../PRODUCT.md) owns behavior;
[DESIGN.md](../../DESIGN.md) owns tokens, layout, interactions, and icon rules.
Read those guides only when the task concerns their contract.

## Validation boundary

Render real Tk widgets for clipping, equal-height date modes, keyboard focus,
disabled/degraded states, long values, and main/Setup overflow. Check Windows
work-area sizing and text scaling; both shifts and the primary action must
remain reachable. Mocked widget tests and web-oriented detectors cannot prove
native geometry or usability. Use genuine current runtime screenshots only.
Verify all dropdowns in both palettes, help keyboard/overflow behavior, and a
short main window with Print/Cancel visible before and after form scrolling.

Readiness, progress, cancellation, and failure reporting must match the
controller. Complete the [Windows smoke test](../../docs/windows-smoke-test.md)
before claiming Word COM and physical printing are verified.
