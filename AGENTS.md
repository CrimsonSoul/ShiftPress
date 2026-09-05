# ShiftPress repository instructions

`~/.codex/AGENTS.md` owns cross-project routing and engineering defaults.

## Checkout and documentation

- Inspect `git status --short --branch` before editing, committing, or pushing.
  Preserve unrelated changes; never reformat the whole mixed checkout.
- Use only the primary checkout on local `main`: no linked worktrees or local
  feature branches. This project-specific exception overrides process-skill
  isolation defaults. `main` is the only local and long-lived branch; authorized
  publication uses a temporary remote `codex/` PR branch.
- Keep six canonical Markdown guides: this file (repository rules),
  [README](README.md) (setup), [PRODUCT](PRODUCT.md) (behavior/migration),
  [DESIGN](DESIGN.md) (visual rules), [surface brief](.impeccable/surfaces/src-ui-py.md)
  (UI validation), and [Windows smoke test](docs/windows-smoke-test.md) (release
  evidence). Read only the relevant guide. Consolidate durable decisions there;
  keep temporary plans, critiques, and reports in chat or outside the repository.
  Do not create persistent docs without a distinct ongoing need.

## Verification

`.github/workflows/build.yml` owns quality, Windows tests, artifacts, and
releases; `.github/workflows/security.yml` owns SonarQube/Snyk gates.

For source, test, workflow, or configuration changes, start with focused tests,
then run the complete checks in the active Python environment (use `.venv/bin/`
executables when absent from `PATH`):

```bash
black --check src tests
mypy src --ignore-missing-imports
pylint src --fail-under=8.0
pytest --cov=src --cov-report=term-missing
node --test scripts/*.test.mjs
git diff --check
```

For documentation-only changes, check Markdown formatting, retained links/file
references, and `git diff --check`; source checks are unnecessary. Non-Windows
Python tests mock Windows modules: report that limitation. Real printing is
verified only by completing the Windows checklist with Word and a physical
printer. Approved UI references live in `.impeccable/`.

## Publication and releases

- “Push the changes” authorizes publishing the exact verified local `main` tip
  to a temporary remote `codex/` branch and opening a PR to `main`. Never push
  directly or force push remote `main`. Auto-merge requires user push authority.
- Before merging, require successful `Build quality gate`, `windows-test`,
  `SonarQube quality gate`, and `Snyk security gate`; all four must also be
  required by GitHub branch protection.
- After merge, fetch and fast-forward local `main` when possible. For GitHub's
  squash-only merge reconciliation, require a clean checkout, local HEAD equal
  to the exact published PR head, identical HEAD/confirmed-merge trees, and the
  confirmed merge commit in `origin/main` history. Save local `main` in a
  verified external Git bundle, then `git reset --soft <confirmed-merge-sha>`
  and fast-forward to `origin/main`. If any check fails, preserve the checkout
  and report it. Never hard reset or discard unrelated work.
- Finish with only local `main`, zero divergence from `origin/main`, and the
  temporary remote PR branch deleted after confirmed merge. Verify each merged
  `main` push produces its Windows artifact.
- Releases additionally require successful packaged Windows startup evidence
  for the exact merged commit, a committed version bump in `src/__init__.py`
  (the sole version source), and explicit
  user authorization for a Build dispatch on `main` with `create_release`
  enabled. Never hand-enter a separate workflow version or dispatch a release
  from an unverified/uncommitted version. Word/physical-printer testing is
  separate: complete the Windows checklist before claiming print verification.
  Its unavailability does not block publication, but must be disclosed in the
  release notes. Known printing failures still block release.
