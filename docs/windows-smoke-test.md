# Windows Print Smoke Test

Use this checklist on a Windows workstation with Microsoft Word, the intended
printer, and representative Day and Night template folders. Unit tests mock the
Windows-only interfaces; this checklist verifies the real Word COM and printer
path before release.

## Preparation

1. Install dependencies and launch ShiftPress with `start_app.bat`.
2. Open **Setup → Change…**, choose both template folders and the test printer,
   then select **Done**.
3. Confirm the collapsed Setup card says **Templates configured** and names the
   selected printer without exposing either folder path.
4. Use dates that have known Day and Night templates. Keep the printed pages for
   comparison with the manifest.

## Required Runs

For every run, compare the numbered **This run** manifest with both Word activity
and the physical printer output.

| Run | Night selection | Day selection | Expected result |
| --- | --- | --- | --- |
| Night only | Enabled, one date | Disabled | Exactly one Night document prints. No Day document opens or prints. |
| Day only | Disabled | Enabled, one date | Exactly one Day document prints. No Night document opens or prints. |
| Both | Enabled, one date | Enabled, one date | Exactly the two listed documents print in manifest order. |
| Mixed scope | Enabled, date range | Enabled, one date | Night prints every listed range document; Day prints only its listed date. |

## State and Safety Checks

- Change Night dates and confirm Day dates do not change; then repeat in the
  other direction.
- Disable either shift and confirm its card says **Not included**, the manifest
  removes it, and the button count decreases before printing.
- Disable both shifts and confirm printing is blocked.
- Select an invalid range for one enabled shift and confirm no documents print.
- Start a multi-document run, select **Cancel**, and confirm no unlisted
  documents print after cancellation takes effect.
- Confirm the progress percentage and final status use the manifest document
  count, not a fixed Day-plus-Night multiplier.
- Confirm missing-template and Word/printer failures name the affected shift and
  date, preserve the source documents, and appear in the failure report.

## Result

Record the Windows version, Word version, printer name, application commit, and
pass/fail result for each required run. A release is print-verified only after
all four runs and the state and safety checks pass on Windows.

## Refresh the README screenshot

The README has no screenshot. Capture one here, where a real Windows instance
with Microsoft Word exists:

1. Launch ShiftPress with both template folders configured and a printer
   selected.
2. Capture the main window to `docs/screenshots/main.png`.
3. Restore the README `## Preview` section above `## Core Features`:

   ```markdown
   ## Preview

   ![Main window](docs/screenshots/main.png)
   ```
