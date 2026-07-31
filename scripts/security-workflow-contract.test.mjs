import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parse } from 'yaml';

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test');

const [buildWorkflow, securityWorkflow] = await Promise.all([
  readFile(new URL('../.github/workflows/build.yml', import.meta.url), 'utf8'),
  readFile(new URL('../.github/workflows/security.yml', import.meta.url), 'utf8'),
]);

const build = parse(buildWorkflow);
const security = parse(securityWorkflow);
const normalizeExpression = (value) => value.replaceAll(/\s+/gu, ' ').trim();
const findStep = (job, name) => {
  assert.ok(job?.steps, `missing workflow job for step: ${name}`);
  const step = job.steps.find((candidate) => candidate.name === name);
  assert.ok(step, `missing workflow step: ${name}`);
  return step;
};

test('test pull requests emit the stable build quality gate', () => {
  assert.deepEqual(build.on.pull_request.branches, ['main', 'test']);
  assert.equal(build.jobs.quality.name, 'Build quality gate');
  assert.ok(
    !('needs' in build.jobs['package-windows']),
    'package-windows must not declare a needs dependency',
  );
});

test('scanner jobs retain stable required names and bounded CI entrypoints', () => {
  assert.equal(security.jobs.sonarqube.name, 'SonarQube quality gate');
  assert.equal(security.jobs.snyk.name, 'Snyk security gate');
  assert.equal(security.jobs.sonarqube['timeout-minutes'], 25);
  assert.equal(security.jobs.snyk['timeout-minutes'], 25);
  assert.match(
    findStep(security.jobs.sonarqube, 'Run Sonar finding gate').run,
    /security:sonar:ci/u,
  );
  assert.match(findStep(security.jobs.snyk, 'Run Snyk finding gate').run, /security:snyk:ci/u);
});

test('Snyk delegates internal test pull requests and merged pushes to its CI gate', () => {
  const snyk = security.jobs.snyk;
  assert.equal(snyk.name, 'Snyk security gate');
  assert.equal(
    normalizeExpression(snyk.if),
    normalizeExpression(`
      (github.event_name == 'push' && github.ref == 'refs/heads/test') ||
      (github.event_name == 'pull_request' &&
       github.event.pull_request.base.ref == 'test' &&
       github.event.pull_request.head.repo.full_name == github.repository)
    `),
  );

  const scanStep = findStep(snyk, 'Run Snyk finding gate');
  assert.equal(scanStep.run, 'npm run security:snyk:ci');
});
