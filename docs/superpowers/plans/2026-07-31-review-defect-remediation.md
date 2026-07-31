# Review Defect Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the fifteen defects found in the ShiftPress frontend design and backend functionality review, without regressing the existing 219-test suite or the quality gates.

**Architecture:** Nine independently reviewable tasks. Backend correctness first (template collisions, COM retries, dead constants), then a pure-domain validation method that the UI work depends on, then the three UI tasks, then CI, then docs and copy. Each task is test-driven and ends in a commit.

**Tech Stack:** Python 3.12, Tkinter/ttk, tkcalendar, pywin32 (Word COM), pytest + pytest-cov, black, mypy, pylint, PyInstaller, GitHub Actions.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-31-review-defect-remediation-design.md`. Read it before starting.
- Work directly on the current branch (`test`). No worktree.
- All 219 existing tests must stay green. Run the full suite before every commit.
- `black --check src tests` must stay clean. Run `black src tests` before committing.
- `mypy src` must report no issues.
- `pylint src --fail-under=8.0` must pass. Current score is 8.85; do not regress below 8.0.
- Python 3.12 is required. The system `python3` on this host is 3.9 and will not work. Use a 3.12 virtualenv.
- Tests mock all Windows-only modules (`win32print`, `pythoncom`, `win32com`, `win32com.client`, `tkcalendar`) in `tests/conftest.py`. Never import them unguarded at module scope.
- `tests/test_ui.py` patches every `ttk` widget class and uses `MagicMock(spec=tk.Tk)` as root. Real geometry is unavailable there; `winfo_reqheight()` returns a `MagicMock`, not an integer.
- Colour tokens are the frozen dataclass in `src/constants.py`. Use `COLORS.<name>`, never a raw hex literal.
- Copy uses sentence case and operational nouns per `DESIGN.md` ("The Plain Label Rule").

### Environment setup

Run once before Task 1:

```bash
/opt/homebrew/bin/python3.12 -m venv .venv312 && .venv312/bin/pip install -q --upgrade pip && .venv312/bin/pip install -q -r requirements-dev.txt
```

All `pytest`, `black`, `mypy`, `pylint` commands below assume `.venv312/bin/` on the path. Add `.venv312/` to `.gitignore` in Task 1 if it is not already ignored.

---

### Task 1: Template collision detection

Two template files whose stems normalize identically (e.g. `Thursday Night.docx` and `Thursday  Night.docx` with a double space) currently collapse into one cache key. The survivor depends on directory iteration order, and the wrong schedule prints with no error and no warning.

**Files:**
- Modify: `src/word_processor.py:79` (cache type annotation), `src/word_processor.py:176-199` (`_build_template_cache`), `src/word_processor.py:270-368` (`find_template_file`)
- Test: `tests/test_word_processor.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WordProcessor._build_template_cache(folder_path: str) -> dict[str, list[str]]`; `WordProcessor._template_cache: dict[str, dict[str, list[str]]]`; `WordProcessor._resolve_unique(base_name: str, paths: list[str]) -> str` raising `TemplateLookupError`. `find_template_file(folder: str, template_name: str) -> Optional[str]` keeps its existing signature and return type.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_word_processor.py` inside `class TestWordProcessor`:

```python
    def test_colliding_normalized_names_raise(self, wp, tmp_path):
        """Two files that normalize to the same name must not silently shadow."""
        (tmp_path / "Thursday Night.docx").write_text("dummy")
        (tmp_path / "Thursday  Night.docx").write_text("dummy")

        with pytest.raises(TemplateLookupError) as exc:
            wp.find_template_file(str(tmp_path), "Thursday Night")

        message = str(exc.value)
        assert "Thursday Night.docx" in message
        assert "Thursday  Night.docx" in message

    def test_collision_check_does_not_break_normal_lookup(self, wp, tmp_path):
        """A folder without collisions must resolve exactly as before."""
        (tmp_path / "Monday.docx").write_text("dummy")
        (tmp_path / "Thursday Night.docx").write_text("dummy")
        (tmp_path / "THIRD Thursday.docx").write_text("dummy")

        assert wp.find_template_file(str(tmp_path), "Monday").endswith("Monday.docx")
        assert wp.find_template_file(str(tmp_path), "Thursday").endswith(
            "Thursday Night.docx"
        )
        assert wp.find_template_file(str(tmp_path), "THIRD Thursday").endswith(
            "THIRD Thursday.docx"
        )
```

Update the import at the top of the file from `from src.word_processor import WordProcessor` to:

```python
from src.word_processor import WordProcessor, TemplateLookupError
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv312/bin/pytest tests/test_word_processor.py -k "collid or collision" -v`
Expected: `test_colliding_normalized_names_raise` FAILS with `DID NOT RAISE <class 'src.word_processor.TemplateLookupError'>`.

- [ ] **Step 3: Change the cache to hold every colliding path**

In `src/word_processor.py`, change the attribute annotation in `__init__`:

```python
        self._template_cache: dict[str, dict[str, list[str]]] = {}
```

Replace `_build_template_cache` entirely:

```python
    def _build_template_cache(self, folder_path: str) -> dict[str, list[str]]:
        """Build a normalized template cache for a folder.

        Scans *folder_path* for ``.docx`` files, filtering out Word lock
        files (``~$*``) and hidden files (``.*``).

        Args:
            folder_path: Absolute path to the template folder.

        Returns:
            Dict mapping normalized (lower-cased, whitespace-collapsed) base
            names to every file path that normalizes to that name.  A name
            with more than one path is a collision and is rejected at lookup
            time rather than silently resolved.
        """

        cache: dict[str, list[str]] = {}
        for entry in Path(folder_path).iterdir():
            name = entry.name
            # Skip Word temp lock files and hidden files
            if name.startswith("~$") or name.startswith("."):
                continue
            if name.lower().endswith(DOCX_EXTENSION):
                base_name = " ".join(entry.stem.lower().split())
                cache.setdefault(base_name, []).append(str(entry))
        for paths in cache.values():
            paths.sort()
        return cache
```

- [ ] **Step 4: Add the collision guard**

Add this method to `WordProcessor`, directly above `find_template_file`:

```python
    @staticmethod
    def _resolve_unique(base_name: str, paths: list[str]) -> str:
        """Return the single path for *base_name*, or reject the collision.

        Args:
            base_name: The normalized template name that was matched.
            paths: Every file path that normalizes to *base_name*.

        Returns:
            The one matching file path.

        Raises:
            TemplateLookupError: If more than one file normalizes to the
                same name, which would otherwise print an arbitrary file.
        """
        if len(paths) > 1:
            names = ", ".join(sorted(Path(p).name for p in paths))
            raise TemplateLookupError(
                f"Multiple template files resolve to the same name "
                f"'{base_name}': {names}. Rename templates to be unique."
            )
        return paths[0]
```

- [ ] **Step 5: Route every lookup branch through the guard**

In `find_template_file`, replace the body of the `for attempt in range(2):` loop (currently `src/word_processor.py:299-365`) with:

```python
        for attempt in range(2):
            cache = self._template_cache[folder_path]

            # 1. Try exact match
            if template_name_lower in cache:
                target = self._resolve_unique(
                    template_name_lower, cache[template_name_lower]
                )
                logger.debug(f"Template exact match: '{template_name}' -> {target}")
                return target

            # 2. Try robust matching using word boundaries
            # This prevents "Thursday" matching "THIRD Thursday"
            # but allows "Thursday" matching "Thursday Night" if it's the only match
            pattern = re.compile(rf"\b{re.escape(template_name_lower)}\b")

            matched_keys: list[str] = []
            for base_name in cache:
                if pattern.search(base_name):
                    # Special logic: if search term doesn't have "third" but filename does, skip
                    # This prevents "Thursday" matching "THIRD Thursday"
                    if "third" not in template_name_lower and "third" in base_name:
                        continue
                    matched_keys.append(base_name)

            if len(matched_keys) == 1:
                key = matched_keys[0]
                target = self._resolve_unique(key, cache[key])
                logger.info(f"Found robust template match: {target}")
                return target
            if len(matched_keys) > 1:
                # Prefer the most specific key: an exact stem, then a prefix.
                starts = [k for k in matched_keys if k.startswith(template_name_lower)]
                if len(starts) == 1:
                    target = self._resolve_unique(starts[0], cache[starts[0]])
                    logger.info(f"Found specific template match: {target}")
                    return target

                candidates = sorted(
                    path for key in matched_keys for path in cache[key]
                )
                raise TemplateLookupError(
                    f"Ambiguous template matches for '{template_name}'. "
                    f"Please rename templates to be unique. Matches: {candidates}"
                )

            # Not found: refresh once in case templates were added during runtime.
            # Only refresh if we had a pre-existing cache; if we just built the cache,
            # refreshing again is unlikely to help and only adds I/O.
            if attempt == 0 and had_cache:
                logger.debug(
                    f"Template not found; refreshing cache for {folder_path} and retrying"
                )
                self._ensure_template_cache(folder_path, force_refresh=True)
                continue

            logger.warning(f"Template not found: {template_name} in {folder}")
            return None
```

Note: the old exact-stem branch is now redundant, because an exact stem equals the cache key and is already handled by branch 1. The prefix branch is retained.

- [ ] **Step 6: Run the full suite**

Run: `.venv312/bin/pytest -q`
Expected: PASS, 221 passed.

- [ ] **Step 7: Run the quality gates**

Run:
```bash
.venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: black reformats nothing or only the files you touched; mypy reports success; pylint scores at or above 8.0.

- [ ] **Step 8: Commit**

```bash
git add src/word_processor.py tests/test_word_processor.py
git commit -m "fix: reject template names that collide after normalization"
```

---

### Task 2: COM retry precision

`safe_com_call` treats the bare substring `"server"` as transient, so a permanent fault like "The server threw an exception" burns five retries at one second each, per document.

**Files:**
- Modify: `src/word_processor.py:256` (the `transient_keywords` tuple)
- Test: `tests/test_word_processor.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no signature change. `safe_com_call(func, *args, retries=COM_RETRIES, delay=COM_RETRY_DELAY)` behaves identically except for which error strings it considers transient.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_word_processor.py` inside `class TestWordProcessor`:

```python
    def test_permanent_server_error_is_not_retried(self, wp):
        """A permanent COM fault must fail fast instead of burning retries."""
        call = MagicMock(side_effect=Exception("The server threw an exception"))

        with pytest.raises(Exception, match="threw an exception"):
            wp.safe_com_call(call, retries=3, delay=0)

        assert call.call_count == 1

    def test_busy_server_error_is_retried(self, wp):
        """A genuinely transient COM fault must still be retried."""
        call = MagicMock(
            side_effect=[Exception("Server is busy"), Exception("Server is busy"), "ok"]
        )

        assert wp.safe_com_call(call, retries=3, delay=0) == "ok"
        assert call.call_count == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv312/bin/pytest tests/test_word_processor.py -k "server" -v`
Expected: `test_permanent_server_error_is_not_retried` FAILS with `assert 3 == 1`.

- [ ] **Step 3: Narrow the transient keyword list**

In `src/word_processor.py`, inside `safe_com_call`, replace:

```python
                transient_keywords = ("rejected", "call was rejected", "busy", "server")
```

with:

```python
                # Specific transient COM markers only.  A bare "server" match
                # would also catch permanent faults such as "The server threw
                # an exception", costing retries * delay seconds per document.
                transient_keywords = (
                    "call was rejected",
                    "rejected by callee",
                    "server is busy",
                    "message filter",
                    "rpc_e_",
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv312/bin/pytest tests/test_word_processor.py -k "server or com_call" -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite and gates**

Run:
```bash
.venv312/bin/pytest -q && .venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: 223 passed; all gates clean.

If an existing test asserted retry behaviour using the word "server" alone, update it to use "Server is busy".

- [ ] **Step 6: Commit**

```bash
git add src/word_processor.py tests/test_word_processor.py
git commit -m "fix: retry only genuinely transient COM faults"
```

---

### Task 3: Remove dead Word story constants

Six `WD_*_STORY` constants are defined and exported but imported nowhere. They are fossils of a removed header/footer-only mode.

**Files:**
- Modify: `src/constants.py:39-44` (`__all__` entries), `src/constants.py:126-133` (definitions and comment)

**Interfaces:**
- Consumes: nothing.
- Produces: `WD_FIND_CONTINUE` and `WD_REPLACE_ALL` remain exported and unchanged. The six story constants no longer exist.

- [ ] **Step 1: Confirm they are unused**

Run: `grep -rn "STORY" src/ tests/ | grep -v "WD_FIND\|WD_REPLACE"`
Expected: only the definition and `__all__` lines in `src/constants.py`. If anything else appears, stop and report it.

- [ ] **Step 2: Delete the `__all__` entries**

In `src/constants.py`, remove these six lines from the `__all__` list:

```python
    "WD_PRIMARY_HEADER_STORY",
    "WD_EVEN_PAGES_HEADER_STORY",
    "WD_PRIMARY_FOOTER_STORY",
    "WD_EVEN_PAGES_FOOTER_STORY",
    "WD_FIRST_PAGE_HEADER_STORY",
    "WD_FIRST_PAGE_FOOTER_STORY",
```

- [ ] **Step 3: Delete the definitions**

In `src/constants.py`, remove this block entirely:

```python
# Word story types (used to target header/footer-only replacements)
# https://learn.microsoft.com/en-us/office/vba/api/word.wdstorytype
WD_EVEN_PAGES_HEADER_STORY: Final = 6  # wdEvenPagesHeaderStory
WD_PRIMARY_HEADER_STORY: Final = 7  # wdPrimaryHeaderStory
WD_EVEN_PAGES_FOOTER_STORY: Final = 8  # wdEvenPagesFooterStory
WD_PRIMARY_FOOTER_STORY: Final = 9  # wdPrimaryFooterStory
WD_FIRST_PAGE_HEADER_STORY: Final = 10  # wdFirstPageHeaderStory
WD_FIRST_PAGE_FOOTER_STORY: Final = 11  # wdFirstPageFooterStory
```

Leave the `# Word Find/Replace constants` block that follows it intact.

- [ ] **Step 4: Run the full suite and gates**

Run:
```bash
.venv312/bin/pytest -q && .venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: 223 passed; all gates clean. Any `ImportError` means Step 1 missed a reference.

- [ ] **Step 5: Commit**

```bash
git add src/constants.py
git commit -m "refactor: drop unused Word story constants"
```

---

### Task 4: Shift-labelled selection validation

`validate_date_range` produces "End date cannot be before start date" with no shift label, and the UI has no way to ask "is this one shift valid?" without building the whole manifest. This task adds the pure domain method that Task 7 and `_validate_inputs` both consume.

**Files:**
- Modify: `src/print_manifest.py:7` (import), `src/print_manifest.py:21-43` (`ShiftSelection`)
- Test: `tests/test_print_manifest.py`

**Interfaces:**
- Consumes: `validate_date_range(start: date, end: date) -> tuple[bool, Optional[str]]` from `src/scheduler.py`.
- Produces: `ShiftSelection.validate() -> Optional[str]`. Returns `None` when the selection is valid or disabled; otherwise a shift-labelled human-readable message. Task 7 and Task 9 rely on this exact name and return type.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_print_manifest.py`:

```python
def test_validate_accepts_a_valid_single_date() -> None:
    """A well-formed single-date selection has no error."""
    assert _selection("night").validate() is None


def test_validate_ignores_a_disabled_selection() -> None:
    """A shift that is not included cannot be invalid."""
    selection = _selection(
        "day",
        enabled=False,
        mode="range",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 1),
    )

    assert selection.validate() is None


def test_validate_labels_a_reversed_range_with_its_shift() -> None:
    """A reversed range must name the shift it belongs to."""
    selection = _selection(
        "night",
        mode="range",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 1),
    )

    error = selection.validate()

    assert error is not None
    assert error.startswith("Night schedule:")
    assert "End date cannot be before start date" in error


def test_validate_labels_a_missing_date_with_its_shift() -> None:
    """A missing date must name the shift it belongs to."""
    selection = _selection("day", start_date=None, end_date=None)

    assert selection.validate() == "Select a Day date"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv312/bin/pytest tests/test_print_manifest.py -k validate -v`
Expected: FAIL with `AttributeError: 'ShiftSelection' object has no attribute 'validate'`.

- [ ] **Step 3: Import the range validator**

In `src/print_manifest.py`, change:

```python
from .scheduler import get_date_range, get_shift_template_name
```

to:

```python
from .scheduler import get_date_range, get_shift_template_name, validate_date_range
```

- [ ] **Step 4: Add the method**

Add to `ShiftSelection`, directly below `active_range`:

```python
    def validate(self) -> Optional[str]:
        """Return a shift-labelled error for this selection, or None if valid.

        A disabled selection is always valid: an excluded shift contributes
        no jobs, so its date values cannot block a run.

        Returns:
            ``None`` when this selection can contribute jobs, otherwise a
            human-readable message naming the shift at fault.
        """
        if not self.enabled:
            return None
        label = self.shift_type.title()
        try:
            start_date, end_date = self.active_range()
        except ValueError as e:
            return str(e)
        is_valid, error_msg = validate_date_range(start_date, end_date)
        if not is_valid:
            return f"{label} schedule: {error_msg}"
        return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv312/bin/pytest tests/test_print_manifest.py -v`
Expected: PASS, 14 passed (10 existing + 4 new).

- [ ] **Step 6: Run the full suite and gates**

Run:
```bash
.venv312/bin/pytest -q && .venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: 227 passed; all gates clean.

- [ ] **Step 7: Commit**

```bash
git add src/print_manifest.py tests/test_print_manifest.py
git commit -m "feat: add shift-labelled selection validation"
```

---

### Task 5: Equal-height date modes and content-derived window size

The single-date row is a label beside an entry (34px); the range rows are labels above entries (60px). Toggling modes changes layout height by 26px and the window never re-fits, and `minsize` (720) is below the required height (759), so the Print button can be clipped by 37 of its 61 pixels.

**Files:**
- Modify: `src/constants.py:32-34,52` (`__all__`), `src/constants.py:99-101,117-120` (definitions), `src/ui.py:28-41` (imports), `src/ui.py:199-214` (`__init__` sizing), `src/ui.py:246-253` (post-construction sizing), `src/ui.py:930-942` (single-date row), `src/ui.py:1121-1139` (`_auto_resize_to_content`)
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ScheduleAppUI._apply_content_sizing() -> None`, replacing `_auto_resize_to_content`. `WINDOW_HEIGHT` and `WINDOW_MIN_HEIGHT` no longer exist in `src/constants.py`. `WINDOW_WIDTH`, `AUTO_RESIZE_MIN_WIDTH`, `AUTO_RESIZE_MIN_HEIGHT` remain.

- [ ] **Step 1: Expose the patched Label class to tests**

In `tests/test_ui.py`, in the `ui` fixture, change:

```python
        ), patch("src.ui.ttk.Label"), patch(
```

to:

```python
        ), patch("src.ui.ttk.Label") as MockLabel, patch(
```

and add this line beside the other `_test_*` assignments:

```python
            ui._test_label_class = MockLabel
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_ui.py` inside `class TestScheduleAppUI`:

```python
    def test_single_date_row_matches_range_row_structure(self, ui):
        """Both date modes must build the same label-above-entry shape."""
        panel = ui._shift_panels["night"]

        panel.single_picker.pack.assert_any_call(fill="x")
        panel.range_start_picker.pack.assert_any_call(fill="x")
        panel.range_end_picker.pack.assert_any_call(fill="x")
        assert panel.single_picker.grid.call_count == 0

        date_labels = [
            call
            for call in ui._test_label_class.call_args_list
            if call.kwargs.get("text") == "Date"
        ]
        assert len(date_labels) == 2  # one per shift panel
        assert date_labels[0].kwargs["style"] == "CardSub.TLabel"

    def test_window_sizing_derives_from_rendered_content(self, ui, root):
        """minsize and geometry must come from content, not a hardcoded guess."""
        root.winfo_reqheight.return_value = 812
        root.winfo_reqwidth.return_value = 1000
        root.winfo_screenwidth.return_value = 1920
        root.winfo_screenheight.return_value = 1080
        root.minsize.reset_mock()
        root.geometry.reset_mock()

        ui._apply_content_sizing()

        root.minsize.assert_called_once_with(1040, 812)
        root.geometry.assert_called_once_with("1040x812")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv312/bin/pytest tests/test_ui.py -k "single_date_row or window_sizing" -v`
Expected: both FAIL — the first with `assert 1 == 0` on `single_picker.grid.call_count`, the second with `AttributeError: 'ScheduleAppUI' object has no attribute '_apply_content_sizing'`.

- [ ] **Step 4: Restructure the single-date row**

In `src/ui.py`, inside `_create_shift_panel`, replace:

```python
        single_wrap = ttk.Frame(date_stack, style="Card.TFrame")
        single_wrap.grid(row=0, column=0, sticky="ew")
        single_wrap.grid_columnconfigure(1, weight=1)
        ttk.Label(single_wrap, text="Date:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 14)
        )
        single_picker = self._create_date_entry(
            date_entry_cls,
            single_wrap,
            calendar_kw=self._calendar_kwargs(),
        )
        single_picker.grid(row=0, column=1, sticky="ew")
        single_picker.set_date(default_date)
```

with:

```python
        # Label-above-entry mirrors the range rows so both modes occupy the
        # same height and toggling never reflows the window.
        single_wrap = ttk.Frame(date_stack, style="Card.TFrame")
        single_wrap.grid(row=0, column=0, sticky="ew")
        ttk.Label(single_wrap, text="Date", style="CardSub.TLabel").pack(
            anchor="w", pady=(0, 6)
        )
        single_picker = self._create_date_entry(
            date_entry_cls,
            single_wrap,
            calendar_kw=self._calendar_kwargs(),
        )
        single_picker.pack(fill="x")
        single_picker.set_date(default_date)
```

- [ ] **Step 5: Replace the sizing logic**

In `src/ui.py`, replace the whole `_auto_resize_to_content` method with:

```python
    def _apply_content_sizing(self) -> None:
        """Size the window from rendered content so it cannot clip itself.

        Deriving both the initial geometry and the minimum size from Tk's
        computed requirement keeps the primary action visible under any
        Windows text-scaling setting, which a hardcoded height cannot.
        Both date modes are the same height by construction, so the
        requirement does not change after launch.
        """

        try:
            self.root.update_idletasks()
            req_w = self.root.winfo_reqwidth()
            req_h = self.root.winfo_reqheight()
            scr_w = self.root.winfo_screenwidth()
            scr_h = self.root.winfo_screenheight()

            target_w = min(
                max(WINDOW_WIDTH, req_w), max(AUTO_RESIZE_MIN_WIDTH, scr_w - 80)
            )
            target_h = min(
                max(AUTO_RESIZE_MIN_HEIGHT, req_h),
                max(AUTO_RESIZE_MIN_HEIGHT, scr_h - 80),
            )

            self.root.minsize(target_w, target_h)
            self.root.geometry(f"{target_w}x{target_h}")
        except Exception as e:
            logger.debug(f"Content sizing skipped: {e}")
```

- [ ] **Step 6: Rewire construction**

In `src/ui.py` `__init__`, delete these two statements:

```python
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
```

and

```python
        # Provide a sane minimum size; DPI scaling can otherwise clip content.
        try:
            self.root.minsize(WINDOW_WIDTH, WINDOW_MIN_HEIGHT)
        except Exception as e:
            logger.debug(f"Could not set minimum window size: {e}")
```

Then replace:

```python
        # If DPI scaling / fonts push content beyond default height, expand once.
        self._auto_resize_to_content()
```

with:

```python
        # Derive geometry and minimum size from the rendered content.
        self._apply_content_sizing()
```

Finally remove `WINDOW_HEIGHT` and `WINDOW_MIN_HEIGHT` from the `from .constants import (...)` block at the top of `src/ui.py`.

- [ ] **Step 7: Remove the now-unused constants**

In `src/constants.py`, delete `"WINDOW_HEIGHT",` and `"WINDOW_MIN_HEIGHT",` from `__all__`, and delete these lines:

```python
WINDOW_HEIGHT: Final = 720
```

```python
WINDOW_MIN_HEIGHT: Final = 720
```

Keep `WINDOW_WIDTH`, `WINDOW_RESIZABLE`, `AUTO_RESIZE_MIN_WIDTH`, and `AUTO_RESIZE_MIN_HEIGHT`.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv312/bin/pytest tests/test_ui.py -v`
Expected: PASS.

- [ ] **Step 9: Verify against real Tk**

Create `/tmp/measure.py`:

```python
import sys, tkinter as tk
from datetime import date
sys.path.insert(0, ".")
from src.ui import ScheduleAppUI

root = tk.Tk()
ui = ScheduleAppUI(root, today=date(2026, 7, 31))
root.update_idletasks()
p = ui._shift_panels["night"]
single_h = p.single_wrap.winfo_reqheight()
p.mode_var.set("range"); ui._sync_shift_panel_state("night")
root.update_idletasks()
range_h = p.range_wrap.winfo_reqheight()
print(f"single={single_h} range={range_h} equal={single_h == range_h}")
print(f"minsize={root.minsize()} reqheight={root.winfo_reqheight()}")
root.destroy()
```

Run: `.venv312/bin/python /tmp/measure.py`
Expected: `equal=True`, and the `minsize` height equal to `reqheight`.

- [ ] **Step 10: Run the full suite and gates**

Run:
```bash
.venv312/bin/pytest -q && .venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: 229 passed; all gates clean.

- [ ] **Step 11: Commit**

```bash
git add src/ui.py src/constants.py tests/test_ui.py
git commit -m "fix: size window from content and equalize date mode heights"
```

---

### Task 6: Folder-path setters own the placeholder contract

`ShiftPressApp._load_config` calls `.delete()` / `.insert()` on entry widgets it does not own, bypassing the placeholder's colour contract, so a saved path renders in placeholder gray (`#B5B7BD`) instead of primary text (`#F4F4F5`).

**Files:**
- Modify: `src/ui.py:1304-1322` (`_browse_folder`), `src/ui.py` (new setters near the public getters), `src/main.py:125-143` (`_load_config`)
- Test: `tests/test_ui.py`, `tests/test_main.py:559-579`

**Interfaces:**
- Consumes: `_PATH_PLACEHOLDER` (module constant, already present in `src/ui.py`).
- Produces: `ScheduleAppUI.set_day_folder(path: str) -> None` and `ScheduleAppUI.set_night_folder(path: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui.py` inside `class TestScheduleAppUI`:

```python
    def test_set_day_folder_uses_primary_text_color(self, ui):
        """A real saved path must not render as placeholder gray."""
        ui.set_day_folder("C:/Templates/Day")

        ui.day_entry.config.assert_called_with(foreground=COLORS.text_main)
        ui.day_entry.insert.assert_called_with(0, "C:/Templates/Day")

    def test_set_night_folder_empty_restores_placeholder(self, ui):
        """An empty saved path must fall back to the dim placeholder."""
        ui.set_night_folder("")

        ui.night_entry.config.assert_called_with(foreground=COLORS.text_dim)
        ui.night_entry.insert.assert_called_with(0, _PATH_PLACEHOLDER)
```

Update the `src.ui` import at the top of `tests/test_ui.py`:

```python
from src.ui import ScheduleAppUI, _PATH_PLACEHOLDER
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv312/bin/pytest tests/test_ui.py -k "set_day_folder or set_night_folder" -v`
Expected: FAIL with `AttributeError: 'ScheduleAppUI' object has no attribute 'set_day_folder'`.

- [ ] **Step 3: Add the setters**

In `src/ui.py`, add these three methods immediately above `get_day_folder`, under the `# Public getters` divider:

```python
    def _set_folder_entry(self, entry: Optional[ttk.Entry], path: str) -> None:
        """Write one path entry, honoring the placeholder and colour contract.

        Args:
            entry: The target entry widget, or ``None`` if not yet built.
            path: The folder path to show.  Empty restores the placeholder.
        """
        if entry is None:
            return
        value = (path or "").strip()
        entry.delete(0, tk.END)
        if value:
            entry.config(foreground=COLORS.text_main)
            entry.insert(0, value)
        else:
            entry.config(foreground=COLORS.text_dim)
            entry.insert(0, _PATH_PLACEHOLDER)

    def set_day_folder(self, path: str) -> None:
        """Set the Day templates folder shown in Setup."""
        self._set_folder_entry(self.day_entry, path)

    def set_night_folder(self, path: str) -> None:
        """Set the Night templates folder shown in Setup."""
        self._set_folder_entry(self.night_entry, path)
```

- [ ] **Step 4: Route browse through the same contract**

In `src/ui.py` `_browse_folder`, replace:

```python
        if path:
            entry.delete(0, tk.END)
            entry.config(foreground=COLORS.text_main)
            entry.insert(0, path)
            logger.debug(f"Selected folder: {path}")
            self.refresh_setup_summary()
```

with:

```python
        if path:
            self._set_folder_entry(entry, path)
            logger.debug(f"Selected folder: {path}")
            self.refresh_setup_summary()
```

- [ ] **Step 5: Use the setters from the controller**

In `src/main.py` `_load_config`, replace:

```python
            config = self.config_manager.load()
            if config.day_folder and self.ui.day_entry:
                self.ui.day_entry.delete(0, tk.END)
                self.ui.day_entry.insert(0, config.day_folder)
            if config.night_folder and self.ui.night_entry:
                self.ui.night_entry.delete(0, tk.END)
                self.ui.night_entry.insert(0, config.night_folder)
            if config.printer_name and self.ui.printer_var:
```

with:

```python
            config = self.config_manager.load()
            self.ui.set_day_folder(config.day_folder)
            self.ui.set_night_folder(config.night_folder)
            if config.printer_name and self.ui.printer_var:
```

If `tkinter as tk` becomes unused in `src/main.py` after this change, leave the import: it is still used for `tk.Tk` type hints and `tk.TclError` in `_safe_after`.

- [ ] **Step 6: Update the existing controller test**

In `tests/test_main.py`, in `test_load_config_populates_entries`, replace:

```python
        app.ui.day_entry.insert.assert_called_with(0, "/saved/day")
        app.ui.night_entry.insert.assert_called_with(0, "/saved/night")
```

with:

```python
        app.ui.set_day_folder.assert_called_with("/saved/day")
        app.ui.set_night_folder.assert_called_with("/saved/night")
```

- [ ] **Step 7: Run the full suite and gates**

Run:
```bash
.venv312/bin/pytest -q && .venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: 231 passed; all gates clean.

- [ ] **Step 8: Commit**

```bash
git add src/ui.py src/main.py tests/test_ui.py tests/test_main.py
git commit -m "fix: render saved template paths as entered text"
```

---

### Task 7: Manifest pluralization, semantic state styles, per-shift error attribution

Three defects share one function. The manifest title hardcodes the plural ("This run: 1 schedules"); the two count-label styles are byte-identical and always success green, so an error renders as success; and one shift's bad date flags both shifts with a message that names neither.

**Files:**
- Modify: `src/ui.py:44-49` (imports), `src/ui.py:464-475` (count styles), `src/ui.py:976-980` (count label creation), `src/ui.py:1405-1475` (`refresh_manifest_preview`)
- Test: `tests/test_ui.py:218-256` (update two existing tests), plus new tests

**Interfaces:**
- Consumes: `ShiftSelection.validate() -> Optional[str]` from Task 4.
- Produces: styles `CountReady.TLabel`, `CountMuted.TLabel`, `CountError.TLabel`. Helper methods `ScheduleAppUI._set_count(shift_type, text, style) -> None`, `_document_noun(count) -> str`, `_print_button_text(count) -> str`, `_describe_manifest(selections, manifest) -> tuple[str, list[str]]`, `_refresh_shift_counts(selections, errors) -> None`.

- [ ] **Step 1: Update the two existing tests that pin the old behaviour**

In `tests/test_ui.py`, in `test_manifest_preview_uses_actual_selected_job_count`, replace:

```python
        ui._shift_panels["night"].count_label.config.assert_called_with(
            text="Selected · 1 document"
        )
        ui._shift_panels["day"].count_label.config.assert_called_with(
            text="Selected · 1 document"
        )
```

with:

```python
        ui._shift_panels["night"].count_label.config.assert_called_with(
            text="Selected · 1 document", style="CountReady.TLabel"
        )
        ui._shift_panels["day"].count_label.config.assert_called_with(
            text="Selected · 1 document", style="CountReady.TLabel"
        )
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_ui.py` inside `class TestScheduleAppUI`:

```python
    def test_single_schedule_manifest_reads_as_singular(self, ui):
        """A one-document run must not read 'This run: 1 schedules'."""
        ui._shift_panels["day"].enabled_var.set(False)
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        assert (
            ui.manifest_title_label.config.call_args.kwargs["text"]
            == "This run: 1 schedule"
        )
        ui.print_btn.config.assert_called_with(text="Print 1 schedule")

    def test_excluded_shift_uses_muted_state_not_success(self, ui):
        """An excluded shift must not render in success green."""
        ui._shift_panels["day"].enabled_var.set(False)
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        ui._shift_panels["day"].count_label.config.assert_called_with(
            text="Not included", style="CountMuted.TLabel"
        )

    def test_invalid_night_range_does_not_flag_valid_day(self, ui):
        """One shift's bad dates must not accuse the other shift."""
        night = ui._shift_panels["night"]
        night.mode_var.set("range")
        night.range_start_picker.set_date(date(2026, 8, 10))
        night.range_end_picker.set_date(date(2026, 8, 1))
        ui.manifest_title_label = MagicMock()
        ui.manifest_label = MagicMock()
        ui.print_btn = MagicMock()

        ui.refresh_manifest_preview()

        night.count_label.config.assert_called_with(
            text="Check Night date selection", style="CountError.TLabel"
        )
        ui._shift_panels["day"].count_label.config.assert_called_with(
            text="Selected · 1 document", style="CountReady.TLabel"
        )
        title = ui.manifest_title_label.config.call_args.kwargs["text"]
        assert title == "This run: Check Night date selection"
        body = ui.manifest_label.config.call_args.kwargs["text"]
        assert "Night schedule: End date cannot be before start date" in body
        ui.print_btn.config.assert_called_with(text="Print schedules")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv312/bin/pytest tests/test_ui.py -k "singular or muted_state or invalid_night" -v`
Expected: all three FAIL — the first on `'This run: 1 schedules' != 'This run: 1 schedule'`, the others on the missing `style=` keyword.

- [ ] **Step 4: Replace the count-label styles**

In `src/ui.py` `_configure_styles`, replace:

```python
        self.style.configure(
            "NightCount.TLabel",
            font=FONTS.bold,
            foreground=COLORS.success,
            background=COLORS.surface,
        )
        self.style.configure(
            "DayCount.TLabel",
            font=FONTS.bold,
            foreground=COLORS.success,
            background=COLORS.surface,
        )
```

with:

```python
        # Semantic readiness states.  Colour reinforces the label text; it is
        # never the only signal, per the DESIGN.md validation-state rule.
        for count_style, count_color in (
            ("CountReady.TLabel", COLORS.success),
            ("CountMuted.TLabel", COLORS.text_dim),
            ("CountError.TLabel", COLORS.error),
        ):
            self.style.configure(
                count_style,
                font=FONTS.bold,
                foreground=count_color,
                background=COLORS.surface,
            )
```

- [ ] **Step 5: Point the count label at the ready style**

In `src/ui.py` `_create_shift_panel`, replace:

```python
        count_label = ttk.Label(
            card,
            text="Selected · 1 document",
            style=f"{label}Count.TLabel",
        )
```

with:

```python
        count_label = ttk.Label(
            card,
            text="Selected · 1 document",
            style="CountReady.TLabel",
        )
```

- [ ] **Step 6: Import PrintJob for the manifest type hint**

In `src/ui.py`, change:

```python
from .print_manifest import (
    DateMode,
    ShiftSelection,
    ShiftType,
    build_print_manifest,
)
```

to:

```python
from .print_manifest import (
    DateMode,
    PrintJob,
    ShiftSelection,
    ShiftType,
    build_print_manifest,
)
```

- [ ] **Step 7: Rewrite the preview**

In `src/ui.py`, replace the entire `refresh_manifest_preview` method with these six methods:

```python
    @staticmethod
    def _document_noun(count: int) -> str:
        """Return the correctly pluralized document noun for *count*."""
        return "document" if count == 1 else "documents"

    @staticmethod
    def _print_button_text(count: int) -> str:
        """Return the count-bearing label for the primary action."""
        if count == 0:
            return "Print schedules"
        if count == 1:
            return "Print 1 schedule"
        return f"Print {count} schedules"

    def _set_count(self, shift_type: ShiftType, text: str, style: str) -> None:
        """Set one panel's count line text and readiness style together."""
        self._shift_panels[shift_type].count_label.config(text=text, style=style)

    def _refresh_shift_counts(
        self,
        selections: tuple[ShiftSelection, ShiftSelection],
        errors: dict[ShiftType, Optional[str]],
    ) -> None:
        """Update each panel independently so one bad shift cannot accuse the other."""
        for selection in selections:
            shift_type = selection.shift_type
            if not selection.enabled:
                self._set_count(shift_type, "Not included", "CountMuted.TLabel")
            elif errors[shift_type]:
                self._set_count(
                    shift_type,
                    f"Check {shift_type.title()} date selection",
                    "CountError.TLabel",
                )
            else:
                count = len(build_print_manifest((selection,)))
                self._set_count(
                    shift_type,
                    f"Selected · {count} {self._document_noun(count)}",
                    "CountReady.TLabel",
                )

    def _describe_manifest(
        self,
        selections: tuple[ShiftSelection, ShiftSelection],
        manifest: tuple[PrintJob, ...],
    ) -> tuple[str, list[str]]:
        """Return the manifest title and one numbered line per included shift."""
        if not manifest:
            return "This run: No schedules selected", []

        total = len(manifest)
        title = f"This run: {total} schedule{'' if total == 1 else 's'}"
        lines: list[str] = []
        row_number = 1
        for selection in selections:
            if not selection.enabled:
                continue
            count = sum(
                1 for job in manifest if job.shift_type == selection.shift_type
            )
            lines.append(
                f"{row_number}. {self._format_selection_summary(selection, count)}"
            )
            row_number += 1
        return title, lines

    def refresh_manifest_preview(self) -> None:
        """Refresh the preflight-neutral manifest copy and count-aware action."""
        if len(self._shift_panels) != 2:
            return

        selections = self.get_shift_selections()
        errors: dict[ShiftType, Optional[str]] = {
            selection.shift_type: selection.validate() for selection in selections
        }
        self._refresh_shift_counts(selections, errors)

        invalid = [s for s in selections if errors[s.shift_type]]
        if invalid:
            manifest: tuple[PrintJob, ...] = ()
            names = " and ".join(s.shift_type.title() for s in invalid)
            title = f"This run: Check {names} date selection"
            lines = [errors[s.shift_type] or "" for s in invalid]
        else:
            manifest = build_print_manifest(selections)
            title, lines = self._describe_manifest(selections, manifest)

        printer = self.get_printer_name()
        printer_label = (
            printer
            if printer and printer != DEFAULT_PRINTER_LABEL
            else "Choose a printer"
        )
        lines.append(f"Printer: {printer_label}")

        if self.manifest_title_label is not None:
            self.manifest_title_label.config(text=title)
        if self.manifest_label is not None:
            self.manifest_label.config(text="\n".join(lines))
        if self.print_btn is not None:
            self.print_btn.config(text=self._print_button_text(len(manifest)))
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv312/bin/pytest tests/test_ui.py -v`
Expected: PASS.

- [ ] **Step 9: Run the full suite and gates**

Run:
```bash
.venv312/bin/pytest -q && .venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: 234 passed; all gates clean.

- [ ] **Step 10: Commit**

```bash
git add src/ui.py tests/test_ui.py
git commit -m "fix: attribute date errors per shift and pluralize run scope"
```

---

### Task 8: Use the shared validator in the controller

`_validate_inputs` performs its own inline range checking, which is now a second implementation of the same rule. Route it through `ShiftSelection.validate()` so the preview and the blocking validation can never diverge.

**Files:**
- Modify: `src/main.py:16` (import), `src/main.py:182-190` (inline validation loop)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `ShiftSelection.validate() -> Optional[str]` from Task 4.
- Produces: no signature change to `_validate_inputs`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_main.py`, in the class that holds the other `_validate_inputs` tests:

```python
    def test_validate_inputs_reports_shift_labelled_range_error(self, app):
        """A reversed Night range must be rejected with the shift named."""
        night = ShiftSelection(
            shift_type="night",
            enabled=True,
            mode="range",
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 1),
            folder="/templates/night",
        )
        day = ShiftSelection(
            shift_type="day",
            enabled=False,
            mode="single",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
            folder="/templates/day",
        )
        app.ui.get_shift_selections.return_value = (night, day)

        request, error = app._validate_inputs()

        assert request is None
        assert error == "Night schedule: End date cannot be before start date"
```

Ensure `tests/test_main.py` imports what the test needs:

```python
from src.print_manifest import ShiftSelection
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv312/bin/pytest tests/test_main.py -k shift_labelled -v`
Expected: FAIL — the current message is `Invalid Night date selection: End date cannot be before start date`.

- [ ] **Step 3: Import the validator path**

In `src/main.py`, remove `validate_date_range` from the scheduler import if it becomes unused:

```python
from .scheduler import get_english_day_name
```

- [ ] **Step 4: Replace the inline loop**

In `src/main.py` `_validate_inputs`, replace:

```python
        for selection in enabled_selections:
            label = selection.shift_type.title()
            try:
                start_date, end_date = selection.active_range()
            except ValueError as e:
                return None, str(e)
            is_valid, error_msg = validate_date_range(start_date, end_date)
            if not is_valid:
                return None, f"Invalid {label} date selection: {error_msg}"
```

with:

```python
        for selection in enabled_selections:
            selection_error = selection.validate()
            if selection_error:
                return None, selection_error
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv312/bin/pytest tests/test_main.py -v`
Expected: PASS. If an existing test asserted the old `"Invalid Night date selection: ..."` wording, update it to the new `"Night schedule: ..."` wording.

- [ ] **Step 6: Run the full suite and gates**

Run:
```bash
.venv312/bin/pytest -q && .venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: 235 passed; all gates clean. Pylint's `too-many-branches` and `too-many-locals` warnings on `_validate_inputs` should reduce.

- [ ] **Step 7: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "refactor: validate shift selections through one shared rule"
```

---

### Task 9: CI gates, release versioning, docs, and copy

The build job can publish a release while tests fail, the documented pylint gate is not enforced, the release version is hand-typed and drifts from the in-app version, the README's only visual shows a differently-named app with a different layout, and the README advertises a removed feature.

**Files:**
- Modify: `.github/workflows/build.yml`, `README.md:15-30`, `docs/windows-smoke-test.md`, `src/main.py:575` (dialog copy), `src/main.py:94` (comment)
- Delete: `docs/screenshots/main.png`

**Interfaces:**
- Consumes: nothing.
- Produces: no code interfaces. `src/__init__.py.__version__` becomes the single source of release version truth.

- [ ] **Step 1: Make the build depend on quality**

In `.github/workflows/build.yml`, change:

```yaml
  build:
    if: github.event_name == 'workflow_dispatch'
    runs-on: windows-latest
```

to:

```yaml
  build:
    needs: quality
    if: github.event_name == 'workflow_dispatch'
    runs-on: windows-latest
```

- [ ] **Step 2: Enforce the documented pylint gate**

In the `quality` job, add this step immediately after the `Type check` step:

```yaml
      - name: Lint
        run: pylint src --fail-under=8.0
```

- [ ] **Step 3: Single-source the release version**

Remove the `version` input from `workflow_dispatch`, leaving:

```yaml
on:
  workflow_dispatch:
    inputs:
      create_release:
        description: "Create a GitHub Release"
        type: boolean
        default: false
```

In the `build` job, add this step immediately after `Install dependencies`:

```yaml
      - name: Read version
        id: version
        shell: bash
        run: |
          v=$(python -c "import re, pathlib; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path('src/__init__.py').read_text()).group(1))")
          echo "value=$v" >> "$GITHUB_OUTPUT"
```

Then replace every `${{ inputs.version }}` with `${{ steps.version.outputs.value }}`, in the artifact name and both release fields:

```yaml
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: ShiftPress-v${{ steps.version.outputs.value }}
          path: dist/*.exe
          retention-days: 90

      - name: Create Release
        if: inputs.create_release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: v${{ steps.version.outputs.value }}
          name: v${{ steps.version.outputs.value }}
          generate_release_notes: true
          files: dist/*.exe
```

- [ ] **Step 4: Validate the workflow YAML**

Run:
```bash
.venv312/bin/python -c "import yaml, pathlib; d = yaml.safe_load(pathlib.Path('.github/workflows/build.yml').read_text()); print(d['jobs']['build']['needs']); print([s.get('name') for s in d['jobs']['quality']['steps']])"
```
Expected: prints `quality`, and a step list containing `Lint`. If `yaml` is missing, run `.venv312/bin/pip install -q pyyaml` first.

- [ ] **Step 5: Remove the stale screenshot**

Run:
```bash
git rm docs/screenshots/main.png
```

In `README.md`, delete these three lines:

```markdown
## Preview

![Main window](docs/screenshots/main.png)

```

- [ ] **Step 6: Remove the advertised feature that does not exist**

In `README.md`, delete this line from Core Features:

```markdown
- Date replacement automation with optional header/footer-only mode
```

and replace it with:

```markdown
- Date replacement across body, header, and footer story ranges
```

- [ ] **Step 7: Record the screenshot refresh in the smoke test**

Append to `docs/windows-smoke-test.md`:

```markdown
## Refresh the README screenshot

The README has no screenshot. Capture one here, where a real Windows instance
with Microsoft Word exists:

1. Launch ShiftPress with both template folders configured and a printer selected.
2. Capture the main window to `docs/screenshots/main.png`.
3. Restore the README `## Preview` section above `## Core Features`:

   ```markdown
   ## Preview

   ![Main window](docs/screenshots/main.png)
   ```
```

- [ ] **Step 8: Fix the failure-dialog copy**

In `src/main.py` `_show_failure_summary`, replace:

```python
        message += "\n\nTip: Click 'Open Logs' in the app footer."
```

with:

```python
        message += "\n\nTip: Click 'Open logs' in the app footer."
```

- [ ] **Step 9: Correct the keyboard-shortcut comment**

In `src/main.py` `__init__`, replace:

```python
        # Set up button command and keyboard shortcuts (Enter = start, Escape = cancel)
```

with:

```python
        # Wire the print button. Enter starts a run only while the button has
        # focus; Escape cancels from anywhere in the window.
```

- [ ] **Step 10: Run the full suite and gates**

Run:
```bash
.venv312/bin/pytest -q && .venv312/bin/black src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```
Expected: 235 passed; all gates clean. If a test asserted the `'Open Logs'` wording, update it.

- [ ] **Step 11: Verify no stale references remain**

Run:
```bash
grep -rn "header/footer\|main.png\|inputs.version" README.md .github/ docs/ src/ || echo "clean"
```
Expected: only the smoke-test doc's instructions for restoring the screenshot.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "ci: gate releases on quality and single-source the version"
```

---

## Final verification

After Task 9, run the complete gate set one more time and confirm the numbers:

```bash
.venv312/bin/pytest -q && .venv312/bin/black --check src tests && .venv312/bin/mypy src && .venv312/bin/pylint src --fail-under=8.0
```

Expected: 235 passed, black clean, mypy clean, pylint at or above 8.0.

Then re-run the real-Tk measurement from Task 5 Step 9 and confirm `equal=True` and `minsize` height equal to `reqheight`.

Report the final test count, coverage percentage, and pylint score.
