# ShiftPrint Finding-Only Scanner Gates Implementation Plan

**Goal:** Finish the Relay-derived Sonar and Snyk finding-only gates for ShiftPrint without introducing a Node package manifest, while preserving the verified Windows build and release safeguards.

**Architecture:** Keep the existing bounded Node gate runners as dependency-free orchestration around globally installed scanner executables. GitHub Actions produces Python LCOV coverage, invokes the Sonar and Snyk runners for internal pull requests and `test` pushes, and keeps transient scanner outages non-blocking while findings and configuration failures block. ShiftPrint begins with an empty reviewed Sonar exception manifest.

**Tech Stack:** Python 3.12, pytest/coverage, Node.js built-in test runner, SonarCloud, Snyk CLI, GitHub Actions, PyInstaller, pywin32, tkcalendar.

---

### Task 1: Adapt the scanner contracts to ShiftPrint

**Files:**
- Modify: `scripts/security-workflow-contract.test.mjs`
- Modify: `scripts/run-sonar-ci.test.mjs`
- Modify: `scripts/sonar-open-findings.test.mjs`
- Modify: `scripts/sonar-reviewed-issues.test.mjs`

1. Replace Relay package-script and 49-exception expectations with direct executable and zero-exception expectations.
2. Preserve regression coverage for scope restrictions, failure classification, deadlines, token redaction, and workflow job names.
3. Keep workflow contract inspection dependency-free so no `package.json` or npm install is required to run tests.

### Task 2: Complete direct scanner execution and workflows

**Files:**
- Modify: `scripts/run-sonar-ci.mjs`
- Create: `.github/workflows/security.yml`
- Modify: `.github/workflows/build.yml`

1. Invoke the globally installed Sonar scanner executable directly.
2. Add bounded Sonar and Snyk jobs for internal pull requests targeting `test` and pushes to `test`.
3. Generate LCOV for Sonar, install pinned scanner CLIs globally, and call the dependency-free Node runners.
4. Give the existing quality job the stable `Build quality gate` name, run scanner regression tests there, and preserve the Windows test plus `build` dependencies that prevent packaging or release after failed tests.

### Task 3: Verify locally and publish the implementation branch

**Files:**
- Verify all changed workflow and scanner files.

1. Run all 80 scanner regression tests.
2. Run the full Python quality sequence and the complete 248-test suite with coverage.
3. Validate workflow syntax and inspect the final diff for secrets, stale ShiftPress app naming, or Relay-specific assumptions.
4. Commit and push `ci/finding-only-scanner-gates`, open a pull request into `test`, and inspect GitHub Actions.
5. Configure required checks only after both scanner credentials exist and the checks have completed successfully; otherwise report the exact external blocker without weakening the fail-closed configuration behavior.
