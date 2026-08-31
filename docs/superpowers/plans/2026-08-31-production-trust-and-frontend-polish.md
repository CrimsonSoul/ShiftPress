# Production Trust and Frontend Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every finding from the 2026-08-31 ShiftPress codebase and frontend review, then re-run the frontend critique with a target score of 40/40.

**Architecture:** Keep the existing Tkinter/ttk visual system and controller boundaries. Make Word operations fail closed, make the controller own truthful completed-job outcomes, and make the UI derive actionable readiness from locally knowable state while leaving filesystem/Word checks in the existing preflight boundary. Add only direct helpers required by these behaviors; do not introduce new frameworks or abstraction layers.

**Tech Stack:** Python 3.12, Tkinter/ttk, pywin32 Word COM, tkcalendar, pytest, GitHub Actions, Impeccable.

**Spec:** `.impeccable/critique/2026-08-31T15-59-52Z__src-ui-py.md`

## Global Constraints

- Preserve the approved "Operator's Print Desk" visual direction in `DESIGN.md`.
- Preserve independent Night and Day selections and the common Night-today/Day-tomorrow defaults.
- Do not print when the requested printer cannot be selected or no supported date text was replaced.
- Advance progress only after a document attempt finishes; final status must match success, partial failure, or cancellation.
- Disable Print only for locally knowable blockers; keep file, template, Word, and printer-device checks in preflight.
- Preserve standard Tkinter/ttk widgets, Windows scaling, source-document read-only behavior, and the existing physical-printer smoke-test boundary.
- Keep user settings recoverable if migration cannot write the new destination.
- Permit release publication only from `refs/heads/main`.
- Do not add dependencies, commit, push, publish, or dispatch a release in this task.

---

### Task 1: Fail-closed Word preparation and printing

**Files:**
- Modify: `src/word_processor.py`
- Test: `tests/test_word_processor.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `WordProcessor.replace_dates(doc: Any, current_date: date) -> int`
- Produces: `_set_active_printer(printer_name: str) -> None` that propagates assignment failures
- Consumes: existing `print_document(...) -> tuple[bool, Optional[str]]`

- [ ] **Step 1: Write failing tests for printer selection, zero replacements, and macro hardening**

```python
def test_print_document_active_printer_failure_blocks_print(word_processor):
    success, error = word_processor.print_document(
        Path("schedule.docx"), date(2026, 8, 31), "Bad Printer"
    )
    assert success is False
    assert "Printer not found" in (error or "")
    word_processor.word_app.Documents.Open.return_value.PrintOut.assert_not_called()

def test_print_document_no_date_replacement_blocks_print(word_processor):
    with patch.object(word_processor, "replace_dates", return_value=0):
        success, error = word_processor.print_document(
            Path("schedule.docx"), date(2026, 8, 31), "Office Printer"
        )
    assert success is False
    assert "date" in (error or "").lower()
    word_processor.word_app.Documents.Open.return_value.PrintOut.assert_not_called()
```

- [ ] **Step 2: Run focused tests and confirm they fail for the old behavior**

Run: `.venv/bin/pytest tests/test_word_processor.py -k 'active_printer_failure or no_date_replacement or macros_cannot_be_disabled' -q`

- [ ] **Step 3: Implement the minimal fail-closed behavior**

```python
replacement_count = self.replace_dates(doc, current_date)
if replacement_count == 0:
    raise RuntimeError("No supported date text was found; document was not printed")
self._set_active_printer(printer_name)
self.safe_com_call(doc.PrintOut, False)
```

Count successful Word `Find.Execute` results in `replace_dates`. Treat inability to set `AutomationSecurity = 3` as initialization failure, allowing the existing cleanup to close COM safely. Update README wording to match the enforced behavior.

- [ ] **Step 4: Run the focused Word processor suite**

Run: `.venv/bin/pytest tests/test_word_processor.py -q`

---

### Task 2: Preserve configuration and enforce main-only releases

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config.py`
- Modify: `.github/workflows/build.yml`
- Test: `scripts/security-workflow-contract.test.mjs`

**Interfaces:**
- Preserves: `_migrate_from(legacy_path: Path) -> Optional[AppConfig]`
- Produces: legacy rename only after `save(config)` succeeds
- Produces: release condition requiring `github.ref == 'refs/heads/main'`

- [ ] **Step 1: Write failing migration and workflow-contract tests**

```python
def test_failed_migration_write_keeps_legacy_config_for_retry(tmp_path):
    manager = ConfigManager()
    manager.config_file = tmp_path / "ShiftPress" / "config.json"
    legacy_file = tmp_path / "ShiftPrint" / "config.json"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text('{"day_folder": "/old/day"}', encoding="utf-8")
    manager.legacy_config_files = (legacy_file,)
    with patch.object(manager, "save", side_effect=OSError("disk full")):
        config = manager.load()
    assert config.day_folder == "/old/day"
    assert legacy_file.exists()
```

```javascript
assert.match(buildWorkflow, /github\.ref == 'refs\/heads\/main'/u);
```

- [ ] **Step 2: Run both focused tests and verify the old contracts fail**

Run: `.venv/bin/pytest tests/test_config.py -k failed_migration_write -q`

Run: `node --test scripts/security-workflow-contract.test.mjs`

- [ ] **Step 3: Stop migration after a failed save and add the release ref guard**

```python
try:
    self.save(config)
except Exception as error:
    logger.warning("Could not save migrated settings: %s", error)
    return config
legacy_path.rename(legacy_path.with_suffix(".json.migrated"))
```

Require `github.ref == 'refs/heads/main'` in the Create Release step.

- [ ] **Step 4: Run configuration and workflow tests**

Run: `.venv/bin/pytest tests/test_config.py -q`

Run: `node --test scripts/*.test.mjs`

---

### Task 3: Make batch progress and final outcomes truthful

**Files:**
- Modify: `src/main.py`
- Modify: `src/ui.py`
- Test: `tests/test_main.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: `_print_job(...) -> bool`
- Produces: `_cancel_ui_update(completed_jobs: int, total_jobs: int) -> None`
- Consumes: `ScheduleAppUI.update_status(message, progress, level=...)`

- [ ] **Step 1: Write failing tests for progress timing and final states**

```python
def test_partial_failure_ends_in_error_status(schedule_app, print_request):
    schedule_app._print_job = Mock(side_effect=[True, False])
    schedule_app._process_batch(print_request)
    run_scheduled_callbacks(schedule_app)
    schedule_app.ui.update_status.assert_any_call(
        "Completed with 1 failed schedule", 100, level="error"
    )
```

- [ ] **Step 2: Run focused tests and confirm the premature 100%/Complete behavior**

Run: `.venv/bin/pytest tests/test_main.py tests/test_ui.py -k 'progress or partial_failure or cancel' -q`

- [ ] **Step 3: Implement completed-job progress and outcome-specific copy**

Before each Word call, show `Printing … (n/m)` at `completed / total`. After it returns, update to `(completed + 1) / total`. Use `level="success"` only when every job succeeds, `level="error"` for partial failure, and neutral `level="info"` for cancellation. Use correct `schedule`/`schedules` pluralization.

- [ ] **Step 4: Run controller and UI suites**

Run: `.venv/bin/pytest tests/test_main.py tests/test_ui.py -q`

---

### Task 4: Make readiness and setup state honest and actionable

**Files:**
- Modify: `src/ui.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: locally derived readiness blockers in `refresh_manifest_preview()`
- Produces: a three-line setup summary for Day templates, Night templates, and printer
- Preserves: controller preflight for filesystem contents, Word, and device availability

- [ ] **Step 1: Write failing tests for every locally knowable blocker**

Cover no enabled schedule, invalid ranges, an enabled schedule without its folder, no selected printer, and a missing `DateEntry` dependency. Assert that Print is disabled and the manifest card explains the first action required. Assert that a valid local selection uses neutral readiness copy rather than a green success claim.

- [ ] **Step 2: Run the focused UI tests and confirm the old optimistic state**

Run: `.venv/bin/pytest tests/test_ui.py -k 'readiness or setup_summary or missing_dateentry' -q`

- [ ] **Step 3: Implement local readiness and explicit setup state**

Derive blockers from enabled shifts, date-order validation, configured folders, printer selection, and dependency availability. Disable Print only while a blocker is present. Render separate Day templates, Night templates, and Printer lines in Setup. Refresh printer availability text whenever printers are refreshed. Rename the dialog action from Done to Close.

- [ ] **Step 4: Run the UI suite**

Run: `.venv/bin/pytest tests/test_ui.py -q`

---

### Task 5: Add keyboard, focus, help, and resilient-state polish

**Files:**
- Create: `.impeccable/config.json`
- Modify: `src/constants.py`
- Modify: `src/ui.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: `Alt+P` Print, `Alt+S` Setup, `Alt+H` How to use, and `Escape` to close Setup
- Produces: visible How to use action with concise task guidance
- Produces: explicit ttk focus styles and first-focus behavior in Setup
- Produces: hidden-until-active progress and wrapped long-state copy

- [ ] **Step 1: Record code-first Impeccable configuration**

Create `.impeccable/config.json` with `{"buildPath":"code"}`.

- [ ] **Step 2: Write failing interaction and degraded-state tests**

Assert root bindings for Print, Setup, and How to use; Escape binding and first focus in Setup; visible help action; focus-state style maps; hidden initial progress; and disabling with a direct dependency explanation when `DateEntry` is unavailable.

- [ ] **Step 3: Run the focused interaction tests and confirm failure**

Run: `.venv/bin/pytest tests/test_ui.py -k 'keyboard or focus or help or progress_visibility or dependency' -q`

- [ ] **Step 4: Implement the smallest native Tkinter polish**

Use Segoe UI Variable Display only for headings and Segoe UI Variable Text for body copy on Windows. Add blue, high-contrast focus treatment to interactive ttk styles. Add visible How to use and keyboard mnemonics. Focus the first Setup field, bind Escape, wrap long status and error copy, remove tooltip-only essential meaning, and reveal progress only while a run is active or has produced an outcome.

- [ ] **Step 5: Run UI and constant tests**

Run: `.venv/bin/pytest tests/test_ui.py tests/test_constants.py -q`

---

### Task 6: Verify the whole product and re-score the frontend

**Files:**
- Modify if runtime capture succeeds: `docs/screenshots/main.png`
- Update: `.impeccable/critique/2026-08-31T15-59-52Z__src-ui-py.md`

- [ ] **Step 1: Run focused regression tests for all changed behaviors**

Run: `.venv/bin/pytest tests/test_word_processor.py tests/test_config.py tests/test_main.py tests/test_ui.py -q`

Run: `node --test scripts/*.test.mjs`

- [ ] **Step 2: Inspect a real isolated native runtime**

Launch ShiftPress with a disposable application-data directory. Inspect default, Setup, Help, invalid-range, and long-path states. Capture `docs/screenshots/main.png` only from that genuine runtime and only if capture is reliable; otherwise preserve the documented Windows smoke-test requirement.

- [ ] **Step 3: Run the required single post-edit detector pass**

Run: `node /Users/ryan/.agents/skills/impeccable/scripts/detect.mjs --json src/ui.py`

- [ ] **Step 4: Run the complete repository gate**

Run: `.venv/bin/black --check src tests`

Run: `.venv/bin/mypy src --ignore-missing-imports`

Run: `.venv/bin/pylint src --fail-under=8.0`

Run: `.venv/bin/pytest --cov=src --cov-report=term-missing`

Run: `node --test scripts/*.test.mjs`

Run: `git diff --check`

- [ ] **Step 5: Re-run the Impeccable critique**

Run fresh frontend and detector assessments using the approved critique workflow, combine only verifiable evidence, and update the critique snapshot. Target 40/40. If a point depends on Windows Word COM or physical-printer evidence unavailable on this host, report that boundary instead of inferring success.

- [ ] **Step 6: Review the final diff and hand off without publication**

Inspect `git status --short --branch`, `git diff --stat`, and the changed source/test diff. Do not commit, push, merge, or dispatch a release.
