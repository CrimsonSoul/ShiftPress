---
name: ShiftPress
description: A native print console for deliberate shift-schedule runs.
---

# Design System: ShiftPress

## Overview

“The Operator's Print Desk”: a dark precision scheduling desk with expressive
headings, generous margins, familiar native controls, and explicit paper
consequences. Tinted shift headers distinguish equal work areas; calm form text
keeps dates and counts easy to inspect. Build with standard Windows Tkinter/ttk
widgets; a plain Canvas provides native scrolling.

## Colors

[src/constants.py](src/constants.py) owns the exact `COLORS`, `THEMES`, and
`FONTS` tokens. [src/ui.py](src/ui.py) owns their native styles and state maps.
Reuse those sources rather than duplicating values in a second token catalog.

- **Midnight:** ink-blue surfaces, a pale blue action accent, sky-blue Night,
  and warm amber Day.
- **Rose:** plum-charcoal surfaces, a pink action accent, lavender Night,
  and warm peach Day. Both choices remain dark throughout main, Setup, and
  calendar and How to use surfaces; theme persistence follows [PRODUCT.md](PRODUCT.md).
- The strongest filled treatment belongs to Print. The action accent also
  identifies Setup values, outlined actions, and selected native indicators.
- Green reinforces progress and success; error rose reinforces errors and
  cancellation. Written labels identify shifts and state in both themes.

Windows captions request dark styling, with explicit theme caption/text colors
on Windows 11. Apply styling after native ownership/frame creation, and inherit
the ShiftPress icon in every owned title bar. Caption colors are best effort
where the operating system supports them.

## Typography

Use Bahnschrift for Windows brand, task, and card headings, with Segoe UI for
form text and controls. Development uses Avenir Next on macOS and Ubuntu on
Linux. The source-owned hierarchy gives the brand the largest size, then Setup,
task headings, and card titles; body and supporting text remain quieter.

Keep native point-sized fonts so Windows scales text normally. Use sentence
case and operational labels such as “Include Night schedule” and “Print 2
schedules”; pluralize counts correctly.

## Layout

- Sequence: brand/theme/help rail, compact three-column Setup summary,
  preparation heading, peer Night/Day cards, full-width Print scope, then status
  and one primary action. Dates, counts, printer, and blockers stay visible;
  never hide a shift behind tabs or configuration.
- Use generous outer margins and shared panel spacing. Windows DPI scales
  padding, gaps, dropdown arrows, and choice indicators alongside native text.
- Both cards use the same controls and equal-height single/range modes. Derive
  geometry from Tk's rendered requirements and Windows work area, including
  taskbar/frame allowances. Keep the window resizable; main and Setup overflow
  must scroll vertically and follow keyboard focus at high text scaling.
- Reserve Print/Cancel and status outside the scrolling form. Short work areas
  use tighter vertical gaps, not smaller fonts; permit narrower resizing than
  the preferred launch width and scale window-frame allowances with Windows DPI.

## Elevation & Depth

Use flat tonal surfaces and one-pixel borders. Tinted title bands establish
shift identity; focus and selection change native states. Avoid shadows, glow,
gradients, browser effects, and image-based widgets.

## Shapes

Use rectangular or gently softened native controls; avoid pills, large radii,
decorative circles, and clipping. Keep native checkbox and radio indicators.

## Components

- Setup identifies Night source, Day source, and printer separately with compact
  recognizable folder identities. The native dialog preserves **Apply** and
  **Cancel** rollback; opening it focuses the first field, Escape cancels.
- Shift panels use full-width tinted title bands, an include checkbox,
  horizontal Single date/Date range choices, labels above full-width date rows,
  and a neutral selected count. Range fields share the row evenly.
- Inputs have dark fields and visible borders. Calendar popups follow the theme,
  using the shift accent with dark text for the selected day. Buttons distinguish
  filled Print/Cancel, outlined Setup/help, and quieter Reset run/log actions.
- Theme and printer choices use dark native menus with selected-item indicators.
  Their buttons and date pickers share one native field/arrow layout, height,
  typography, padding, and visible focus borders. Date arrows are integrated,
  not a separate narrow button; readonly fields have no light selection patch.
- How to use is a non-modal, themed reference window with numbered workflow
  steps, selectable read-only text, overflow scrolling, and a fixed Close action.
  On opening, measure the rendered text at its actual width and fit the window
  to the content, capped to the monitor work area. Only show a scrollbar when
  the screen or a user's resize genuinely leaves content out of view.
  Escape closes it and returns focus to the help button without changing a run.

## Do's and Don'ts

- Disable only locally invalid runs and explain the actionable blocker inline.
  Keep selected counts neutral until preflight; expose checking, active work,
  success, partial failure, and cancellation honestly. Errors name the affected
  shift; valid peer cards retain their own status.
- Preserve explicit focus styles, keyboard navigation, Alt+S/P/H, Escape,
  **Reset run**, and visible **How to use** guidance. Essential information
  cannot live only in hover tooltips or color. Wrap long paths, printer names,
  and status text; keep controls reachable when dependencies are unavailable.
- Reveal progress, scrollbars, and logs when relevant. Preserve meaningful
  outcomes; diagnostic detail belongs in logs with plain recovery actions.

## Icon

An ivory printer on neutral ink-charcoal, with equal blue and rose schedule
bars, fits both Midnight and Rose. Keep the same mark in both themes and in
every native title bar, taskbar, Explorer, and packaged executable.

[icon.png](icon.png) is the full-resolution image-generated master, including
its generation prompt metadata. `python tools/make_icon.py` exports `icon.ico`
(16/24/32/48/64/128/256px) directly from that master without replacing it.
The root's default Tk window icon propagates to owned dialogs; PyInstaller uses
the same ICO for the executable and bundles both assets. Pillow stays a
development-only dependency. Commit the master and exported ICO together.

For behavior see [PRODUCT.md](PRODUCT.md); for native runtime validation see
the [surface brief](.impeccable/surfaces/src-ui-py.md).
