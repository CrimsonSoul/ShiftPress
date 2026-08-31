# ShiftPress repository instructions

`~/.codex/AGENTS.md` owns cross-project skill routing and engineering defaults.
This file adds only ShiftPress-specific commands, safety rules, and publishing
semantics.

## Working tree

- Inspect `git status --short --branch` before editing and before any commit or
  push. Preserve unrelated changes and never reformat the whole repository in a
  mixed worktree.
- `main` is the sole long-lived branch. Use temporary `codex/` branches for
  proposed changes.

## Sources of truth

- `.github/workflows/build.yml` defines the quality gate, Windows test, artifact,
  and release behavior; `.github/workflows/security.yml` defines the SonarQube
  and Snyk gates.
- `src/__init__.py` is the only release-version source. Never hand-enter a
  separate workflow version.
- `docs/windows-smoke-test.md` is the required real Word COM and physical-printer
  release checklist. `.impeccable/` holds the approved UI references.

## Verification

Run the Python checks in the active project environment. If they are not on
`PATH`, use the corresponding executable under `.venv/bin/`.

Before claiming a source, test, workflow, or configuration change complete, run:

```bash
black --check src tests
mypy src --ignore-missing-imports
pylint src --fail-under=8.0
pytest --cov=src --cov-report=term-missing
node --test scripts/*.test.mjs
git diff --check
```

Start with focused tests for the changed behavior. The Python suite mocks
Windows-only modules on non-Windows hosts; report that limitation. Do not claim
real printing is verified unless the Windows checklist was completed with Word
and a physical printer.

## Publishing and releases

- "Push the changes" means push the exact verified tip to a temporary `codex/`
  branch and open a pull request targeting `main`; never push directly or force
  push to `main`.
- Merge only after `Build quality gate`, `SonarQube quality gate`, and
  `Snyk security gate` all conclude successfully. Auto-merge may be enabled only
  after the user authorizes a push.
- After merge, fetch and fast-forward local `main`, then require zero divergence
  from `origin/main`. Every merged `main` push must produce its Windows artifact.
- A published release additionally requires the completed Windows smoke test, a
  committed `src/__init__.py` version bump, and an explicit Build workflow
  dispatch with `create_release` enabled. Never dispatch a release from an
  unverified or uncommitted version.
