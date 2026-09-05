# Windows Print Smoke Test

Before release, run this checklist on Windows with Microsoft Word, the intended
physical printer, representative Day/Night template folders, and the release
candidate executable (or Python 3.12 via `start_app.bat`). Automated tests and
packaged startup checks do not establish physical printing.

## Preparation

1. Open **Setup…**, choose template folders and printer, then **Apply**. Reopen
   Setup, change a value, and **Cancel**; verify the prior settings return.
2. Confirm the summary identifies Night source, Day source, and printer
   separately with recognizable folder identities. Configured paths must not
   imply template or printer-device readiness.
3. Choose dates with known templates. Keep source copies and printed pages for
   comparison with the numbered **Print scope** manifest and Word activity.

## Required runs

| Run         | Night      | Day      | Physical output                                         |
| ----------- | ---------- | -------- | ------------------------------------------------------- |
| Night only  | One date   | Disabled | One Night document; no Day document opens or prints.    |
| Day only    | Disabled   | One date | One Day document; no Night document opens or prints.    |
| Both        | One date   | One date | Exactly two listed documents in manifest order.         |
| Mixed scope | Date range | One date | Every listed Night date and only the selected Day date. |

## State and safety

- Fresh launch and **Reset run** select Night today and Day tomorrow. Changes
  to one shift never change the other; values survive mode changes and
  disabling/re-enabling.
- Disable either shift: its state becomes **Not included**, its manifest jobs
  disappear, and the Print count decreases. Its missing/invalid folder must not
  block the enabled shift. Disabling both blocks printing.
- An invalid enabled range blocks all printing and identifies that shift.
  Missing/ambiguous selected templates fail before document processing.
- During a multi-document run, selection/setup controls are locked. Cancel
  stops before the next document after an active Word call finishes; Word
  resources are released. No unlisted document prints.
- Progress advances after each attempt and uses the manifest total. Final state
  distinguishes all-success, partial failure, and cancellation with exact
  counts. Compare sent-to-printer claims with the actual pages.
- Check body/header/footer dates. Source documents remain unchanged. A template
  with no supported date text and an unavailable requested printer must not
  print; macro-disable failure must block Word initialization.
- Failures identify the affected shift/date; failed document attempts appear in
  CSV reports. Settings-save failures are visible before printing and on close;
  logs retain diagnostic detail.
- Inspect main/Setup at Windows text scaling and constrained display size:
  no unreachable controls, keyboard focus follows scrolling, long values wrap,
  and shortcuts, Help, Apply/Cancel, and Escape behave as described.
- Switch between **Midnight** and **Rose**. Main, Setup, and calendars remain
  dark, selections and processing locks are unchanged, and the theme restores
  after closing/reopening. There is no light or system-following theme.

## Evidence

Record tester/date, Windows and Word versions, printer, exact application commit
and artifact, and pass/fail for each run and safety check. A release is
print-verified only after every required check passes with physical output.
Keep evidence in the release/task record rather than a new repository report.
Any screenshot added to README must show this genuine current Windows runtime;
do not reuse an obsolete screenshot or fabricate one.
