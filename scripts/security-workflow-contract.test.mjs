import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test');

const [buildWorkflow, securityWorkflow, sonarProperties] = await Promise.all([
  readFile(new URL('../.github/workflows/build.yml', import.meta.url), 'utf8'),
  readFile(new URL('../.github/workflows/security.yml', import.meta.url), 'utf8'),
  readFile(new URL('../sonar-project.properties', import.meta.url), 'utf8'),
]);

function jobBlock(workflow, id) {
  const sentinel = `${workflow.trimEnd()}\n  __end__: \n`;
  const match = sentinel.match(
    new RegExp(`^  ${id}:\\s*\\n([\\s\\S]*?)(?=^  [A-Za-z0-9_-]+:)`, 'mu'),
  );
  assert.ok(match, `missing workflow job: ${id}`);
  return match[1];
}

const normalizeExpression = (value) => value.replaceAll(/\s+/gu, ' ').trim();

function sonarProperty(name) {
  const prefix = `${name}=`;
  const matches = sonarProperties
    .split(/\r?\n/u)
    .filter((line) => line.startsWith(prefix));
  assert.equal(matches.length, 1, `expected one Sonar property: ${name}`);
  return matches[0].slice(prefix.length);
}

test('main pull requests emit stable build gates without weakening Windows packaging', () => {
  assert.match(buildWorkflow, /push:\s*\n\s+branches:\s*\n\s+- main/u);
  assert.doesNotMatch(buildWorkflow, /\s+- test\s*$/mu);
  assert.match(buildWorkflow, /permissions:\s*\n\s+contents: read/u);

  const quality = jobBlock(buildWorkflow, 'quality');
  assert.match(quality, /^    name: Build quality gate$/mu);
  assert.match(quality, /node --test scripts\/\*\.test\.mjs/u);

  const windows = jobBlock(buildWorkflow, 'windows-test');
  assert.match(windows, /runs-on: windows-latest/u);
  assert.match(windows, /win32print, pythoncom, win32com\.client, tkcalendar/u);

  const build = jobBlock(buildWorkflow, 'build');
  assert.match(build, /^    needs: \[quality, windows-test\]$/mu);
  assert.match(build, /^    permissions:\s*\n\s+contents: write$/mu);
  assert.match(build, /Smoke the built exe/u);
  assert.match(build, /Upload artifact/u);
  assert.match(build, /echo "retention=14"/u);
});

test('scanner jobs retain stable required names and bounded direct entrypoints', () => {
  const sonar = jobBlock(securityWorkflow, 'sonarqube');
  const snyk = jobBlock(securityWorkflow, 'snyk');

  assert.match(sonar, /^    name: SonarQube quality gate$/mu);
  assert.match(snyk, /^    name: Snyk security gate$/mu);
  assert.match(snyk, /^    runs-on: windows-latest$/mu);
  assert.match(sonar, /^    timeout-minutes: 25$/mu);
  assert.match(snyk, /^    timeout-minutes: 25$/mu);
  assert.match(sonar, /node scripts\/run-sonar-ci\.mjs "\$\{SONAR_SCOPE\[@\]\}"/u);
  assert.match(snyk, /run: pip install -r requirements-dev\.txt/u);
  assert.match(snyk, /run: node scripts\/run-snyk-ci\.mjs/u);
  assert.doesNotMatch(securityWorkflow, /npm (?:ci|run)/u);
});

test('Sonar generates and consumes one supported Python coverage report', () => {
  const sonar = jobBlock(securityWorkflow, 'sonarqube');
  const generated = sonar.match(/--cov-report=xml:([A-Za-z0-9_.-]+)/u);

  assert.ok(generated, 'Sonar job must generate Cobertura XML coverage');
  assert.equal(sonarProperty('sonar.python.coverage.reportPaths'), generated[1]);
  assert.match(generated[1], /\.xml$/u);
});

test('scanner jobs run only for internal main pull requests and merged main pushes', () => {
  const expected = normalizeExpression(`
    (github.event_name == 'push' && github.ref == 'refs/heads/main') ||
    (github.event_name == 'pull_request' &&
     github.event.pull_request.base.ref == 'main' &&
     github.event.pull_request.head.repo.full_name == github.repository)
  `);

  for (const id of ['sonarqube', 'snyk']) {
    const block = jobBlock(securityWorkflow, id);
    const guard = block.match(/^    if: >-\s*\n([\s\S]*?)(?=^    [A-Za-z0-9_-]+:)/mu);
    assert.ok(guard, `missing internal main guard for ${id}`);
    assert.equal(normalizeExpression(guard[1]), expected);
  }
});

test('scanner CLI installs are pinned without creating a Node project', () => {
  assert.match(securityWorkflow, /npm install --global[^\n]* @sonar\/scan@5\.0\.0/u);
  assert.match(securityWorkflow, /npm install --global[^\n]* snyk@1\.1306\.2/u);
  assert.doesNotMatch(securityWorkflow, /package(?:-lock)?\.json/u);
});

test('security runs are read-only, cancellable, and never manually dispatched', () => {
  assert.match(securityWorkflow, /permissions:\s*\n\s+contents: read/u);
  assert.match(securityWorkflow, /group: security-\$\{\{ github\.workflow \}\}-\$\{\{ github\.ref \}\}/u);
  assert.match(securityWorkflow, /cancel-in-progress: true/u);
  assert.doesNotMatch(securityWorkflow, /workflow_dispatch:/u);
});
