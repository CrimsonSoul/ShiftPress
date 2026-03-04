# ShiftPress Icon Redesign & Repository Rename

**Date**: 2026-03-03

## Icon

- **Concept**: Calendar page with downward press/print arrow
- **Colors**: Amber (#F59E0B) on Zinc-900 (#18181B) rounded-square background
- **Calendar element**: Simplified page outline with top header bar and horizontal date-row lines
- **Press element**: Bold downward arrow overlapping bottom-right of calendar
- **Sizes**: 1024x1024 PNG source; ICO with 16/24/32/48/64/128/256px variants
- **Method**: SVG created programmatically, converted via Pillow/cairosvg to PNG and ICO
- **Files replaced**: `icon.png`, `icon.ico` (same filenames, no build config changes needed)

## Repository Rename

- **GitHub**: `CrimsonSoul/shift-automator-pro` -> `CrimsonSoul/ShiftPress` via `gh repo rename`
- **Local folder**: `/Users/ryan/Apps/shift-automator-pro` -> `/Users/ryan/Apps/ShiftPress`
- **Remote URL**: Updated to match new repo name
- **Redirects**: GitHub auto-redirects old URL; existing clones continue working

## Implementation Steps

1. Create SVG icon matching the design spec
2. Install cairosvg + Pillow if needed
3. Render SVG to 1024x1024 PNG
4. Generate multi-size ICO from PNG
5. Replace `icon.png` and `icon.ico` in repo root
6. Rename GitHub repo via `gh repo rename ShiftPress`
7. Rename local folder to `/Users/ryan/Apps/ShiftPress`
8. Update git remote URL
9. Verify build config still references correct icon files
10. Run tests, commit, push
